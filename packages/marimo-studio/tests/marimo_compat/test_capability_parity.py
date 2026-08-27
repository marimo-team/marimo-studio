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
from marimo_studio._browser_client.protocol import ViewActivationRequest
from marimo_studio._browser_client.transport import StudioServerConnection
from marimo_studio._cli import cli, main
from marimo_studio._validation.analysis import AnalysisOptions
from marimo_studio._validation.evidence import AnalysisReport
from marimo_studio._validation.results import CheckResult
from marimo_studio.agent import ViewActivationResult
from marimo_studio.errors import AgentRequestError

from ..app_helpers import edit_mode, marimo_app, session_manager


def _workspace(notebook_path):
    return studio_agent.open(notebook=notebook_path)


def _json_command(*args: str) -> dict[str, object]:
    result = CliRunner().invoke(cli, [*args, "--format", "json"])
    assert result.exit_code == 0, result.output
    value = json.loads(result.output)
    assert isinstance(value, dict)
    return value


def test_status_adapters_follow_the_workspace_lifecycle(notebook_path) -> None:
    workspace = _workspace(notebook_path)
    original = notebook_path.read_bytes()

    def status() -> dict[str, object]:
        python = asyncio.run(workspace.status()).to_dict()
        command = _json_command("status", "--target", str(notebook_path))
        assert command == python
        return command

    unconfigured = status()
    assert unconfigured["schema"] == 2
    assert unconfigured["state"] == "unconfigured"
    assert unconfigured["views"] == []
    assert notebook_path.read_bytes() == original
    assert not (notebook_path.parent / "__marimo__").exists()

    view = asyncio.run(workspace.create_view("dashboard"))
    ready = status()
    assert ready["state"] == "ready"
    views = cast(list[dict[str, object]], ready["views"])
    assert [view["name"] for view in views] == ["dashboard"]

    shutil.rmtree(view.workspace.notebook.parent / "__marimo__")
    needs_view = status()
    assert needs_view["state"] == "needs-view"
    assert needs_view["default_view"] == "dashboard"
    assert needs_view["views"] == []


def test_static_inspection_matches(notebook_path) -> None:
    python = asyncio.run(
        _workspace(notebook_path).inspect_notebook(
            include_code=True,
            selectors=(1,),
            output_expressions=True,
            limit=1,
        )
    ).to_dict()
    command = _json_command(
        "notebook",
        "inspect",
        "--target",
        str(notebook_path),
        "--include-code",
        "--cell",
        "1",
        "--output-expressions",
        "--limit",
        "1",
    )

    assert command == python


def test_starter_catalog_adapters_match(notebook_path) -> None:
    python = {
        "schema": 1,
        "starters": [
            starter.to_dict()
            for starter in asyncio.run(_workspace(notebook_path).starters())
        ],
    }
    command = _json_command("starters")

    assert command == python


def test_provider_doctor_adapters_match() -> None:
    python = asyncio.run(studio_agent.doctor()).to_dict()
    command = _json_command("doctor")

    assert command == python


def test_view_inspection_matches(notebook_path) -> None:
    workspace = _workspace(notebook_path)
    view = asyncio.run(workspace.create_view("dashboard"))

    python = asyncio.run(view.inspect()).to_dict()
    command = _json_command(
        "view",
        "inspect",
        "dashboard",
        "--target",
        str(notebook_path),
    )

    assert command == python


def test_view_read_and_build_adapters_match(notebook_path) -> None:
    workspace = _workspace(notebook_path)
    view = asyncio.run(workspace.create_view("dashboard"))

    document = asyncio.run(view.read("index.html"))
    command_document = _json_command(
        "view",
        "read",
        "dashboard",
        "index.html",
        "--target",
        str(notebook_path),
    )
    assert command_document == {"schema": 1, **document.to_dict()}

    publication = asyncio.run(view.build()).to_dict()
    command_publication = _json_command(
        "view",
        "build",
        "dashboard",
        "--target",
        str(notebook_path),
    )
    assert command_publication["view"] == publication["view"]
    assert command_publication["profile"] == publication["profile"]
    assert command_publication["input_id"] == publication["input_id"]
    assert command_publication["artifact_id"] == publication["artifact_id"]


