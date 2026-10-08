from __future__ import annotations

import json
from pathlib import Path

import pytest
from click import unstyle
from click.testing import CliRunner

from marimo_studio._cli import cli
from marimo_studio._cli.commands import view_delivery
from marimo_studio._views.records import ViewBuild
from marimo_studio.view_providers import ProjectDiagnostic

from .commands_test_support import _run_cli


@pytest.mark.native_process
def test_new_command_errors_emit_the_complete_diagnostic_command(
    tmp_path: Path,
    runtime_assets: Path,
) -> None:
    result = _run_cli(
        runtime_assets,
        "view",
        "build",
        "dashboard",
        "--target",
        str(tmp_path / "missing.py"),
        "--json",
    )

    assert result.returncode == 3, result.stderr
    event = json.loads(result.stderr)
    assert event["event"] == "diagnostic"
    assert event["command"] == "view build"


def test_view_build_prints_build_warnings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    notebook = tmp_path / "analysis.py"
    notebook.write_text("import marimo\napp = marimo.App()\n", encoding="utf-8")

    async def build(*_args: object, **_kwargs: object) -> ViewBuild:
        return ViewBuild(
            view="dashboard",
            profile="development",
            revision="rev-1",
            issues=(
                ProjectDiagnostic(
                    "projection-site-missing",
                    "warning",
                    "The built page dropped the host at index.html:4:7.",
                ),
            ),
        )

    monkeypatch.setattr(view_delivery, "build_view", build)
    monkeypatch.setattr(
        view_delivery, "_bootstrap_provider_environment", lambda *_args: None
    )

    result = CliRunner().invoke(
        cli, ["view", "build", "dashboard", "--target", str(notebook)]
    )

    assert result.exit_code == 0, result.output
    assert unstyle(result.output).splitlines() == [
        "Built dashboard for development use (rev-1)",
        "  warning projection-site-missing: "
        "The built page dropped the host at index.html:4:7.",
    ]
