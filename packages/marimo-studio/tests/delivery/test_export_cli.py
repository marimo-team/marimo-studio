from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from click.testing import CliRunner

import marimo_studio.authoring as studio_authoring
from marimo_studio._cli import cli

from .export_test_support import configure_export_view

_PREPARE_TIMEOUT = 120.0


@pytest.mark.native_process
@pytest.mark.xdist_group("managed-export")
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
            "--prepare-timeout",
            str(_PREPARE_TIMEOUT),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["schema"] == 1
    assert payload["view"] == "dashboard"
    assert payload["runtime"] == "zero-python"
    assert payload["cache_activity"] is not None
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
            "--runtime",
            "wasm",
        ],
    )

    assert result.exit_code == 0, result.output
    serve = next(line for line in result.output.splitlines() if "http.server" in line)
    assert "--bind 127.0.0.1" in serve
    assert "--directory" in serve
    assert str(output) in serve


def test_export_help_explains_runtime_and_preparation_timeout() -> None:
    result = CliRunner().invoke(cli, ["view", "export", "--help"])

    assert result.exit_code == 0, result.output
    help_text = " ".join(result.output.split())
    assert "--runtime [zero-python|wasm]" in help_text
    assert "zero-python prepares configured notebook states during export" in help_text
    assert "wasm runs notebook Python in each visitor's browser" in help_text
    assert "--prepare-timeout SECONDS" in help_text
    assert "Defaults to 30 seconds when omitted" in help_text


def test_wasm_export_rejects_prepare_timeout_before_resolving_target(
    tmp_path: Path,
) -> None:
    output = tmp_path / "site"

    result = CliRunner().invoke(
        cli,
        [
            "view",
            "export",
            "dashboard",
            "--target",
            str(tmp_path / "missing.py"),
            "--output",
            str(output),
            "--runtime",
            "wasm",
            "--prepare-timeout",
            "10",
        ],
    )

    assert result.exit_code == 2
    assert (
        "--prepare-timeout is only valid with --runtime zero-python." in result.output
    )
    assert not output.exists()


@pytest.mark.native_process
@pytest.mark.xdist_group("managed-export")
def test_agent_view_exports_the_same_static_bundle(
    notebook_path: Path,
    tmp_path: Path,
) -> None:
    configure_export_view(notebook_path)
    output = tmp_path / "agent-site"
    view = studio_authoring.open_workspace(notebook_path).view("dashboard")

    result = asyncio.run(view.export(output, prepare_timeout=_PREPARE_TIMEOUT))

    assert result.view == "dashboard"
    assert result.entrypoint == output / "index.html"
    assert result.entrypoint.is_file()
