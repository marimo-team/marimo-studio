from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest
from click import unstyle
from click.testing import CliRunner

import marimo_studio._workspace.launch as launch_module
from marimo_studio._cli import cli, main
from marimo_studio._cli.diagnostics import DiagnosticStream
from marimo_studio._workspace import ensure_view, load_studio


def _run_cli(
    runtime_assets: Path,
    *args: str,
) -> subprocess.CompletedProcess[str]:
    script = """\
from pathlib import Path
import sys

import marimo_studio._assets as assets

runtime_assets = Path(sys.argv[1])
assets.runtime_assets_path = lambda: runtime_assets
from marimo_studio._cli import main

sys.argv = ["marimo-studio", *sys.argv[2:]]
main()
"""
    return subprocess.run(
        [sys.executable, "-c", script, str(runtime_assets), *args],
        check=False,
        capture_output=True,
        text=True,
    )


def test_view_add_bootstraps_lists_and_checks_named_views(
    notebook_path: Path,
) -> None:
    runner = CliRunner()

    created = runner.invoke(
        cli,
        ["view", "add", "dashboard", str(notebook_path), "--format", "json"],
    )
    added = runner.invoke(
        cli,
        ["view", "add", "executive", str(notebook_path), "--format", "json"],
    )
    listed = runner.invoke(
        cli,
        ["view", "list", str(notebook_path), "--format", "json"],
    )
    checked = runner.invoke(
        cli,
        ["check", str(notebook_path), "--view", "executive", "--format", "json"],
    )

    assert created.exit_code == 0, created.output
    assert added.exit_code == 0, added.output
    assert listed.exit_code == 0, listed.output
    assert checked.exit_code == 0, checked.output
    assert json.loads(created.output)["view"] == "dashboard"
    assert "/__marimo__/studio/analysis/dashboard" in json.loads(created.output)["root"]
    assert json.loads(added.output)["view"] == "executive"
    assert [item["name"] for item in json.loads(listed.output)["views"]] == [
        "dashboard",
        "executive",
    ]
    payload = json.loads(checked.output)
    assert payload["ok"] is True
    assert payload["view"] == "executive"
    assert any(check["name"] == "view:executive" for check in payload["checks"])


