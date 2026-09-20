from __future__ import annotations

import json
import os
import shlex
import subprocess
from importlib.metadata import version
from pathlib import Path

import pytest
from click import unstyle
from click.testing import CliRunner

from marimo_studio._cli import cli
from marimo_studio._cli.environment import SANDBOX_ENV
from marimo_studio._views.api import prepare_view
from marimo_studio._workspace import load_studio
from marimo_studio.errors import ViewExistsError
from marimo_studio.view_providers._host.package_policy import (
    BUNDLED_PROVIDER_REQUIREMENTS,
)
from marimo_studio.view_providers._host.registry import ProviderRegistry

from ..provider_test_support import ProviderStub, candidate, install_registry


def _editor_command(notebook: Path) -> str:
    arguments = [
        "uvx",
        "--with",
        f"marimo-studio=={version('marimo-studio')}",
        "marimo",
        "edit",
        str(notebook),
        "--sandbox",
    ]
    return (
        subprocess.list2cmdline(arguments) if os.name == "nt" else shlex.join(arguments)
    )


def test_view_create_bootstraps_lists_and_checks_named_views(
    notebook_path: Path,
) -> None:
    runner = CliRunner()

    created = runner.invoke(
        cli,
        [
            "view",
            "create",
            "dashboard",
            "--target",
            str(notebook_path),
            "--json",
        ],
    )
    added = runner.invoke(
        cli,
        [
            "view",
            "create",
            "executive",
            "--target",
            str(notebook_path),
            "--json",
        ],
    )
    overview = runner.invoke(
        cli,
        [
            "status",
            "--target",
            str(notebook_path),
            "--json",
        ],
    )
    checked = runner.invoke(
        cli,
        [
            "validate",
            "executive",
            "--target",
            str(notebook_path),
            "--json",
        ],
    )

    assert created.exit_code == 0, created.output
    assert added.exit_code == 0, added.output
    assert overview.exit_code == 0, overview.output
    assert checked.exit_code == 0, checked.output
    assert json.loads(created.stdout)["view"] == "dashboard"
    assert Path(json.loads(created.stdout)["root"]) == (
        notebook_path.parent / "__marimo__" / "studio" / "analysis" / "dashboard"
    )
    assert json.loads(added.stdout)["view"] == "executive"
    overview_payload = json.loads(overview.stdout)
    assert overview_payload["schema"] == 1
    assert [item["name"] for item in overview_payload["views"]] == [
        "dashboard",
        "executive",
    ]
    payload = json.loads(checked.stdout)
    assert payload["ok"] is True
    assert payload["view"] == "executive"
    assert any(
        check["name"] == "view:executive"
        for check in payload["evidence"]["static"]["checks"]
    )


def test_view_create_dry_run_matches_the_live_document_catalog_without_writing(
    notebook_path: Path,
) -> None:
    original = notebook_path.read_bytes()
    runner = CliRunner()

    preview = runner.invoke(
        cli,
        [
            "view",
            "create",
            "dashboard",
            "--target",
            str(notebook_path),
            "--dry-run",
            "--json",
        ],
    )

    assert preview.exit_code == 0, preview.output
    preview_payload = json.loads(preview.stdout)
    assert preview_payload["dry_run"] is True
    assert preview_payload["view"] == "dashboard"
    assert preview_payload["schema"] == 1
    assert preview_payload["created"]
    assert notebook_path.read_bytes() == original
    assert not (notebook_path.parent / "__marimo__").exists()

    created = runner.invoke(
        cli,
        [
            "view",
            "create",
            "dashboard",
            "--target",
            str(notebook_path),
            "--json",
        ],
    )

    assert created.exit_code == 0, created.output
    created_payload = json.loads(created.stdout)
    assert preview_payload["documents"] == created_payload["documents"]
    assert [Path(path).name for path in created_payload["documents"]] == [
        "view.toml",
        "index.html",
        "AGENTS.md",
    ]


def test_view_create_rejects_an_existing_name_during_dry_run(
    notebook_path: Path,
) -> None:
    prepare_view(notebook_path)

    result = CliRunner().invoke(
        cli,
        [
            "view",
            "create",
            "dashboard",
            "--target",
            str(notebook_path),
            "--dry-run",
        ],
    )

    assert result.exit_code != 0
    assert isinstance(result.exception, ViewExistsError)


