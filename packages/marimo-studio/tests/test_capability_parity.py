from __future__ import annotations

import asyncio
import json
import shutil
import sys
from types import SimpleNamespace
from typing import cast

import pytest
from click.testing import CliRunner
from starlette.testclient import TestClient

import marimo_studio.agent as studio_agent
from marimo_studio._agent_transport import StudioServerConnection
from marimo_studio._cli import cli, main
from marimo_studio.activation import ViewActivationRequest, ViewActivationResult
from marimo_studio.agent_models import AnalysisReport
from marimo_studio.analysis import AnalysisOptions
from marimo_studio.errors import AgentRequestError
from marimo_studio.types import CheckResult

from .app_helpers import edit_mode, marimo_app, session_manager


def _context(notebook_path):
    return SimpleNamespace(globals={"__file__": str(notebook_path)})


def _json_command(*args: str) -> dict[str, object]:
    result = CliRunner().invoke(cli, [*args, "--format", "json"])
    assert result.exit_code == 0, result.output
    value = json.loads(result.output)
    assert isinstance(value, dict)
    return value


def test_overview_matches_before_workspace_setup(notebook_path) -> None:
    original = notebook_path.read_bytes()

    python = studio_agent.overview(_context(notebook_path)).to_dict()
    command = _json_command("overview", str(notebook_path))

    assert command == python
    assert command["state"] == "unconfigured"
    assert command["views"] == []
    assert notebook_path.read_bytes() == original
    assert not (notebook_path.parent / "__marimo__").exists()


def test_overview_matches_after_workspace_setup(notebook_path) -> None:
    studio_agent.ensure_view(_context(notebook_path), "dashboard")

    python = studio_agent.overview(_context(notebook_path)).to_dict()
    command = _json_command("overview", str(notebook_path))

    assert command == python
    assert command["state"] == "ready"
    views = cast(list[dict[str, object]], command["views"])
    assert [view["name"] for view in views] == ["dashboard"]


def test_overview_matches_when_configuration_needs_its_first_view(
    notebook_path,
) -> None:
    setup = studio_agent.ensure_view(_context(notebook_path), "dashboard")
    shutil.rmtree(setup.root.parent)

    python = studio_agent.overview(_context(notebook_path)).to_dict()
    command = _json_command("overview", str(notebook_path))

    assert command == python
    assert command["state"] == "needs-view"
    assert command["default_view"] == "dashboard"
    assert command["views"] == []


def test_static_inspection_matches(notebook_path) -> None:
    python = studio_agent.inspect(
        _context(notebook_path),
        include_code=True,
        display=True,
        limit=1,
    ).to_dict()
    command = _json_command(
        "inspect",
        str(notebook_path),
        "--include-code",
        "--display",
        "--limit",
        "1",
    )

    assert command == python


def test_view_setup_dry_run_matches(notebook_path) -> None:
    python = studio_agent.ensure_view(
        _context(notebook_path),
        "dashboard",
        dry_run=True,
    ).to_dict()
    command = _json_command(
        "view",
        "add",
        str(notebook_path),
        "--name",
        "dashboard",
        "--dry-run",
    )

    assert command == python


def test_binding_dry_run_matches(notebook_path) -> None:
    studio_agent.ensure_view(_context(notebook_path), "dashboard")

    python = studio_agent.bind(
        _context(notebook_path),
        "summary",
        1,
        dry_run=True,
    ).to_dict()
    command = _json_command(
        "bind",
        str(notebook_path),
        "--cell",
        "1",
        "--as",
        "summary",
        "--dry-run",
    )

    assert command == python


def test_static_check_matches(notebook_path) -> None:
    studio_agent.ensure_view(_context(notebook_path), "dashboard")

    python = studio_agent.check(
        _context(notebook_path),
        view_name="dashboard",
    ).to_dict()
    command = _json_command(
        "check",
        str(notebook_path),
        "--view",
        "dashboard",
    )

    assert command == python


