from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from click import unstyle
from click.testing import CliRunner

from marimo_studio._cli import cli, main
from marimo_studio._cli.diagnostics import DiagnosticStream
from marimo_studio._workspace import ensure_view, load_studio

from .helpers import replace_app_shell


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
        replace_app_shell(
            template.read_text(encoding="utf-8"),
            '<marimo-cell name="missing"></marimo-cell>',
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
            replace_app_shell(template.read_text(encoding="utf-8"), "").replace(
                '<main id="app-shell"></main>', "<main></main>"
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