def test_static_validation_matches(notebook_path) -> None:
    workspace = _workspace(notebook_path)
    asyncio.run(workspace.create_view("dashboard"))

    python = asyncio.run(workspace.validate(view="dashboard")).to_dict()
    command = _json_command(
        "validate",
        "dashboard",
        "--target",
        str(notebook_path),
    )

    assert command == python


def test_analysis_adapters_use_the_same_options(
    notebook_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = _workspace(notebook_path)
    asyncio.run(workspace.create_view("dashboard"))
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
    code_connection = StudioServerConnection(
        "http://localhost:2718",
        session_id="s_123456",
    )
    cli_connection = StudioServerConnection("http://localhost:2718")
    python_options: list[AnalysisOptions] = []
    cli_options: list[AnalysisOptions] = []

    async def request_analysis(_connection, _notebook, request):
        python_options.append(request.options)
        return report

    async def analyze_studio(_workspace, options, **_kwargs):
        cli_options.append(options)
        return report

    monkeypatch.setattr(
        "marimo_studio._composition.create_code_mode_bridge",
        lambda: SimpleNamespace(
            active_notebook=lambda: notebook_path.resolve(),
            connection=lambda: code_connection,
        ),
    )
    monkeypatch.setattr(
        "marimo_studio._authoring.validation.request_analysis",
        request_analysis,
    )
    monkeypatch.setattr(
        "marimo_studio._authoring.validation.analyze_studio",
        analyze_studio,
    )
    monkeypatch.setattr(
        "marimo_studio._cli.commands.validate.should_reenter",
        lambda *_args: False,
    )

    monkeypatch.setattr(
        "marimo_studio._cli.commands.validate.studio_server_connection",
        lambda *_args, **_kwargs: cli_connection,
    )

    python = asyncio.run(
        studio_agent.open().validate(
            level="browser",
            view="dashboard",
            browser_timeout=20,
            runtime_timeout=75,
        )
    ).to_dict()
    command = _json_command(
        "validate",
        "dashboard",
        "--target",
        str(notebook_path),
        "--level",
        "browser",
        "--server",
        "http://localhost:2718",
        "--browser-timeout",
        "20",
        "--runtime-timeout",
        "75",
    )

    assert (
        python_options
        == cli_options
        == [
            AnalysisOptions(
                view="dashboard",
                browser_timeout=20,
                runtime_timeout=75,
                require_browser=True,
            )
        ]
    )
    assert command == python


def test_activation_adapters_return_the_same_result(
    notebook_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = _workspace(notebook_path)
    asyncio.run(workspace.create_view("dashboard"))
    result = ViewActivationResult(
        notebook=notebook_path.resolve(),
        view="dashboard",
        generation=3,
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
        "marimo_studio._composition.create_code_mode_bridge",
        lambda: SimpleNamespace(
            active_notebook=lambda: notebook_path.resolve(),
            connection=lambda: code_connection,
        ),
    )
    monkeypatch.setattr(
        "marimo_studio._browser_client.client.request_view_activation",
        activate,
    )
    monkeypatch.setattr(
        "marimo_studio._cli.commands.view_delivery.studio_server_connection",
        lambda *_args, **_kwargs: cli_connection,
    )

    python = asyncio.run(studio_agent.open().view("dashboard").activate()).to_dict()
    command = _json_command(
        "view",
        "activate",
        "dashboard",
        "--target",
        str(notebook_path),
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
    workspace = _workspace(notebook_path)
    asyncio.run(workspace.create_view("dashboard"))
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
        "marimo_studio._composition.create_code_mode_bridge",
        lambda: SimpleNamespace(
            active_notebook=lambda: notebook_path.resolve(),
            connection=lambda: code_connection,
        ),
    )
    monkeypatch.setattr("marimo_studio._browser_client.client.request_json", missing)
    monkeypatch.setattr(
        "marimo_studio._cli.commands.view_delivery.studio_server_connection",
        lambda *_args, **_kwargs: cli_connection,
    )

    with pytest.raises(AgentRequestError) as python_error:
        asyncio.run(studio_agent.open().view("missing").activate())

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
            "missing",
            "--target",
            str(notebook_path),
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