def test_analysis_adapters_use_the_same_options(
    notebook_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context(notebook_path)
    studio_agent.ensure_view(context, "dashboard")
    report = AnalysisReport(
        notebook=notebook_path.resolve(),
        views=("dashboard",),
        runtime="server",
        revisions={"dashboard": "revision-1"},
        static_checks=(CheckResult("static", "pass", "Sources are valid"),),
        runtime_checks=(CheckResult("runtime", "pass", "Runtime is valid"),),
        runtime_skipped=None,
        browser_observations=(),
        browser_required=False,
        actions=(),
    )
    connection = StudioServerConnection("http://localhost:2718")
    python_options: list[AnalysisOptions] = []
    cli_options: list[AnalysisOptions] = []

    async def request_analysis(_connection, _notebook, request):
        python_options.append(request.options)
        return report

    async def analyze_studio(_workspace, options, **_kwargs):
        cli_options.append(options)
        return report

    monkeypatch.setattr(
        "marimo_studio._composition.create_tooling_adapters",
        lambda: SimpleNamespace(
            code_mode=SimpleNamespace(connection=lambda: connection)
        ),
    )
    monkeypatch.setattr(
        "marimo_studio._agent_client.request_analysis",
        request_analysis,
    )
    monkeypatch.setattr(
        "marimo_studio._cli.commands.analyze.analyze_studio",
        analyze_studio,
    )
    monkeypatch.setattr(
        "marimo_studio._cli.commands.analyze.should_reenter",
        lambda *_args: False,
    )

    python = asyncio.run(
        studio_agent.analyze(
            context,
            view="dashboard",
            browser_timeout=20,
            runtime_timeout=75,
            require_browser=False,
        )
    ).to_dict()
    command = _json_command(
        "analyze",
        str(notebook_path),
        "--view",
        "dashboard",
        "--browser-timeout",
        "20",
        "--runtime-timeout",
        "75",
        "--no-browser",
    )

    assert (
        python_options
        == cli_options
        == [
            AnalysisOptions(
                view="dashboard",
                browser_timeout=20,
                runtime_timeout=75,
                require_browser=False,
            )
        ]
    )
    assert command == python


def test_activation_adapters_return_the_same_result(
    notebook_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context(notebook_path)
    studio_agent.ensure_view(context, "dashboard")
    result = ViewActivationResult(
        notebook=notebook_path.resolve(),
        view="dashboard",
        state="active",
        generation=3,
        transition="in-place",
        client_id="browser-client-1234",
        session_id="s_123456",
    )
    code_connection = StudioServerConnection(
        "http://localhost:2718",
        session_id="s_123456",
    )
    cli_connection = StudioServerConnection(
        "http://localhost:2718",
        browser_client="browser-client-1234",
    )
    requests: list[tuple[StudioServerConnection, ViewActivationRequest]] = []

    async def activate(connection, _notebook, request):
        requests.append((connection, request))
        return result

    monkeypatch.setattr(
        "marimo_studio._composition.create_tooling_adapters",
        lambda: SimpleNamespace(
            code_mode=SimpleNamespace(connection=lambda: code_connection)
        ),
    )
    monkeypatch.setattr(
        "marimo_studio._agent_client.request_view_activation",
        activate,
    )
    monkeypatch.setattr(
        "marimo_studio._cli.commands.view.studio_server_connection",
        lambda *_args, **_kwargs: cli_connection,
    )

    python = asyncio.run(studio_agent.activate_view(context, "dashboard")).to_dict()
    command = _json_command(
        "view",
        "activate",
        str(notebook_path),
        "--name",
        "dashboard",
        "--server",
        "http://localhost:2718",
        "--browser-client",
        "browser-client-1234",
    )

    assert command == python == result.to_dict()
    assert requests == [
        (code_connection, ViewActivationRequest("dashboard")),
        (
            cli_connection,
            ViewActivationRequest(
                "dashboard",
                browser_client="browser-client-1234",
            ),
        ),
    ]


def test_activation_view_not_found_code_matches_python_http_and_cli(
    notebook_path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    context = _context(notebook_path)
    studio_agent.ensure_view(context, "dashboard")
    code_connection = StudioServerConnection(
        "http://localhost:2718",
        server_token="server-token",
        session_id="s_123456",
    )
    cli_connection = StudioServerConnection(
        "http://localhost:2718",
        server_token="server-token",
    )

    async def missing(*_args, **_kwargs):
        raise AgentRequestError(
            "view-not-found",
            "View 'missing' does not exist.",
            status_code=404,
            details={
                "view": "missing",
                "available_views": ["dashboard"],
            },
        )

    monkeypatch.setattr(
        "marimo_studio._composition.create_tooling_adapters",
        lambda: SimpleNamespace(
            code_mode=SimpleNamespace(connection=lambda: code_connection)
        ),
    )
    monkeypatch.setattr("marimo_studio._agent_client.request_json", missing)
    monkeypatch.setattr(
        "marimo_studio._cli.commands.view.studio_server_connection",
        lambda *_args, **_kwargs: cli_connection,
    )

    with pytest.raises(AgentRequestError) as python_error:
        asyncio.run(studio_agent.activate_view(context, "missing"))

    app = marimo_app(notebook_path)
    edit_mode(app)
    headers = {"Marimo-Server-Token": str(session_manager(app).skew_protection_token)}
    with TestClient(app) as client:
        http = client.patch(
            "/_marimo-studio/views/missing/activate",
            headers=headers,
            json={"schema": 1, "browser_client": None},
        )

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "marimo-studio",
            "view",
            "activate",
            str(notebook_path),
            "--name",
            "missing",
            "--server",
            "http://localhost:2718",
            "--diagnostics",
            "jsonl",
        ],
    )
    with pytest.raises(SystemExit) as cli_exit:
        main()
    event = json.loads(capsys.readouterr().err)

    assert python_error.value.code == event["code"] == http.json()["error"]
    assert (
        python_error.value.exit_code == cli_exit.value.code == event["exit_code"] == 5
    )
    assert python_error.value.status_code == http.status_code == 404
    expected_details = {
        "view": "missing",
        "available_views": ["dashboard"],
    }
    assert python_error.value.diagnostic_details() == expected_details
    assert event["details"] == expected_details
    assert {
        "view": http.json()["view"],
        "available_views": http.json()["available_views"],
    } == expected_details
