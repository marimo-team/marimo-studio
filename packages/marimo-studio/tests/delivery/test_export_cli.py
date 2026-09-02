from __future__ import annotations

import asyncio
import json
from pathlib import Path

from click.testing import CliRunner

import marimo_studio.authoring as studio_authoring
from marimo_studio._cli import cli

from .export_test_support import configure_export_view


def test_export_command_reports_the_static_entrypoint(
    notebook_path: Path,
    tmp_path: Path,
) -> None:
    configure_export_view(notebook_path)
    output = tmp_path / "site"

    result = CliRunner().invoke(
        cli,
        [
            "view",
            "export",
            "dashboard",
            "--target",
            str(notebook_path),
            "--output",
            str(output),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["schema"] == 1
    assert payload["view"] == "dashboard"
    assert payload["runtime"] == "wasm"
    assert Path(payload["entrypoint"]) == output / "index.html"
    assert output.joinpath("index.html").is_file()


def test_export_completion_command_serves_on_loopback(
    notebook_path: Path,
    tmp_path: Path,
) -> None:
    configure_export_view(notebook_path)
    output = tmp_path / "site"

    result = CliRunner().invoke(
        cli,
        [
            "view",
            "export",
            "dashboard",
            "--target",
            str(notebook_path),
            "--output",
            str(output),
        ],
    )

    assert result.exit_code == 0, result.output
    serve = next(line for line in result.output.splitlines() if "http.server" in line)
    assert "--bind 127.0.0.1" in serve
    assert "--directory" in serve
    assert str(output) in serve


def test_agent_view_exports_the_same_static_bundle(
    notebook_path: Path,
    tmp_path: Path,
) -> None:
    configure_export_view(notebook_path)
    output = tmp_path / "agent-site"
    view = studio_authoring.open_workspace(notebook_path).view("dashboard")

    result = asyncio.run(view.export(output))

    assert result.view == "dashboard"
    assert result.entrypoint == output / "index.html"
    assert result.entrypoint.is_file()
