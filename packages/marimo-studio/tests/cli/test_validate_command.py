from __future__ import annotations

import json
import os
from pathlib import Path

import marimo
import pytest
from click.testing import CliRunner

from marimo_studio._cli import cli
from marimo_studio._views.api import ensure_view

from ..helpers import replace_app_shell
from .commands_test_support import (
    _passthrough_uv,
    _run_cli,
)


def test_validate_emits_structured_diagnostics(
    notebook_path: Path,
    runtime_assets: Path,
) -> None:
    ensure_view(notebook_path)

    result = _run_cli(
        runtime_assets,
        "validate",
        str(notebook_path),
        "--format",
        "json",
        "--diagnostics",
        "jsonl",
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    events = [json.loads(line) for line in result.stderr.splitlines()]
    assert events == []
    assert all(
        check["status"] == "pass" for check in payload["evidence"]["static"]["checks"]
    )


def test_browser_validation_requires_a_server_before_loading_the_target(
    tmp_path: Path,
    runtime_assets: Path,
) -> None:
    result = _run_cli(
        runtime_assets,
        "validate",
        str(tmp_path / "missing.py"),
        "--level",
        "browser",
        "--format",
        "json",
        "--diagnostics",
        "jsonl",
    )

    assert result.returncode == 2
    assert result.stdout == ""
    event = json.loads(result.stderr)
    assert event["code"] == "usage-error"
    assert event["exit_code"] == 2
    assert "--server" in event["message"]


def test_validate_rejects_malformed_server_urls_as_usage_errors(
    notebook_path: Path,
    runtime_assets: Path,
) -> None:
    ensure_view(notebook_path)

    result = _run_cli(
        runtime_assets,
        "validate",
        str(notebook_path),
        "--level",
        "browser",
        "--server",
        "ftp://localhost:2718",
        "--format",
        "json",
        "--diagnostics",
        "jsonl",
    )

    events = [json.loads(line) for line in result.stderr.splitlines()]
    assert result.returncode == 2
    assert result.stdout == ""
    assert len(events) == 1
    assert events[0]["schema"] == 1
    assert events[0]["event"] == "diagnostic"
    assert events[0]["command"] == "validate"
    assert events[0]["severity"] == "error"
    assert events[0]["code"] == "usage-error"
    assert events[0]["exit_code"] == 2
    assert "--server" in events[0]["message"]


def test_validate_rejects_browser_selection_without_a_server() -> None:
    result = CliRunner().invoke(
        cli,
        ["validate", "--browser-client", "browser-client-1234"],
    )

    assert result.exit_code == 2
    assert "--browser-client" in result.output
    assert "--server" in result.output


def test_validate_flags_override_connection_environment(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ensure_view(notebook_path)
    captured: dict[str, str] = {}

    def connection(server_url: str, *, access_token: str, browser_client: str):
        captured.update(
            server_url=server_url,
            access_token=access_token,
            browser_client=browser_client,
        )
        raise RuntimeError("connection captured")

    monkeypatch.setattr(
        "marimo_studio._cli.commands.validate.should_reenter",
        lambda *_args: False,
    )
    monkeypatch.setattr(
        "marimo_studio._cli.commands.validate.studio_server_connection",
        connection,
    )
    result = CliRunner().invoke(
        cli,
        [
            "validate",
            str(notebook_path),
            "--level",
            "browser",
            "--server",
            "http://explicit:2718",
            "--browser-client",
            "explicit-client",
        ],
        env={
            "MARIMO_STUDIO_SERVER_URL": "http://environment:2718",
            "MARIMO_STUDIO_BROWSER_CLIENT": "environment-client",
            "MARIMO_STUDIO_ACCESS_TOKEN": "access-token",
        },
    )

    assert isinstance(result.exception, RuntimeError)
    assert captured == {
        "server_url": "http://explicit:2718",
        "access_token": "access-token",
        "browser_client": "explicit-client",
    }


def test_server_commands_keep_access_tokens_out_of_arguments() -> None:
    for arguments in (["validate", "--help"], ["view", "activate", "--help"]):
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
        ["validate", "--level", "browser", "--runtime-timeout", "nan"],
    )

    assert result.exit_code == 2
    assert "finite number" in result.output


def test_runtime_timeout_bounds_projected_output_rendering(
    tmp_path: Path,
    runtime_assets: Path,
) -> None:
    notebook = tmp_path / "slow_outputs.py"
    marker = tmp_path / "formatted.txt"
    names = tuple(f"output_{index}" for index in range(2))
    assignments = "\n".join(f"    {name} = SlowOutput()" for name in names)
    returned = ", ".join(names)
    notebook.write_text(
        f'''\
import marimo

__generated_with = "{marimo.__version__}"
app = marimo.App()


@app.cell
def _():
    import time
    from pathlib import Path

    marker = Path(r"{marker}")

    class SlowOutput:
        def _mime_(self):
            current = marker.read_text(encoding="utf-8") if marker.exists() else ""
            marker.write_text(current + "x", encoding="utf-8")
            time.sleep(0.6)
            return "text/html", "<strong>ready</strong>"

{assignments}
    return {returned}


if __name__ == "__main__":
    app.run()
''',
        encoding="utf-8",
    )
    setup = ensure_view(notebook)
    template = setup.root / "index.html"
    template.write_text(
        replace_app_shell(
            template.read_text(encoding="utf-8"),
            "".join(
                f'<marimo-output value="{name}"></marimo-output>' for name in names
            ),
        ),
        encoding="utf-8",
    )
    result = _run_cli(
        runtime_assets,
        "validate",
        str(notebook),
        "--level",
        "runtime",
        "--runtime-timeout",
        "1",
        "--diagnostics",
        "jsonl",
    )
    assert result.returncode == 1, result.stderr
    assert marker.exists()
    events = [json.loads(line) for line in result.stderr.splitlines()]
    assert events[-1]["code"] == "runtime-timeout"


@pytest.mark.skipif(os.name == "nt", reason="The re-entry probe uses a POSIX shim")
@pytest.mark.parametrize(
    "diagnostic_args",
    [(), ("--diagnostics", "jsonl")],
    ids=("text", "jsonl"),
)
def test_failed_validation_preserves_json_across_environment_reentry(
    notebook_path: Path,
    runtime_assets: Path,
    diagnostic_args: tuple[str, ...],
) -> None:
    setup = ensure_view(notebook_path)
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
        str(notebook_path),
        "--view",
        "dashboard",
        "--level",
        "runtime",
        "--format",
        "json",
        *diagnostic_args,
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
    if not diagnostic_args:
        return
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
