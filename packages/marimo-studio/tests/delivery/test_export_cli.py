from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

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
            "export",
            str(notebook_path),
            "--output",
            str(output),
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
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
        ["export", str(notebook_path), "--output", str(output)],
    )

    assert result.exit_code == 0, result.output
    serve = next(line for line in result.output.splitlines() if "http.server" in line)
    assert "--bind 127.0.0.1" in serve
    assert "--directory" in serve
    assert str(output) in serve
