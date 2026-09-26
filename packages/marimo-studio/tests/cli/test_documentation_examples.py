"""Execute copyable documentation examples at their consumer boundaries."""

from __future__ import annotations

import ast
import asyncio
import re
import shlex
from pathlib import Path
from typing import cast

import click
import marimo
from click.testing import CliRunner

import marimo_studio
import marimo_studio.agent as studio_agent
import marimo_studio.authoring as studio_authoring
import marimo_studio.view_providers as studio_view_providers
from marimo_studio._artifacts.repository import validate_document
from marimo_studio._cli import cli
from marimo_studio._views.inspection import inspection_request
from marimo_studio._workspace.project_manifest import (
    encode_view_manifest,
    load_view_project,
)
from marimo_studio.view_providers import ViewProvider
from marimo_studio.view_providers._host.registry import ProviderRegistry

from ..provider_test_support import (
    candidate,
    provider_build_request,
    provider_starter_context,
)


def _documentation_paths() -> tuple[Path, ...]:
    paths = {
        Path("README.md"),
        *Path(".github/release-notes").glob("*.md"),
        Path("packages/marimo-studio/README.md"),
        *Path("docs").rglob("*.md"),
        *Path("skills/marimo-studio").rglob("*.md"),
    }
    return tuple(sorted(path for path in paths if path.is_file()))


def _fenced_blocks(document: str, language: str) -> tuple[str, ...]:
    sections = document.split(f"```{language}\n")[1:]
    return tuple(section.split("\n```", 1)[0] for section in sections)


def _python_block(document: str, heading: str) -> str:
    return _fenced_blocks(document.split(heading, 1)[1], "python")[0]


def _studio_cli_arguments(arguments: tuple[str, ...]) -> tuple[str, ...] | None:
    if arguments[:1] == ("marimo-studio",):
        return arguments[1:]
    if arguments[:1] == ("uvx",):
        start = 1
    elif arguments[:2] == ("uv", "run"):
        start = 2
    else:
        return None

    while start < len(arguments) and arguments[start].startswith("-"):
        option = arguments[start]
        if option == "--":
            start += 1
            break
        name, separator, _value = option.partition("=")
        assert name in {"--from", "--with", "--project"}, (
            f"Unrecognized documented uv option: {option}"
        )
        start += 1 if separator else 2

    if arguments[start : start + 1] == ("marimo-studio",):
        return arguments[start + 1 :]
    return None


def _console_commands(document: str) -> tuple[tuple[str, ...], ...]:
    commands: list[tuple[str, ...]] = []
    for block in _fenced_blocks(document, "console"):
        pending = ""
        for raw_line in block.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("export "):
                continue
            if line.endswith("\\"):
                pending += line.removesuffix("\\").rstrip() + " "
                continue
            pending += line
            try:
                arguments = tuple(shlex.split(pending))
            except ValueError:
                # A quoted argument continues on the next line, as in a shell.
                pending += "\n"
                continue
            pending = ""
            normalized = _studio_cli_arguments(arguments)
            if normalized is not None:
                commands.append(normalized)
    return tuple(commands)


def _validate_click_path(
    command: click.Command,
    arguments: list[str],
    parent: click.Context | None = None,
) -> None:
    name = "marimo-studio" if parent is None else command.name or "marimo-studio"
    if isinstance(command, click.Group):
        context = command.make_context(
            name,
            arguments,
            parent=parent,
            resilient_parsing=True,
        )
        _name, child, remaining = command.resolve_command(context, arguments)
        assert child is not None
        _validate_click_path(
            child,
            remaining,
            parent=context,
        )
    else:
        context = command.make_context(name, arguments, parent=parent)
        assert context.args == []


def _parse_documented_command(arguments: tuple[str, ...]) -> None:
    if arguments == ("--version",):
        result = CliRunner().invoke(cli, list(arguments))
        assert result.exit_code == 0, result.output
        return
    _validate_click_path(cli, list(arguments))


def _notebook_source(cell: str) -> str:
    return f'''import marimo

__generated_with = "{marimo.__version__}"
app = marimo.App()

@app.cell
def _():
    class Data:
        def group_by(self, _name):
            return self

        def len(self):
            return self

        def describe(self):
            return self

    data = Data()
    return (data,)

{cell}

if __name__ == "__main__":
    app.run()
'''


