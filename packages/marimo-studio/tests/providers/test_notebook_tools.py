"""Run provider commands from a notebook's pixi script environment."""

from __future__ import annotations

import json
import logging
import os
import shutil
import sys
import threading
import time
from collections.abc import Callable, Iterable
from pathlib import Path, PurePosixPath

import pytest
from click.testing import CliRunner

import marimo_studio._composition as composition
from marimo_studio._cli import cli
from marimo_studio._notebook.ports import ScriptEnvironmentInstall
from marimo_studio._processes.cancellation import provider_cancellation
from marimo_studio._processes.operation import (
    ProviderCancellation,
    ProviderCommandError,
)
from marimo_studio._processes.provider_runner import create_provider_runner
from marimo_studio._processes.tools import ProviderTools, provider_tools
from marimo_studio._views.catalog import starters
from marimo_studio._views.inspection import project_provenance
from marimo_studio._views.records import Starter
from marimo_studio._workspace.locations import CatalogLocations
from marimo_studio._workspace.project_manifest import (
    encode_view_manifest,
    load_view_project,
)
from marimo_studio._workspace.tools import command_installs, notebook_tools
from marimo_studio.errors import ConfigurationError, DependencyError
from marimo_studio.view_providers import RenderRequest, find_tool, probe_tool
from marimo_studio.view_providers._host import provider_registry

posix_only = pytest.mark.skipif(os.name == "nt", reason="uses POSIX shell scripts")

PIXI_METADATA = """\
# /// script
# requires-python = ">=3.10,<3.15"
# dependencies = []
#
# [tool.pixi.dependencies]
# tectonic = ">=0.15"
# ///
"""
NOTEBOOK = """\
import marimo

app = marimo.App()


@app.cell
def _():
    x = 1
    return (x,)
"""


def _notebook(directory: Path, metadata: str = PIXI_METADATA) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    notebook = directory / "analysis.py"
    notebook.write_text(metadata + NOTEBOOK, encoding="utf-8")
    return notebook


