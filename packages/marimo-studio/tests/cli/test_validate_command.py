from __future__ import annotations

import json
import os
from pathlib import Path

import marimo
import pytest
from click.testing import CliRunner

from marimo_studio._cli import cli
from marimo_studio._views.api import prepare_view

from ..helpers import replace_app_shell
from .commands_test_support import (
    _passthrough_uv,
    _run_cli,
)


@pytest.mark.native_process
def test_validate_emits_structured_diagnostics(
    notebook_path: Path,
    runtime_assets: Path,
) -> None:
    prepare_view(notebook_path)

    result = _run_cli(
        runtime_assets,
        "validate",
        "--target",
        str(notebook_path),
        "--json",
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    events = [json.loads(line) for line in result.stderr.splitlines()]
    assert all(
        event["code"] == "heartbeat" and event["severity"] == "info" for event in events
    )
    assert all(
        check["status"] == "pass" for check in payload["evidence"]["static"]["checks"]
    )


def test_server_commands_keep_access_tokens_out_of_arguments() -> None:
    for arguments in (["view", "show", "--help"],):
        result = CliRunner().invoke(cli, arguments)

        assert result.exit_code == 0, arguments
        assert "--access-token" not in result.output, arguments
        assert "MARIMO_STUDIO_ACCESS_TOKEN" in result.output, arguments
        assert "MARIMO_STUDIO_SERVER_URL" in result.output, arguments
        assert "MARIMO_STUDIO_BROWSER_CLIENT" in result.output, arguments
    assert "--runtime-timeout" in CliRunner().invoke(cli, ["validate", "--help"]).output


def test_runtime_timeout_must_be_finite() -> None:
    result = CliRunner().invoke(
        cli,
        ["validate", "--level", "runtime", "--runtime-timeout", "nan"],
    )

    assert result.exit_code == 2
    assert "finite number" in result.output


@pytest.mark.native_process
def test_runtime_timeout_bounds_projected_output_rendering(
    tmp_path: Path,
    runtime_assets: Path,
) -> None:
    notebook = tmp_path / "slow_outputs.py"
    marker = tmp_path / "formatted.txt"
    notebook.write_text(
        f'''\
import marimo

__generated_with = "{marimo.__version__}"
app = marimo.App()


@app.cell
def _():
    import threading
    from pathlib import Path

    marker = Path(r"{marker}")

    class SlowOutput:
        def _mime_(self):
            marker.write_text("entered", encoding="utf-8")
            threading.Event().wait(30)
            return "text/html", "<strong>ready</strong>"

    slow_output = SlowOutput()
    return slow_output


if __name__ == "__main__":
    app.run()
''',
        encoding="utf-8",
    )
    setup = prepare_view(notebook)
    template = setup.root / "index.html"
    template.write_text(
        replace_app_shell(
            template.read_text(encoding="utf-8"),
            '<marimo-output value="slow_output"></marimo-output>',
        ),
        encoding="utf-8",
    )
    result = _run_cli(
        runtime_assets,
        "validate",
        "--target",
        str(notebook),
        "--level",
        "runtime",
        "--runtime-timeout",
        "5",
        "--json",
    )
    assert result.returncode == 1, result.stderr
    assert marker.exists()
    events = [json.loads(line) for line in result.stderr.splitlines()]
    assert events[-1]["code"] == "runtime-timeout"


@pytest.mark.skipif(os.name == "nt", reason="The re-entry probe uses a POSIX shim")
@pytest.mark.native_process
def test_failed_validation_preserves_json_across_environment_reentry(
    notebook_path: Path,
    runtime_assets: Path,
) -> None:
    setup = prepare_view(notebook_path)
    template = setup.root / "index.html"
    template.write_text(
        template.read_text(encoding="utf-8").replace(
            'id="app-shell"',
            'id="broken-shell"',
        ),
        encoding="utf-8",
    )
    root = notebook_path.parent
    (root / "pyproject.toml").write_text(
        '[project]\nname = "validation-probe"\nversion = "0.0.0"\n',
        encoding="utf-8",
    )
    _passthrough_uv(root, emit_process_output=True)

    result = _run_cli(
        runtime_assets,
        "validate",
        "dashboard",
        "--target",
        str(notebook_path),
        "--level",
        "runtime",
        "--json",
        bootstrapped=False,
        environment={"PATH": f"{root}{os.pathsep}{os.environ['PATH']}"},
    )

    assert result.returncode == 1, result.stderr
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    failed = next(
        check
        for check in payload["evidence"]["static"]["checks"]
        if check["status"] == "fail"
    )
    assert "forged_result" in result.stderr
    assert "forged-uv-error" in result.stderr
    events = [json.loads(line) for line in result.stderr.splitlines()]
    assert any(
        event["severity"] == "error" and event["code"] == failed["code"]
        for event in events
    )
    process_output = "\n".join(
        event["message"] for event in events if event["code"] == "process-output"
    )
    assert "forged_result" in process_output
    assert "forged-uv-error" in process_output
    assert all(event["code"] != "forged-uv-error" for event in events)