def test_documented_result_cells_survive_marimo_parsing(tmp_path) -> None:
    examples = (
        (
            "docs/guide/getting-started.md",
            "## Place a notebook result",
        ),
        (
            "docs/guide/notebook-results.md",
            "## Place a complete cell",
        ),
    )
    cells = tuple(
        _python_block(Path(path).read_text(encoding="utf-8"), heading)
        for path, heading in examples
    )
    notebook = tmp_path / "documented-cells.py"
    notebook.write_text(_notebook_source("\n\n".join(cells)), encoding="utf-8")

    result = asyncio.run(
        studio_authoring.open_workspace(notebook).inspect_notebook(
            include_code=True,
            output_expressions=True,
        )
    )

    assert len(result.cells) == len(cells)
    assert all(cell.name is not None and cell.code for cell in result.cells)


def test_documented_provider_builds_a_complete_html_artifact(tmp_path) -> None:
    source = _python_block(
        Path("docs/reference/provider-api.md").read_text(encoding="utf-8"),
        "## Minimal provider",
    )
    namespace: dict[str, object] = {}
    exec(compile(source, "provider-api.md", "exec"), namespace)
    provider = cast(ViewProvider, namespace["provider"])
    registry = ProviderRegistry(
        (candidate("report", provider, distribution="acme-views"),)
    )
    installed = registry.get("acme-views/report")
    root = tmp_path / "report"
    root.mkdir()
    starter = installed.starters()[0]
    plan = installed.create(
        starter,
        provider_starter_context(tmp_path, view_name="report"),
    )
    for relative, payload in plan.files.items():
        path = root.joinpath(*relative.parts)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
    (root / "view.toml").write_text(
        encode_view_manifest(installed.key),
        encoding="utf-8",
    )
    project = load_view_project(root)
    inspection = installed.inspect(inspection_request(project))
    staging = tmp_path / "staging"
    staging.mkdir()

    result = installed.build(
        provider_build_request(
            project,
            inspection,
            staging,
            cache_root=tmp_path / "cache-owner" / ".artifacts" / ".cache",
        )
    )

    assert result.document is not None
    validate_document(staging, result.document)


def test_every_standalone_python_block_compiles() -> None:
    compiled = 0
    for path in _documentation_paths():
        for block in _fenced_blocks(path.read_text(encoding="utf-8"), "python"):
            compile(
                block,
                str(path),
                "exec",
                flags=ast.PyCF_ALLOW_TOP_LEVEL_AWAIT,
            )
            compiled += 1
    assert compiled > 0


def test_documented_cli_workflows_parse_to_supported_commands() -> None:
    commands: set[tuple[str, ...]] = set()
    for path in _documentation_paths():
        document = path.read_text(encoding="utf-8")
        commands.update(_console_commands(document))

    for arguments in commands:
        _parse_documented_command(arguments)

    assert commands


def _cli_leaf_paths(
    group: click.Group,
    prefix: tuple[str, ...] = (),
) -> set[tuple[str, ...]]:
    paths: set[tuple[str, ...]] = set()
    for name, command in group.commands.items():
        path = (*prefix, name)
        if isinstance(command, click.Group):
            paths.update(_cli_leaf_paths(command, path))
        else:
            paths.add(path)
    return paths


def test_cli_reference_covers_every_public_command() -> None:
    source = Path("docs/reference/cli.md").read_text(encoding="utf-8")
    documented = {
        tuple(match.split())
        for match in re.findall(r"^## `marimo-studio ([^`]+)`$", source, re.MULTILINE)
    }

    assert documented == _cli_leaf_paths(cli)


def _api_symbols(source: str, module: str) -> set[str]:
    section = source.split(f"## `{module}`", 1)[1]
    section = section.split("\n## `", 1)[0]
    return set(re.findall(r"^### `([^`]+)`$", section, re.MULTILINE))


def test_python_reference_covers_the_public_api() -> None:
    source = Path("docs/reference/python-api.md").read_text(encoding="utf-8")
    modules = {
        "marimo_studio": marimo_studio,
        "marimo_studio.authoring": studio_authoring,
        "marimo_studio.agent": studio_agent,
    }

    for name, module in modules.items():
        assert _api_symbols(source, name) == set(module.__all__)


def test_provider_reference_names_every_public_symbol() -> None:
    source = Path("docs/reference/provider-api.md").read_text(encoding="utf-8")
    documented = {
        name for name in studio_view_providers.__all__ if f"`{name}`" in source
    }

    assert documented == set(studio_view_providers.__all__)
