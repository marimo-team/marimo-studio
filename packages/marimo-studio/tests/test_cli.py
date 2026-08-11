from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
import time
from pathlib import Path

import marimo
import pytest
from click import unstyle
from click.testing import CliRunner

from marimo_studio._cli import cli, main
from marimo_studio._cli.diagnostics import DiagnosticStream
from marimo_studio._workspace import load_studio
from marimo_studio._workspace.environment import SANDBOX_ENV
from marimo_studio.workspace import ensure_view

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
        env={**os.environ, SANDBOX_ENV: "1"},
        text=True,
    )


def test_view_add_bootstraps_lists_and_checks_named_views(
    notebook_path: Path,
) -> None:
    runner = CliRunner()

    created = runner.invoke(
        cli,
        ["view", "add", str(notebook_path), "--format", "json"],
    )
    added = runner.invoke(
        cli,
        [
            "view",
            "add",
            str(notebook_path),
            "--name",
            "executive",
            "--format",
            "json",
        ],
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
    assert Path(json.loads(created.output)["root"]) == (
        notebook_path.parent / "__marimo__" / "studio" / "analysis" / "dashboard"
    )
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


def test_view_add_reports_the_editor_command(notebook_path: Path) -> None:
    result = CliRunner().invoke(cli, ["view", "add", str(notebook_path)])

    assert result.exit_code == 0, result.output
    arguments = ["marimo", "edit", str(notebook_path), "--sandbox"]
    expected = (
        subprocess.list2cmdline(arguments) if os.name == "nt" else shlex.join(arguments)
    )
    assert expected in unstyle(result.stderr)


def test_view_add_resolves_an_uninitialized_project_from_the_current_directory(
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

    result = CliRunner().invoke(cli, ["view", "add", "--format", "json"])

    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["config"] == str(pyproject)
    assert load_studio(pyproject).default_view == "dashboard"


def test_help_teaches_target_first_workflows() -> None:
    runner = CliRunner()

    root = runner.invoke(cli, ["--help"])
    add = runner.invoke(cli, ["view", "add", "--help"])
    bind_help = runner.invoke(cli, ["bind", "--help"])

    assert root.exit_code == 0
    assert "marimo-studio view add analysis.py" in root.output
    assert "marimo edit analysis.py --sandbox" in root.output
    assert "Usage: cli view add [OPTIONS] [TARGET]" in add.output
    assert "--name NAME" in add.output
    assert "Usage: cli bind [OPTIONS] [TARGET]" in bind_help.output
    assert "--as ALIAS" in bind_help.output


def test_cli_bind_updates_the_shared_cell_registry(
    notebook_path: Path,
) -> None:
    ensure_view(notebook_path)
    runner = CliRunner()

    bound = runner.invoke(
        cli,
        [
            "bind",
            str(notebook_path),
            "--cell",
            "1",
            "--as",
            "summary",
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


def test_view_remove_preserves_source_when_confirmation_is_declined(
    notebook_path: Path,
) -> None:
    ensure_view(notebook_path)
    added = ensure_view(notebook_path, "executive")

    result = CliRunner().invoke(
        cli,
        ["view", "remove", str(notebook_path), "--name", "executive"],
        input="n\n",
    )

    assert result.exit_code == 1
    assert added.root.is_dir()
    assert set(load_studio(notebook_path).views) == {"dashboard", "executive"}


def test_view_remove_reports_the_updated_view_inventory(notebook_path: Path) -> None:
    dashboard = ensure_view(notebook_path).root
    ensure_view(notebook_path, "executive")

    result = CliRunner().invoke(
        cli,
        [
            "view",
            "remove",
            str(notebook_path),
            "--name",
            "dashboard",
            "--yes",
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == {
        "default_view": "executive",
        "notebook": str(notebook_path),
        "schema": 1,
        "view": "dashboard",
        "views": ["executive"],
    }
    assert not dashboard.exists()


def test_view_remove_requires_noninteractive_confirmation_for_jsonl(
    notebook_path: Path,
    runtime_assets: Path,
) -> None:
    ensure_view(notebook_path)
    added = ensure_view(notebook_path, "executive")

    result = _run_cli(
        runtime_assets,
        "view",
        "remove",
        str(notebook_path),
        "--name",
        "executive",
        "--diagnostics",
        "jsonl",
    )

    assert result.returncode == 2
    assert result.stdout == ""
    assert json.loads(result.stderr) == {
        "schema": 1,
        "event": "diagnostic",
        "command": "view remove",
        "severity": "error",
        "code": "usage-error",
        "message": "Pass --yes when using JSON Lines diagnostics.",
        "exit_code": 2,
    }
    assert added.root.is_dir()


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


def test_analyze_returns_the_agent_handoff_contract(
    notebook_path: Path,
    runtime_assets: Path,
) -> None:
    ensure_view(notebook_path)

    result = _run_cli(
        runtime_assets,
        "analyze",
        str(notebook_path),
        "--view",
        "dashboard",
        "--format",
        "json",
    )

    assert result.returncode == 1, result.stderr
    payload = json.loads(result.stdout)
    assert payload["schema"] == 1
    assert payload["views"] == ["dashboard"]
    assert payload["ok"] is False
    assert payload["handoff_ready"] is False
    assert payload["runtime"] == "server"
    assert set(payload["revisions"]) == {"dashboard"}
    static_stage = payload["stages"]["static"]
    runtime_stage = payload["stages"]["runtime"]
    assert static_stage["status"] == "pass", static_stage
    assert runtime_stage["status"] == "pass", runtime_stage
    assert payload["stages"]["browser"] == {
        "required": True,
        "status": "not-observed",
        "observations": [
            {
                "view": "dashboard",
                "state": "not-observed",
                "diagnostics": [],
                "message": "No rendered browser observation was requested.",
                "code": "browser-not-requested",
            }
        ],
    }
    assert payload["actions"] == [
        {
            "stage": "browser",
            "severity": "error",
            "code": "browser-not-requested",
            "message": "No rendered browser observation was requested.",
            "advice": (
                "Open Studio for this notebook, select the view, then rerun "
                "the analysis."
            ),
            "view": "dashboard",
        }
    ]


@pytest.mark.parametrize(
    "server_url",
    [
        "ftp://localhost:2718",
        "http://localhost:abc",
        "http://localhost:99999",
        "http://localhost:2718?access_token=secret",
        "http://localhost:2718/#access_token=secret",
        "http://user@localhost:2718",
        "http://user:secret@localhost:2718",
    ],
)
def test_analyze_rejects_malformed_server_urls_as_usage_errors(
    notebook_path: Path,
    runtime_assets: Path,
    server_url: str,
) -> None:
    ensure_view(notebook_path)

    result = _run_cli(
        runtime_assets,
        "analyze",
        str(notebook_path),
        "--server",
        server_url,
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
    assert events[0]["command"] == "analyze"
    assert events[0]["severity"] == "error"
    assert events[0]["code"] == "usage-error"
    assert events[0]["exit_code"] == 2
    assert "--server" in events[0]["message"]


def test_analyze_rejects_browser_selection_without_a_server() -> None:
    result = CliRunner().invoke(
        cli,
        ["analyze", "--browser-client", "browser-client-1234"],
    )

    assert result.exit_code == 2
    assert "--browser-client" in result.output
    assert "--server" in result.output


def test_analyze_keeps_access_tokens_out_of_command_arguments() -> None:
    result = CliRunner().invoke(cli, ["analyze", "--help"])

    assert result.exit_code == 0
    assert "--access-token" not in result.output
    assert "MARIMO_STUDIO_ACCESS_TOKEN" in result.output
    assert "--runtime-timeout" in result.output


@pytest.mark.parametrize("command", ["analyze", "check"])
def test_runtime_timeout_must_be_finite(command: str) -> None:
    result = CliRunner().invoke(
        cli,
        [command, "--runtime-timeout", "nan"],
    )

    assert result.exit_code == 2
    assert "finite number" in result.output


def test_runtime_timeout_bounds_projected_output_rendering(
    tmp_path: Path,
    runtime_assets: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    notebook = tmp_path / "slow_outputs.py"
    marker = tmp_path / "formatted.txt"
    names = tuple(f"output_{index}" for index in range(8))
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
            time.sleep(0.8)
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
    monkeypatch.setenv(SANDBOX_ENV, "1")

    started = time.monotonic()
    result = _run_cli(
        runtime_assets,
        "check",
        str(notebook),
        "--runtime",
        "--runtime-timeout",
        "3",
        "--diagnostics",
        "jsonl",
    )
    elapsed = time.monotonic() - started

    assert result.returncode == 1, result.stderr
    assert marker.exists()
    assert elapsed < 6
    events = [json.loads(line) for line in result.stderr.splitlines()]
    assert events[-1]["code"] == "runtime-timeout"


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
        "message": "ValueError:\u2028bad input",
    }

    stream.relay_output(
        json.dumps(child, ensure_ascii=False) + "\r\nshutdown warning\n"
    )

    events = [json.loads(line) for line in capsys.readouterr().err.split("\n") if line]
    assert events[0] == child
    assert events[1]["code"] == "process-output"
    assert events[1]["message"] == "shutdown warning"
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
