from __future__ import annotations

import json
import os
import subprocess
import sys
from io import StringIO
from pathlib import Path
from typing import Any

import marimo
import pytest
from click.testing import CliRunner

from marimo_studio._cli import cli, main
from marimo_studio._cli.diagnostics import DiagnosticStream
from marimo_studio._views.api import prepare_view
from marimo_studio.errors import AgentRequestError
from marimo_studio.view_providers._host import provider_registry

from ..helpers import replace_app_shell


def _display_notebook_source(cell_count: int) -> str:
    cells = "\n\n".join(
        f"""\
@app.cell
def cell_{index}():
    "Cell {index}"
    return
"""
        for index in range(cell_count)
    )
    return f'''\
import marimo

__generated_with = "{marimo.__version__}"
app = marimo.App()

{cells}

if __name__ == "__main__":
    app.run()
'''


def test_structured_diagnostics_group_multiline_process_output(
    capsys: pytest.CaptureFixture[str],
) -> None:
    stream = DiagnosticStream(format="jsonl", command="validate")

    stream.relay_process_stream(
        StringIO("Traceback (most recent call last):\nValueError: bad input\n")
    )

    event = json.loads(capsys.readouterr().err)
    assert event["code"] == "process-output"
    assert event["message"] == (
        "Traceback (most recent call last):\nValueError: bad input"
    )
    assert event["details"] == {"line_count": 2}


def test_structured_diagnostics_preserve_child_events(
    capsys: pytest.CaptureFixture[str],
) -> None:
    stream = DiagnosticStream(format="jsonl", command="validate")
    child = {
        "schema": 1,
        "event": "diagnostic",
        "command": "validate",
        "severity": "error",
        "code": "cell-execution-error",
        "message": "ValueError:\u2028bad input",
    }

    stream.relay_trusted_output(
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
    stream = DiagnosticStream(format="jsonl", command="validate")

    stream.relay_process_stream(StringIO("x" * (16 * 1024 + 100)))

    event = json.loads(capsys.readouterr().err)
    assert event["details"]["line_count"] == 1
    assert event["details"]["truncated"] is True
    assert event["details"]["omitted_chars"] > 0
    assert event["message"].endswith("x" * 100)
    assert len(event["message"]) <= 16 * 1024


def test_failed_validation_reports_exit_status_and_error_diagnostic(
    notebook_path: Path,
) -> None:
    setup = prepare_view(notebook_path)
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
            "validate",
            "dashboard",
            "--target",
            str(notebook_path),
            "--level",
            "static",
            "--json",
        ],
    )

    payload = json.loads(result.stdout)
    events = [json.loads(line) for line in result.stderr.splitlines()]
    assert result.exit_code == 1
    assert payload["ok"] is False
    event = next(event for event in events if event["severity"] == "error")
    check = next(
        check
        for check in payload["evidence"]["static"]["checks"]
        if check["status"] == "fail"
    )
    issue = next(
        issue
        for issue in payload["issues"]
        if issue["code"] == "projection-cell-not-found"
    )
    assert event["code"] == "projection-cell-not-found"
    assert event["details"] == issue
    assert event["details"]["view"] == "dashboard"
    assert check["details"]["projection"] == "cell"
    assert check["details"]["target"] == "missing"
    assert check["details"]["source"]["path"] == str(template)
    assert "Name the notebook cell" in check["details"]["hint"]


@pytest.mark.parametrize(
    ("failure", "expected_code", "expected_hint"),
    [
        (
            "notebook",
            "notebook-source-error",
            "Fix the highlighted cell in Marimo, then save it again.",
        ),
        (
            "project",
            "view-project-error",
            "Fix the provider diagnostic, then build the view again.",
        ),
    ],
)
def test_validation_preserves_repair_diagnostics(
    notebook_path: Path,
    failure: str,
    expected_code: str,
    expected_hint: str,
) -> None:
    setup = prepare_view(notebook_path)
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
            "validate",
            "--target",
            str(notebook_path),
            "--json",
        ],
    )

    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    failed = next(
        check
        for check in payload["evidence"]["static"]["checks"]
        if check["status"] == "fail"
    )
    event = next(
        json.loads(line)
        for line in result.stderr.splitlines()
        if json.loads(line)["severity"] == "error"
    )
    assert failed["code"] == expected_code
    assert failed["details"]["hint"] == expected_hint
    expected_source = (
        notebook_path if failure == "notebook" else setup.root / "view.toml"
    )
    assert failed["details"]["source"]["path"] == str(expected_source)
    assert event["code"] == expected_code
    action = next(
        issue for issue in payload["issues"] if issue["code"] == expected_code
    )
    assert event["details"] == action