def _tectonic(directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    tool = directory / "tectonic"
    tool.write_text('#!/bin/sh\necho "Tectonic 0.17.0"\n', encoding="utf-8")
    tool.chmod(0o755)
    return tool


class _Environments:
    """Stand in for pixi with a Python command that reports one environment."""

    def __init__(
        self,
        directories: tuple[str, ...],
        *,
        selected: bool = True,
        script: str = "import sys; sys.stderr.write('installed')",
        missing: bool = False,
    ) -> None:
        self.directories = directories
        self.is_selected = selected
        self.script = script
        self.missing = missing
        self.installed: list[Path] = []

    def selected(self) -> bool:
        return self.is_selected

    def install(self, notebook: Path) -> ScriptEnvironmentInstall:
        self.installed.append(notebook)
        if self.missing:
            raise DependencyError("pixi must be installed to use --sandbox=pixi.")
        return ScriptEnvironmentInstall(
            (sys.executable, "-c", self.script),
            dict(os.environ),
            lambda _report: self.directories,
        )


def _install(
    monkeypatch: pytest.MonkeyPatch, environments: _Environments
) -> _Environments:
    monkeypatch.setattr(composition, "create_script_environments", lambda: environments)
    return environments


def _latex(records: Iterable[Starter]) -> list[tuple[bool, str | None]]:
    return [
        (starter.availability.available, starter.availability.version)
        for starter in records
        if starter.provider == "marimo-studio/latex"
    ]


def _edit(notebook: Path, metadata: Callable[[str], str]) -> None:
    notebook.write_text(metadata(PIXI_METADATA) + NOTEBOOK, encoding="utf-8")


@posix_only
def test_latex_starter_is_available_from_the_notebook_pixi_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    environment = tmp_path / "environment" / "bin"
    _tectonic(environment)
    _install(monkeypatch, _Environments((str(environment),)))
    notebook = _notebook(tmp_path / "project")

    assert _latex(starters(notebook)) == [(True, "0.17.0")]
    assert _latex(starters()) == [(False, None)]


@posix_only
def test_starters_command_reports_availability_for_a_target_notebook(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    environment = tmp_path / "environment" / "bin"
    _tectonic(environment)
    # A Studio command installs the environment of the notebook it targets.
    _install(monkeypatch, _Environments((str(environment),), selected=False))
    notebook = _notebook(tmp_path / "project")

    result = CliRunner().invoke(cli, ["starters", "--target", str(notebook), "--json"])

    assert result.exit_code == 0, result.output
    latex = [
        starter["availability"]
        for starter in json.loads(result.stdout)["starters"]
        if starter["provider"] == "marimo-studio/latex"
    ]
    assert [(item["available"], item["version"]) for item in latex] == [
        (True, "0.17.0")
    ]


@posix_only
def test_provider_commands_run_with_the_notebook_tools_first_on_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    environment = tmp_path / "environment" / "bin"
    tool = _tectonic(environment)
    _install(monkeypatch, _Environments((str(environment),)))
    notebook = _notebook(tmp_path / "project")
    root = tmp_path / "view"
    root.mkdir()

    with notebook_tools(notebook):
        located = find_tool("tectonic")
        completed = create_provider_runner(root, ProviderCancellation(), 10).run(
            ["tectonic", "--version"], cwd=root
        )

    assert located == str(tool)
    assert completed.stdout == "Tectonic 0.17.0\n"


@posix_only
def test_view_revision_names_the_tool_version_of_its_notebook(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    environment = tmp_path / "environment" / "bin"
    _tectonic(environment)
    _install(monkeypatch, _Environments((str(environment),)))
    notebook = _notebook(tmp_path / "project")
    root = tmp_path / "project" / "studio" / "analysis" / "paper"
    root.mkdir(parents=True)
    (root / "view.toml").write_text(
        encode_view_manifest("marimo-studio/latex"), encoding="utf-8"
    )
    project = load_view_project(
        root, locations=CatalogLocations.inside_views(notebook, root.parent)
    )
    with notebook_tools(notebook):
        built = provider_registry().get("marimo-studio/latex").provenance()

    # A starter listing without a notebook checks the PATH, where Tectonic is
    # missing, between the build and a later revision of the same project.
    starters()

    assert project_provenance(project) == built


@posix_only
def test_a_notebook_opened_without_the_pixi_sandbox_keeps_commands_on_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    on_path = _tectonic(tmp_path / "path")
    monkeypatch.setenv("PATH", str(on_path.parent))
    environments = _install(
        monkeypatch, _Environments((str(tmp_path / "environment"),), selected=False)
    )
    notebook = _notebook(tmp_path / "project")

    with notebook_tools(notebook):
        located = find_tool("tectonic")

    assert environments.installed == []
    assert located == str(on_path)


@posix_only
@pytest.mark.parametrize(
    "files",
    (
        {"analysis.py": '# /// script\n# dependencies = ["polars"]\n# ///\n'},
        {
            "analysis.py": PIXI_METADATA,
            "pyproject.toml": '[project]\nname = "analysis"\nversion = "0.1.0"\n',
        },
    ),
    ids=("without-pixi-metadata", "inside-a-project"),
)
def test_notebooks_without_a_pixi_script_environment_keep_commands_on_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    files: dict[str, str],
) -> None:
    on_path = _tectonic(tmp_path / "path")
    monkeypatch.setenv("PATH", str(on_path.parent))
    environments = _install(
        monkeypatch, _Environments((str(tmp_path / "environment"),))
    )
    project = tmp_path / "project"
    project.mkdir()
    for name, content in files.items():
        suffix = NOTEBOOK if name == "analysis.py" else ""
        (project / name).write_text(content + suffix, encoding="utf-8")

    with notebook_tools(project / "analysis.py"):
        located = find_tool("tectonic")

    assert environments.installed == []
    assert located == str(on_path)


@posix_only
def test_failed_pixi_install_names_its_cause_in_availability(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    _install(
        monkeypatch,
        _Environments(
            (),
            script="import sys; sys.stderr.write('solve failed'); sys.exit(1)",
        ),
    )
    notebook = _notebook(tmp_path / "project")

    with (
        caplog.at_level(logging.WARNING, logger="marimo.studio"),
        notebook_tools(notebook),
    ):
        availability = provider_registry().get("marimo-studio/latex").availability()

    assert not availability.available
    assert availability.reason is not None
    assert availability.reason.endswith(
        "The notebook's pixi environment is unavailable: solve failed"
    )
    assert availability.action == "Fix the pixi error, then build the view again."
    assert "solve failed" in caplog.text


@posix_only
def test_a_failed_render_names_the_notebook_pixi_problem(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    template = tmp_path / "template"
    template.mkdir()
    (template / "main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}x\\end{document}\n",
        encoding="utf-8",
    )
    output = tmp_path / "output"
    output.mkdir()
    cancellation = ProviderCancellation()

    with provider_tools(ProviderTools(problem="solve failed")):
        result = (
            provider_registry()
            .get("marimo-studio/latex")
            .render(
                RenderRequest(
                    source=PurePosixPath("main.tex"),
                    template_root=template,
                    values={},
                    outputs={},
                    cells={},
                    output_root=output,
                    cancellation=cancellation,
                    runner=create_provider_runner(template, cancellation, 10),
                    command_timeout=10,
                )
            )
        )

    assert [(item.code, item.message) for item in result.diagnostics] == [
        ("provider-error", "Studio cannot find the tectonic command."),
        (
            "pixi-environment-unavailable",
            "The notebook's pixi environment is unavailable: solve failed",
        ),
    ]


def test_starters_command_rejects_a_missing_target_notebook(tmp_path: Path) -> None:
    result = CliRunner().invoke(
        cli, ["starters", "--target", str(tmp_path / "missing.py"), "--json"]
    )

    assert isinstance(result.exception, ConfigurationError)
    assert str(result.exception).startswith("Notebook does not exist")


def test_missing_pixi_is_retried_after_the_metadata_changes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    environments = _install(monkeypatch, _Environments((), missing=True))
    notebook = _notebook(tmp_path / "project")

    for _ in range(2):
        with notebook_tools(notebook):
            pass
    _edit(notebook, lambda text: text.replace('">=0.15"', '">=0.16"'))
    with notebook_tools(notebook):
        pass

    assert environments.installed == [notebook, notebook]


def test_studio_configuration_edits_reuse_the_installed_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    environment = tmp_path / "environment" / "bin"
    environment.mkdir(parents=True)
    environments = _install(monkeypatch, _Environments((str(environment),)))
    notebook = _notebook(tmp_path / "project")

    with notebook_tools(notebook):
        pass
    _edit(
        notebook,
        lambda text: text.replace(
            "# ///\n", '#\n# [tool.marimo-studio]\n# default = "paper"\n# ///\n'
        ),
    )
    with notebook_tools(notebook):
        pass
    _edit(notebook, lambda text: text.replace('">=0.15"', '">=0.16"'))
    with notebook_tools(notebook):
        pass

    assert environments.installed == [notebook, notebook]


def test_cancelling_a_provider_call_stops_its_pixi_install(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install(monkeypatch, _Environments((), script="import time; time.sleep(30)"))
    notebook = _notebook(tmp_path / "project")
    cancellation = ProviderCancellation()
    threading.Timer(0.2, cancellation.cancel).start()
    started = time.monotonic()

    with (
        provider_cancellation(cancellation),
        pytest.raises(ProviderCommandError, match="cancelled"),
        notebook_tools(notebook),
    ):
        pass

    assert time.monotonic() - started < 10


@pytest.mark.pixi
def test_pixi_installs_the_tectonic_a_notebook_declares(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pixi = shutil.which("pixi")
    assert pixi is not None
    # Leave only pixi on PATH, so Tectonic can come from the notebook alone.
    monkeypatch.setenv("PATH", str(Path(pixi).parent))
    monkeypatch.delenv("CONDA_PREFIX", raising=False)
    notebook = _notebook(tmp_path)

    with command_installs(), notebook_tools(notebook):
        located = find_tool("tectonic")
        availability = probe_tool(
            ("tectonic", "--version"), minimum="0.15", install="unused"
        )

    assert located is not None
    assert Path(located).parent != Path(pixi).parent
    assert availability.available, availability.reason