def test_human_output_uses_color_and_json_remains_machine_readable(
    notebook_path: Path,
) -> None:
    runner = CliRunner()
    human = runner.invoke(
        cli,
        [
            "view",
            "create",
            "dashboard",
            "--target",
            str(notebook_path),
            "--dry-run",
        ],
        color=True,
    )
    machine = runner.invoke(
        cli,
        [
            "view",
            "create",
            "dashboard",
            "--target",
            str(notebook_path),
            "--dry-run",
            "--json",
        ],
        color=True,
    )

    assert human.exit_code == 0, human.output
    assert "\x1b[" in human.output
    human_output = unstyle(human.output)
    assert "Would create view dashboard" in human_output
    assert human_output.count(f"update {notebook_path}") == 1
    assert json.loads(machine.stdout)["view"] == "dashboard"


def test_view_create_reports_the_editor_command_in_human_and_json_output(
    notebook_path: Path,
) -> None:
    runner = CliRunner()
    human = runner.invoke(
        cli,
        ["view", "create", "dashboard", "--target", str(notebook_path)],
    )
    machine = runner.invoke(
        cli,
        [
            "view",
            "create",
            "executive",
            "--target",
            str(notebook_path),
            "--json",
        ],
    )

    assert human.exit_code == 0, human.output
    assert _editor_command(notebook_path) in unstyle(human.stderr)
    assert machine.exit_code == 0, machine.output
    event = json.loads(machine.stderr)
    assert event["code"] == "next-command"
    assert event["message"] == _editor_command(notebook_path)
    assert event["details"] == {"action": "edit"}


def test_view_create_reports_exact_requirements_for_every_provider_distribution(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(SANDBOX_ENV, "1")
    react = ProviderStub("unused/react", "default")
    svelte = ProviderStub("unused/svelte", "default")
    external = ProviderStub("unused/report", "default")
    install_registry(
        monkeypatch,
        ProviderRegistry(
            (
                candidate("react", react, distribution="marimo-studio"),
                candidate("svelte", svelte, distribution="marimo-studio"),
                candidate("report", external, distribution="example-suite"),
            ),
            BUNDLED_PROVIDER_REQUIREMENTS,
        ),
    )
    runner = CliRunner()

    for name, starter in (
        ("dashboard", "marimo-studio/react:default"),
        ("detail", "marimo-studio/svelte:default"),
        ("report", "example-suite/report:default"),
    ):
        result = runner.invoke(
            cli,
            [
                "view",
                "create",
                name,
                "--target",
                str(notebook_path),
                "--starter",
                starter,
                "--json",
            ],
        )
        assert result.exit_code == 0, result.output

    payload = json.loads(result.stdout)
    requirements = [
        f"marimo-studio[deno]=={version('marimo-studio')}",
        "example-suite==1.0.0",
    ]
    assert payload["launch_requirements"] == requirements
    arguments = ["uvx"]
    for requirement in requirements:
        arguments.extend(["--with", requirement])
    arguments.extend(["marimo", "edit", str(notebook_path), "--sandbox"])
    expected = (
        subprocess.list2cmdline(arguments) if os.name == "nt" else shlex.join(arguments)
    )
    event = json.loads(result.stderr)
    assert event["code"] == "next-command"
    assert event["message"] == expected


def test_view_create_resolves_an_uninitialized_project_from_the_current_directory(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pyproject = notebook_path.parent / "pyproject.toml"
    pyproject.write_text(
        f"""\
[tool.marimo-studio]
notebook = "{notebook_path.name}"
default = "dashboard"
""",
        encoding="utf-8",
    )
    monkeypatch.chdir(notebook_path.parent)

    result = CliRunner().invoke(
        cli,
        [
            "view",
            "create",
            "dashboard",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["config"] == str(pyproject)
    assert load_studio(pyproject).default_view == "dashboard"


@pytest.mark.parametrize("inline", [False, True])
def test_create_preserves_project_execution(notebook_path: Path, inline: bool) -> None:
    from marimo_studio._workspace.metadata import read_notebook_metadata

    project = notebook_path.parent / "pyproject.toml"
    original = (
        '[project]\nname = "analysis"\nversion = "0.1"\n'
        'dependencies = ["polars", "duckdb"]\n'
    )
    project.write_text(original)
    if inline:
        notebook_path.write_text(
            '# /// script\n# dependencies = ["polars"]\n# ///\n'
            + notebook_path.read_text()
        )
    result = CliRunner().invoke(
        cli,
        ["view", "create", "dashboard", "--target", str(notebook_path)],
        env={SANDBOX_ENV: "1"},
    )
    assert result.exit_code == 0, result.output
    assert "uv run --project" in result.stderr
    assert "--no-sandbox" in result.stderr
    assert project.read_text() == original
    metadata = read_notebook_metadata(notebook_path)
    assert metadata is not None
    if inline:
        assert "polars" in metadata["dependencies"]
    else:
        assert "dependencies" not in metadata
    assert metadata["tool"]["marimo-studio"]["default"] == "dashboard"