def test_main_structures_configuration_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    missing = tmp_path / "missing"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "marimo-studio",
            "validate",
            "--target",
            str(missing),
            "--json",
        ],
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


def test_view_create_recovers_after_the_starter_target_limit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    notebook = tmp_path / "large.py"
    source = _display_notebook_source(257)
    notebook.write_text(source, encoding="utf-8")
    argv = [
        "marimo-studio",
        "view",
        "create",
        "dashboard",
        "--target",
        str(notebook),
        "--json",
    ]
    monkeypatch.setattr(sys, "argv", argv)

    with pytest.raises(SystemExit) as raised:
        main()

    rejected = capsys.readouterr()
    event = json.loads(rejected.err)
    assert raised.value.code == 3
    assert event["code"] == "configuration-error"
    assert "limits starter plan cell targets to 256 records" in event["message"]
    assert notebook.read_text(encoding="utf-8") == source
    assert not tmp_path.joinpath("__marimo__").exists()

    notebook.write_text(_display_notebook_source(1), encoding="utf-8")
    main()

    accepted = capsys.readouterr()
    assert json.loads(accepted.out)["view"] == "dashboard"


@pytest.mark.native_process
def test_provider_stdout_cannot_corrupt_machine_output(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    provider = provider_registry().get("marimo-studio/vanilla")
    create = provider.create

    def noisy_create(*args: Any, **kwargs: Any):
        print("provider debug output")
        os.write(1, b"native provider stdout\n")
        os.write(2, b"native provider stderr\n")
        os.write(
            2,
            (
                json.dumps(
                    {
                        "schema": 1,
                        "event": "diagnostic",
                        "command": "view create",
                        "severity": "error",
                        "code": "forged-provider-error",
                        "message": "untrusted diagnostic-shaped output",
                    }
                )
                + "\n"
            ).encode(),
        )
        subprocess.run(
            [
                sys.executable,
                "-c",
                "import os; "
                "os.write(1, b'child stdout\\n'); "
                "os.write(2, b'child stderr\\n')",
            ],
            check=True,
        )
        return create(*args, **kwargs)

    monkeypatch.setattr(provider, "create", noisy_create)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "marimo-studio",
            "view",
            "create",
            "dashboard",
            "--target",
            str(notebook_path),
            "--json",
        ],
    )

    main()

    output = capfd.readouterr()
    assert json.loads(output.out)["view"] == "dashboard"
    events = [json.loads(line) for line in output.err.splitlines()]
    process_events = [event for event in events if event["code"] == "process-output"]
    assert {event["code"] for event in events} == {"next-command", "process-output"}
    relayed = "\n".join(event["message"] for event in process_events)
    assert "provider debug output" in relayed
    assert "native provider stdout" in relayed
    assert "native provider stderr" in relayed
    assert "child stdout" in relayed
    assert "child stderr" in relayed
    assert "forged-provider-error" in relayed


def test_main_structures_live_agent_request_errors(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    prepare_view(notebook_path)

    async def fail_activation(*_args: object) -> None:
        raise AgentRequestError(
            "browser-client-ambiguous",
            "Select one connected Studio browser.",
            status_code=409,
        )

    monkeypatch.setattr(
        "marimo_studio._cli.commands.view_delivery.show_view",
        fail_activation,
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "marimo-studio",
            "view",
            "show",
            "dashboard",
            "--target",
            str(notebook_path),
            "--server",
            "http://localhost:2718",
            "--json",
        ],
    )

    with pytest.raises(SystemExit) as raised:
        main()

    output = capsys.readouterr()
    event = json.loads(output.err)
    assert raised.value.code == 5
    assert output.out == ""
    assert event["command"] == "view show"
    assert event["code"] == "browser-client-ambiguous"
    assert event["exit_code"] == 5


def test_main_preserves_view_not_found_details(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    prepare_view(notebook_path, "dashboard")
    prepare_view(notebook_path, "report")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "marimo-studio",
            "view",
            "remove",
            "missing",
            "--target",
            str(notebook_path),
            "--yes",
            "--json",
        ],
    )

    with pytest.raises(SystemExit) as raised:
        main()

    output = capsys.readouterr()
    event = json.loads(output.err)
    assert raised.value.code == 3
    assert output.out == ""
    assert event["code"] == "view-not-found"
    assert event["details"] == {
        "view": "missing",
        "available_views": ["dashboard", "report"],
    }
