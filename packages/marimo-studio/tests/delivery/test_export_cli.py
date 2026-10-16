from __future__ import annotations

import asyncio
import json
from pathlib import Path, PurePosixPath

import pytest
from click import unstyle
from click.testing import CliRunner, Result

import marimo_studio.authoring as studio_authoring
from marimo_studio._cli import cli
from marimo_studio._cli.environment import SANDBOX_ENV
from marimo_studio._delivery.export import DEFAULT_PREPARE_TIMEOUT
from marimo_studio._workspace import load_studio

from ..artifact_test_support import add_provider_outputs
from .export_test_support import configure_export_view

_PREPARE_TIMEOUT = 120.0
_MODULE_TAG = '<script type="module" src="./app.js"></script>'


def _invoke_static_view(notebook: Path, command: str, *extra: str) -> Result:
    return CliRunner().invoke(
        cli,
        [
            "view",
            command,
            "dashboard",
            "--target",
            str(notebook),
            "--runtime",
            "wasm",
            *extra,
        ],
    )


def _install_app_module(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    script: bytes,
) -> None:
    root = configure_export_view(notebook_path)
    root.joinpath("app.js").write_text("export {};\n", encoding="utf-8")
    document = root / "index.html"
    document.write_text(
        document.read_text(encoding="utf-8").replace(
            "</head>", f"{_MODULE_TAG}</head>"
        ),
        encoding="utf-8",
    )
    add_provider_outputs(
        monkeypatch,
        load_studio(notebook_path).view("dashboard"),
        {PurePosixPath("app.js"): script},
    )


@pytest.mark.native_process
@pytest.mark.xdist_group("managed-export")
def test_export_command_reports_the_static_entrypoint(
    notebook_path: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(SANDBOX_ENV, "1")
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
    progress = [
        json.loads(line)
        for line in result.stderr.splitlines()
        if json.loads(line).get("event") == "progress"
    ]
    assert payload["schema"] == 1
    assert payload["view"] == "dashboard"
    assert payload["runtime"] == "zero-python"
    assert payload["cache_activity"] is not None
    assert payload["preflight"]["ok"] is True
    assert payload["warnings"] == []
    assert progress
    assert progress[0]["command"] == "view export"
    assert {event["progress"]["source"] for event in progress} == {
        "marimo-export",
        "marimo-studio",
    }
    assert progress[0]["progress"]["event"]["kind"] == "build_started"
    assert progress[-1]["progress"]["event"]["kind"] == "commit_started"
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


def test_preflight_command_verifies_static_delivery_without_an_output(
    notebook_path: Path,
) -> None:
    configure_export_view(notebook_path)

    result = CliRunner().invoke(
        cli,
        [
            "view",
            "preflight",
            "dashboard",
            "--target",
            str(notebook_path),
            "--runtime",
            "wasm",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    progress = [json.loads(line) for line in result.stderr.splitlines()]
    assert payload["ok"] is True
    assert payload["view"] == "dashboard"
    assert payload["runtime"] == "wasm"
    assert payload["projections"]
    assert progress[0]["progress"]["event"]["kind"] == "build_started"
    assert progress[-1]["progress"]["event"]["kind"] == "preflight_finished"


@pytest.mark.parametrize("command", ("preflight", "export"))
def test_static_delivery_text_shows_each_issue_repair(
    notebook_path: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    command: str,
) -> None:
    _install_app_module(
        notebook_path,
        monkeypatch,
        b"void import(globalThis.target);\n",
    )
    output = ("--output", str(tmp_path / "site")) if command == "export" else ()
    result = _invoke_static_view(notebook_path, command, *output)

    assert result.exit_code == 0, result.output
    lines = unstyle(result.stdout).splitlines()
    issue = next(
        index for index, line in enumerate(lines) if "static-module-computed" in line
    )
    assert lines[issue + 1].strip().startswith("repair ")


@pytest.mark.parametrize("command", ("export", "preflight"))
def test_static_delivery_help_explains_runtime_and_preparation_timeout(
    command: str,
) -> None:
    result = CliRunner().invoke(cli, ["view", command, "--help"])

    assert result.exit_code == 0, result.output
    help_text = " ".join(result.output.split())
    assert "--runtime [zero-python|wasm]" in help_text
    assert "zero-python selects the Prepared runtime" in help_text
    assert "wasm selects the Browser runtime" in help_text
    assert "--prepare-timeout SECONDS" in help_text
    assert f"Defaults to {DEFAULT_PREPARE_TIMEOUT:g} seconds" in help_text


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


def test_wasm_preflight_rejects_prepare_timeout_before_resolving_target(
    tmp_path: Path,
) -> None:
    result = CliRunner().invoke(
        cli,
        [
            "view",
            "preflight",
            "dashboard",
            "--target",
            str(tmp_path / "missing.py"),
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


@pytest.mark.native_process
@pytest.mark.xdist_group("managed-export")
def test_agent_view_exports_the_same_static_bundle(
    notebook_path: Path,
    tmp_path: Path,
) -> None:
    configure_export_view(notebook_path)
    output = tmp_path / "agent-site"
    view = studio_authoring.open_workspace(notebook_path).view("dashboard")

    events = []
    result = asyncio.run(
        view.export(
            output,
            prepare_timeout=_PREPARE_TIMEOUT,
            progress=events.append,
        )
    )

    assert result.view == "dashboard"
    assert result.entrypoint == output / "index.html"
    assert result.entrypoint.is_file()
    assert result.preflight.ok
    assert events[0].event.kind == "build_started"
    assert events[-1].event.kind == "commit_started"


def test_agent_view_preflights_without_publishing_a_destination(
    notebook_path: Path,
) -> None:
    configure_export_view(notebook_path)
    view = studio_authoring.open_workspace(notebook_path).view("dashboard")
    events = []

    result = asyncio.run(
        view.preflight(
            runtime="wasm",
            progress=events.append,
        )
    )

    assert result.ok
    assert result.view == "dashboard"
    assert events[0].event.kind == "build_started"
    assert events[-1].event.kind == "preflight_finished"


def test_preflight_reports_every_error_and_exits_unsuccessfully(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_app_module(
        notebook_path,
        monkeypatch,
        b'import "./missing-first.js"; import "./missing-second.js";',
    )

    result = _invoke_static_view(notebook_path, "preflight", "--json")

    assert result.exit_code == 1
    assert result.stdout, (result.exception, result.output)
    report = json.loads(result.stdout)
    assert report["ok"] is False
    assert [issue["reference"] for issue in report["issues"]] == [
        "./missing-first.js",
        "./missing-second.js",
    ]