def test_view_add_dry_run_reports_changes_without_writing(
    notebook_path: Path,
) -> None:
    original = notebook_path.read_bytes()

    result = CliRunner().invoke(
        cli,
        [
            "view",
            "add",
            "dashboard",
            str(notebook_path),
            "--dry-run",
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["dry_run"] is True
    assert payload["view"] == "dashboard"
    assert payload["created"]
    assert notebook_path.read_bytes() == original
    assert not (notebook_path.parent / "__marimo__").exists()


def test_help_presents_direct_launch_as_the_root_command() -> None:
    root = CliRunner().invoke(cli, ["--help"], prog_name="marimo-studio")
    direct = CliRunner().invoke(
        cli,
        ["analysis.py", "--help"],
        prog_name="marimo-studio",
    )

    assert root.exit_code == 0
    assert root.output.startswith(
        "Usage:\n"
        "  marimo-studio [NOTEBOOK] [OPTIONS]\n"
        "  marimo-studio COMMAND [ARGS]...\n"
    )
    assert direct.exit_code == 0
    assert direct.output.startswith(
        "Usage: marimo-studio [NOTEBOOK] [OPTIONS] [-- MARIMO_ARGS]\n"
    )


def test_human_output_uses_color_and_json_remains_machine_readable(
    notebook_path: Path,
) -> None:
    runner = CliRunner()
    human = runner.invoke(
        cli,
        [
            "view",
            "add",
            "dashboard",
            str(notebook_path),
            "--dry-run",
        ],
        color=True,
    )
    machine = runner.invoke(
        cli,
        [
            "view",
            "add",
            "dashboard",
            str(notebook_path),
            "--dry-run",
            "--format",
            "json",
        ],
        color=True,
    )

    assert human.exit_code == 0, human.output
    assert "\x1b[" in human.output
    assert "Would add view dashboard" in unstyle(human.output)
    assert "\x1b[" not in machine.output
    assert json.loads(machine.output)["view"] == "dashboard"


def test_launch_validates_options_before_bootstrap(notebook_path: Path) -> None:
    original = notebook_path.read_bytes()
    runner = CliRunner()

    base_url = runner.invoke(
        cli,
        [str(notebook_path), "--base-url", "invalid"],
    )
    compact_port = runner.invoke(
        cli,
        [str(notebook_path), "--", "-p9000"],
    )

    assert base_url.exit_code == 2
    assert compact_port.exit_code == 2
    assert notebook_path.read_bytes() == original
    assert not (notebook_path.parent / "__marimo__").exists()


def test_cli_bind_updates_the_shared_cell_registry(
    notebook_path: Path,
) -> None:
    ensure_view(notebook_path)
    runner = CliRunner()

    bound = runner.invoke(
        cli,
        [
            "bind",
            "summary",
            str(notebook_path),
            "--cell",
            "1",
            "--format",
            "json",
        ],
    )

    assert bound.exit_code == 0, bound.output
    payload = json.loads(bound.output)
    assert payload["alias"] == "summary"
    assert set(payload["cell"]) == {
        "index",
        "name",
        "ref",
        "runtime_id",
        "source",
    }
    assert str(load_studio(notebook_path).cells["summary"]) == payload["cell"]["ref"]


def test_cli_inspect_runtime_reports_mime_and_json_values(
    notebook_path: Path,
    runtime_assets: Path,
) -> None:
    result = _run_cli(
        runtime_assets,
        "inspect",
        str(notebook_path),
        "--runtime",
        "--format",
        "json",
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["cells"][1]["runtime"]["status"] == "idle"
    assert payload["cells"][1]["runtime"]["outputs"][-1]["mimetype"] == "text/html"
    assert payload["runtime"]["values"] == {"doubled": 4, "x": 2}


def test_check_emits_structured_diagnostics(
    notebook_path: Path,
    runtime_assets: Path,
) -> None:
    ensure_view(notebook_path)

    result = _run_cli(
        runtime_assets,
        "check",
        str(notebook_path),
        "--format",
        "json",
        "--diagnostics",
        "jsonl",
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    events = [json.loads(line) for line in result.stderr.splitlines()]
    assert [event["code"] for event in events] == [
        check["name"] for check in payload["checks"]
    ]
    assert all(
        event["schema"] == 1
        and event["event"] == "diagnostic"
        and event["severity"] == "info"
        for event in events
    )


def test_structured_diagnostics_group_multiline_process_output(
    capsys: pytest.CaptureFixture[str],
) -> None:
    stream = DiagnosticStream(format="jsonl", command="check")

    stream.relay_output("Traceback (most recent call last):\nValueError: bad input\n")

    event = json.loads(capsys.readouterr().err)
    assert event["code"] == "process-output"
    assert event["message"] == (
        "Traceback (most recent call last):\nValueError: bad input"
    )
    assert event["details"] == {"line_count": 2}


def test_structured_diagnostics_preserve_child_events(
    capsys: pytest.CaptureFixture[str],
) -> None:
    stream = DiagnosticStream(format="jsonl", command="check")
    child = {
        "schema": 1,
        "event": "diagnostic",
        "command": "check",
        "severity": "error",
        "code": "cell-execution-error",
        "message": "ValueError: bad input",
    }

    stream.relay_output(json.dumps(child) + "\nshutdown warning\n")

    events = [json.loads(line) for line in capsys.readouterr().err.splitlines()]
    assert events[0] == child
    assert events[1]["code"] == "process-output"
    assert events[1]["message"] == "shutdown warning"
    assert stream.error_count == 1


def test_structured_diagnostics_preserve_unicode_line_separators(
    capsys: pytest.CaptureFixture[str],
) -> None:
    stream = DiagnosticStream(format="jsonl", command="check")
    child = {
        "schema": 1,
        "event": "diagnostic",
        "command": "check",
        "severity": "error",
        "code": "cell-execution-error",
        "message": "bad\u2028input",
    }

    stream.relay_output(json.dumps(child, ensure_ascii=False) + "\r\n")

    assert json.loads(capsys.readouterr().err) == child
    assert stream.error_count == 1


def test_structured_diagnostics_bound_large_process_output(
    capsys: pytest.CaptureFixture[str],
) -> None:
    stream = DiagnosticStream(format="jsonl", command="check")

    stream.relay_output("x" * 20_000)

    event = json.loads(capsys.readouterr().err)
    assert event["details"]["line_count"] == 1
    assert event["details"]["truncated"] is True
    assert event["details"]["omitted_chars"] > 0
    assert event["message"].endswith("x" * 100)
    assert len(event["message"]) <= 16 * 1024


def test_failed_check_reports_exit_status_and_error_diagnostic(
    notebook_path: Path,
) -> None:
    setup = ensure_view(notebook_path)
    template = setup.root / "index.html"
    template.write_text(
        template.read_text(encoding="utf-8").replace(
            '<main id="app-shell"></main>',
            '<main id="app-shell"><marimo-cell name="missing"></marimo-cell></main>',
        ),
        encoding="utf-8",
    )

    result = CliRunner().invoke(
        cli,
        [
            "check",
            str(notebook_path),
            "--format",
            "json",
            "--diagnostics",
            "jsonl",
        ],
    )

    payload = json.loads(result.stdout)
    events = [json.loads(line) for line in result.stderr.splitlines()]
    assert result.exit_code == 1
    assert payload["ok"] is False
    event = next(event for event in events if event["severity"] == "error")
    check = next(check for check in payload["checks"] if check["status"] == "fail")
    assert event["code"] == "cell-not-found"
    assert event["details"] == check["details"]
    assert event["details"]["view"] == "dashboard"
    assert event["details"]["projection"] == "cell"
    assert event["details"]["target"] == "missing"
    assert event["details"]["source"]["path"] == str(template)
    assert "Name a notebook cell" in event["details"]["hint"]


@pytest.mark.parametrize(
    ("failure", "expected_code", "expected_hint"),
    [
        (
            "notebook",
            "notebook-source-error",
            "Fix the highlighted cell in Marimo, then save it again.",
        ),
        (
            "template",
            "template-error",
            "Fix the view template, then save it again.",
        ),
    ],
)
def test_check_preserves_repair_diagnostics(
    notebook_path: Path,
    failure: str,
    expected_code: str,
    expected_hint: str,
) -> None:
    setup = ensure_view(notebook_path)
    if failure == "notebook":
        notebook_path.write_text(
            notebook_path.read_text(encoding="utf-8").replace(
                "    doubled = x * 2",
                "    42doubled = x * 2",
            ),
            encoding="utf-8",
        )
    else:
        template = setup.root / "index.html"
        template.write_text(
            template.read_text(encoding="utf-8").replace(
                '<main id="app-shell"></main>',
                "<main></main>",
            ),
            encoding="utf-8",
        )

    result = CliRunner().invoke(
        cli,
        [
            "check",
            str(notebook_path),
            "--format",
            "json",
            "--diagnostics",
            "jsonl",
        ],
    )

    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    failed = next(check for check in payload["checks"] if check["status"] == "fail")
    event = next(
        json.loads(line)
        for line in result.stderr.splitlines()
        if json.loads(line)["severity"] == "error"
    )
    assert failed["code"] == expected_code
    assert failed["details"]["hint"] == expected_hint
    expected_source = (
        notebook_path if failure == "notebook" else setup.root / "index.html"
    )
    assert failed["details"]["source"]["path"] == str(expected_source)
    assert event["code"] == expected_code
    assert event["details"] == failed["details"]


def test_main_structures_configuration_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    missing = tmp_path / "missing"
    monkeypatch.setattr(
        sys,
        "argv",
        ["marimo-studio", "check", str(missing), "--diagnostics", "jsonl"],
    )

    with pytest.raises(SystemExit) as raised:
        main()

    output = capsys.readouterr()
    event = json.loads(output.err)
    assert raised.value.code == 3
    assert output.out == ""
    assert event["code"] == "configuration-error"
    assert event["severity"] == "error"
    assert event["exit_code"] == 3


def test_direct_launch_opens_the_native_editor_and_studio_view(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[list[str], Path | None]] = []
    opened: list[str] = []
    monkeypatch.setattr(launch_module.secrets, "token_urlsafe", lambda _size: "secret")
    monkeypatch.setattr(launch_module, "_open_later", opened.append)
    monkeypatch.setattr(
        launch_module,
        "environment_command",
        lambda _target, args: ["notebook-environment", *args],
    )
    monkeypatch.setattr(
        launch_module.subprocess,
        "run",
        lambda command, **kwargs: (
            calls.append((command, kwargs.get("cwd"))) or SimpleNamespace(returncode=0)
        ),
    )

    result = CliRunner().invoke(
        cli,
        [
            str(notebook_path),
            "--view",
            "dashboard",
            "--port",
            "9123",
            "--base-url",
            "/proxy/token",
        ],
    )

    assert result.exit_code == 0, result.output
    output = result.output.splitlines()
    assert len(output) == 2
    studio_url = urlsplit(output[0].removeprefix("Studio: ").strip())
    view_url = urlsplit(output[1].removeprefix("View:   ").strip())
    assert studio_url.hostname == "127.0.0.1"
    assert studio_url.port == 9123
    assert studio_url.path == "/proxy/token/studio/dashboard/"
    assert parse_qs(studio_url.query) == {"access_token": ["secret"]}
    assert view_url.path == "/proxy/token/dashboard/"
    assert parse_qs(view_url.query) == {"access_token": ["secret"]}
    assert opened == [output[0].removeprefix("Studio: ").strip()]
    assert len(calls) == 1
    command, cwd = calls[0]
    assert cwd == notebook_path.parent
    assert command[:4] == [
        "notebook-environment",
        "marimo",
        "edit",
        str(notebook_path),
    ]
    assert command[command.index("--host") + 1] == "127.0.0.1"
    assert command[command.index("--port") + 1] == "9123"
    assert command[command.index("--base-url") + 1] == "/proxy/token"
    assert command[-4:] == [
        "--headless",
        "--no-sandbox",
        "--token-password",
        "secret",
    ]
    assert load_studio(notebook_path).config_path == notebook_path


def test_bare_launch_discovers_the_configured_notebook(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ensure_view(notebook_path)
    calls: list[list[str]] = []
    monkeypatch.chdir(notebook_path.parent)
    monkeypatch.setattr(
        launch_module,
        "environment_command",
        lambda _target, args: ["notebook-environment", *args],
    )
    monkeypatch.setattr(
        launch_module.subprocess,
        "run",
        lambda command, **_kwargs: (
            calls.append(command) or SimpleNamespace(returncode=0)
        ),
    )

    result = CliRunner().invoke(cli, ["--headless"])

    assert result.exit_code == 0, result.output
    assert calls[0][1:4] == ["marimo", "edit", str(notebook_path)]
