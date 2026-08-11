from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from starlette.testclient import TestClient

from marimo_studio._capabilities import ServerContext, ServerHandle, SessionState
from marimo_studio._compat.server.gateway import _ContextHandle
from marimo_studio._compat.server.session_state import PrivateSessionState
from marimo_studio._server import agent_api, browser_agent, dev
from marimo_studio._server.agent_coordinator import AgentCoordinator
from marimo_studio._server.live_clients import StudioClientRegistry
from marimo_studio._server.notebook_scope import NotebookScope
from marimo_studio._server.presentation import NotebookPresentation
from marimo_studio._server.runtimes import RuntimeRegistry
from marimo_studio.agent_models import BrowserObservation
from marimo_studio.errors import AgentRequestError
from marimo_studio.types import CheckResult

from .app_helpers import configured, edit_mode, marimo_app, session_manager


def test_authenticated_agent_connection_returns_the_mutation_token(
    notebook_path: Path,
) -> None:
    studio = configured(notebook_path)
    app = marimo_app(studio.notebook, token="test-token", skew_protection=True)
    edit_mode(app)

    with TestClient(app) as client:
        missing = client.get(
            "/_marimo-studio/agent/connection",
            headers={"Accept": "application/json"},
            follow_redirects=False,
        )
        invalid = client.get(
            "/_marimo-studio/agent/connection",
            headers={
                "Accept": "application/json",
                "Authorization": "Bearer invalid-token",
            },
            follow_redirects=False,
        )
        response = client.get(
            "/_marimo-studio/agent/connection",
            headers={
                "Accept": "application/json",
                "Authorization": "Bearer test-token",
            },
        )

    assert missing.status_code == 401
    assert missing.json()["error"] == "authentication-required"
    assert invalid.status_code == 401
    assert invalid.json()["error"] == "authentication-required"
    assert response.status_code == 200
    assert response.json() == {
        "schema": 1,
        "notebook": str(studio.notebook),
        "server_token": str(session_manager(app).skew_protection_token),
    }


def test_change_stream_delivers_agent_view_activation(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    studio = configured(notebook_path)
    clients = StudioClientRegistry()
    agents = AgentCoordinator(clients)
    native_sleep = asyncio.sleep

    async def poll_immediately(_delay: float) -> None:
        await native_sleep(0)

    monkeypatch.setattr(dev.asyncio, "sleep", poll_immediately)
    stopping = False

    async def collect() -> tuple[bytes, bytes, bytes]:
        nonlocal stopping
        client_id = "browser-client-1234"
        stream = dev.change_events(
            studio,
            stop_requested=lambda: stopping,
            clients=clients,
            agents=agents,
            client_id=client_id,
        )
        ready = await anext(stream)
        await clients.bind_session("s_123456", client_id)
        target = await clients.select_target(client_id=client_id)
        activation = await agents.activate(target, "executive")
        activated = await asyncio.wait_for(anext(stream), timeout=1)
        session = await asyncio.wait_for(anext(stream), timeout=1)
        stopping = True
        with pytest.raises(StopAsyncIteration):
            await asyncio.wait_for(anext(stream), timeout=1)
        assert activation.generation == 1
        return ready, activated, session

    ready, activated, session = asyncio.run(collect())

    assert ready == b"event: ready\ndata: {}\n\n"
    assert activated == (
        b'event: activate\ndata: {"schema":1,"generation":1,"view":"executive"}\n\n'
    )
    assert json.loads(session.split(b"data: ", 1)[1]) == {
        "schema": 1,
        "generation": 1,
        "sessionId": "s_123456",
        "replaced": False,
    }
    with pytest.raises(AgentRequestError, match="not connected"):
        asyncio.run(clients.select_target(client_id="browser-client-1234"))


def test_change_stream_reports_each_editor_session_binding(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    studio = configured(notebook_path)
    clients = StudioClientRegistry()
    agents = AgentCoordinator(clients)
    native_sleep = asyncio.sleep

    async def poll_immediately(_delay: float) -> None:
        await native_sleep(0)

    monkeypatch.setattr(dev.asyncio, "sleep", poll_immediately)
    stopping = False

    async def collect() -> tuple[bytes, bytes]:
        nonlocal stopping
        client_id = "browser-client-1234"
        stream = dev.change_events(
            studio,
            stop_requested=lambda: stopping,
            clients=clients,
            agents=agents,
            client_id=client_id,
        )
        assert await anext(stream) == b"event: ready\ndata: {}\n\n"
        await clients.bind_session("s_123456", client_id)
        first = await asyncio.wait_for(anext(stream), timeout=1)
        await clients.bind_session("s_654321", client_id)
        second = await asyncio.wait_for(anext(stream), timeout=1)
        stopping = True
        with pytest.raises(StopAsyncIteration):
            await asyncio.wait_for(anext(stream), timeout=1)
        return first, second

    first, second = asyncio.run(collect())

    assert json.loads(first.split(b"data: ", 1)[1]) == {
        "schema": 1,
        "generation": 1,
        "sessionId": "s_123456",
        "replaced": False,
    }
    assert json.loads(second.split(b"data: ", 1)[1]) == {
        "schema": 1,
        "generation": 2,
        "sessionId": "s_654321",
        "replaced": True,
    }


def test_native_page_reload_waits_for_code_mode_to_finish() -> None:
    notifications: list[Any] = []
    scratchpad_lock = asyncio.Lock()
    session = SimpleNamespace(
        scratchpad_lock=scratchpad_lock,
        notify=lambda notification, **_kwargs: notifications.append(notification),
    )
    manager = SimpleNamespace(
        get_session_by_file_key=lambda _file_key: session,
    )
    context = ServerContext(
        notebook=Path("analysis.py"),
        file_key="analysis.py",
        base_url="",
        mode="edit",
        dev=True,
        routing_query=(),
        user_config={},
        config_overrides={},
        server_token="",
        handle=ServerHandle(_ContextHandle(server=None, session_manager=manager)),
    )

    async def exercise() -> None:
        await scratchpad_lock.acquire()
        transition = asyncio.create_task(
            PrivateSessionState().reload_page(context, "executive")
        )
        await asyncio.sleep(0)
        assert notifications == []
        scratchpad_lock.release()
        await transition

    asyncio.run(exercise())

    assert [notification.name for notification in notifications] == [
        "query-params-set",
        "reload",
    ]
    assert notifications[0].key == "marimo_studio_view"
    assert notifications[0].value == "executive"


def test_edit_workspace_records_browser_readiness_and_requests_active_view(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    studio = configured(notebook_path)
    app = marimo_app(studio.notebook)
    edit_mode(app)
    headers = {"Marimo-Server-Token": str(session_manager(app).skew_protection_token)}
    revision = NotebookPresentation(studio.notebook).snapshot("dashboard").revision

    async def record(
        _coordinator: AgentCoordinator,
        observation: BrowserObservation,
    ) -> bool:
        return observation.request_id == "request-dashboard"

    async def observe(*_args: object, **_kwargs: object):
        return (
            BrowserObservation(
                view="dashboard",
                state="error",
                runtime="server",
                revision=revision,
                diagnostics=(),
                client_id="browser-client-1234",
                runtime_instance="runtime-instance",
                request_id="request-dashboard",
                sequence=4,
                query="",
            ),
        )

    async def ignore_reload(*_args: object, **_kwargs: object) -> None:
        return None

    async def no_session_client(*_args: object, **_kwargs: object) -> None:
        return None

    monkeypatch.setattr(AgentCoordinator, "record", record)
    monkeypatch.setattr(
        StudioClientRegistry,
        "wait_for_session_target",
        no_session_client,
    )
    monkeypatch.setattr(browser_agent, "observe_views", observe)
    monkeypatch.setattr(PrivateSessionState, "exists", lambda *_args: True)
    monkeypatch.setattr(PrivateSessionState, "reload_page", ignore_reload)

    with TestClient(app) as client:
        recorded = client.put(
            "/_marimo-studio/views/dashboard/observation",
            headers=headers,
            json={
                "schema": 1,
                "view": "dashboard",
                "runtime": "server",
                "revision": revision,
                "state": "error",
                "diagnostics": [],
                "clientId": "browser-client-1234",
                "runtimeInstance": "runtime-instance",
                "sessionId": "s_123456",
                "requestId": "request-dashboard",
                "sequence": 4,
                "query": "",
            },
        )
        observed = client.post(
            "/_marimo-studio/observations",
            headers=headers,
            json={
                "schema": 1,
                "views": ["dashboard"],
                "revisions": {"dashboard": revision},
                "runtime": "server",
                "timeout": 10,
                "browserClient": None,
            },
        )
        missing_observation_token = client.post(
            "/_marimo-studio/observations",
            json={
                "schema": 1,
                "views": ["dashboard"],
                "revisions": {"dashboard": revision},
                "runtime": "server",
                "timeout": 10,
                "browserClient": None,
            },
        )
        invalid_observation_token = client.post(
            "/_marimo-studio/observations",
            headers={"Marimo-Server-Token": "stale-token"},
            json={
                "schema": 1,
                "views": ["dashboard"],
                "revisions": {"dashboard": revision},
                "runtime": "server",
                "timeout": 10,
                "browserClient": None,
            },
        )
        safe_observation_request = client.get("/_marimo-studio/observations")
        activated = client.patch(
            "/_marimo-studio/views/executive/activate",
            headers={**headers, "Marimo-Session-Id": "s_123456"},
        )

    assert recorded.status_code == 204
    assert missing_observation_token.json()["error"] == "missing-server-token"
    assert invalid_observation_token.json()["error"] == "invalid-server-token"
    assert safe_observation_request.status_code == 405
    assert observed.json()["observations"] == [
        {
            "view": "dashboard",
            "state": "error",
            "runtime": "server",
            "revision": revision,
            "diagnostics": [],
            "client_id": "browser-client-1234",
            "runtime_instance": "runtime-instance",
            "request_id": "request-dashboard",
            "sequence": 4,
            "query": "",
        }
    ]
    assert activated.status_code == 202
    assert activated.json()["view"] == "executive"
    assert activated.json()["state"] == "reload-requested"
    assert activated.json()["transition"] == "reload"
    assert activated.json()["session_id"] == "s_123456"


def test_external_observation_uses_the_selected_browser_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    projected_sessions: list[tuple[str | None, str | None]] = []
    clients = StudioClientRegistry()
    agents = AgentCoordinator(clients)
    snapshot = SimpleNamespace(
        revision="revision-1",
        resolved=SimpleNamespace(workspace=object()),
    )

    async def snapshot_async(_view: str) -> object:
        return snapshot

    presentation: Any = SimpleNamespace(snapshot_async=snapshot_async)
    notebook_scope = NotebookScope(
        notebook=Path("analysis.py"),
        presentation=presentation,
        clients=clients,
        agents=agents,
    )
    context: Any = SimpleNamespace()

    class Provider:
        def project(
            self,
            _snapshot: object,
            _context: object,
            session_id: str | None,
            binding_id: str | None,
        ) -> object:
            projected_sessions.append((session_id, binding_id))
            return SimpleNamespace(instance=f"runtime-{session_id}")

    runtimes = cast(
        RuntimeRegistry,
        SimpleNamespace(select=lambda *_args: (Provider(), ("server",))),
    )
    sessions = cast(SessionState, SimpleNamespace(exists=lambda *_args: True))

    async def exercise() -> tuple[BrowserObservation, ...]:
        client_id = "browser-client-1234"
        await clients.connect(client_id)
        await clients.bind_session("s_123456", client_id)
        target = await clients.select_target(client_id=client_id)
        observing = asyncio.create_task(
            browser_agent.observe_views(
                context,
                notebook_scope,
                ("dashboard",),
                {"dashboard": "revision-1"},
                runtime="server",
                timeout=1,
                session_id=None,
                client_id=client_id,
                sessions=sessions,
                runtimes=runtimes,
            )
        )
        while True:
            pending = await agents.pending_operations(target, None, None)
            if pending.observations:
                break
            await asyncio.sleep(0)
        request = pending.observations[0]
        assert request.session_id == "s_123456"
        assert await agents.record(
            BrowserObservation(
                view="dashboard",
                state="ready",
                runtime="server",
                revision="revision-1",
                client_id=client_id,
                runtime_instance="runtime-s_123456",
                session_id="s_123456",
                request_id=request.request_id,
                sequence=0,
                query="",
            )
        )
        return await observing

    observations = asyncio.run(exercise())

    assert projected_sessions == [("s_123456", "s_123456")]
    assert observations[0].session_id == "s_123456"


def test_code_mode_observation_rejects_an_inactive_view(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clients = StudioClientRegistry()
    agents = AgentCoordinator(clients)
    notebook_scope = NotebookScope(
        notebook=Path("analysis.py"),
        presentation=NotebookPresentation(Path("analysis.py")),
        clients=clients,
        agents=agents,
    )
    context: Any = SimpleNamespace()
    sessions = cast(SessionState, SimpleNamespace(exists=lambda *_args: True))
    runtimes = cast(RuntimeRegistry, SimpleNamespace())

    async def exercise() -> None:
        client_id = "browser-client-1234"
        await clients.connect(client_id, "dashboard")
        await clients.bind_session("s_123456", client_id)
        target = await clients.select_target(client_id=client_id)

        with pytest.raises(AgentRequestError) as raised:
            await browser_agent.observe_views(
                context,
                notebook_scope,
                ("executive",),
                {"executive": "revision-1"},
                runtime="server",
                timeout=1,
                session_id="s_123456",
                client_id=client_id,
                allow_view_activation=False,
                sessions=sessions,
                runtimes=runtimes,
            )

        assert raised.value.code == "browser-view-not-active"
        pending = await agents.pending_operations(target, None, None)
        assert pending.observations == ()

    asyncio.run(exercise())


def test_code_mode_observation_rejects_an_active_view_changed_during_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clients = StudioClientRegistry()
    agents = AgentCoordinator(clients)
    snapshot = SimpleNamespace(
        revision="revision-1",
        resolved=SimpleNamespace(workspace=object()),
    )

    async def snapshot_async(_view: str) -> object:
        await clients.connect("browser-client-1234", "executive")
        return snapshot

    presentation: Any = SimpleNamespace(snapshot_async=snapshot_async)
    notebook_scope = NotebookScope(
        notebook=Path("analysis.py"),
        presentation=presentation,
        clients=clients,
        agents=agents,
    )
    context: Any = SimpleNamespace()
    provider = SimpleNamespace(
        project=lambda *_args: SimpleNamespace(instance="runtime-instance")
    )
    runtimes = cast(
        RuntimeRegistry,
        SimpleNamespace(select=lambda *_args: (provider, ("server",))),
    )
    sessions = cast(SessionState, SimpleNamespace(exists=lambda *_args: True))

    async def exercise() -> None:
        client_id = "browser-client-1234"
        await clients.connect(client_id, "dashboard")
        await clients.bind_session("s_123456", client_id)
        target = await clients.select_target(client_id=client_id)

        with pytest.raises(AgentRequestError) as raised:
            await browser_agent.observe_views(
                context,
                notebook_scope,
                ("dashboard",),
                {"dashboard": "revision-1"},
                runtime="server",
                timeout=1,
                session_id="s_123456",
                client_id=client_id,
                allow_view_activation=False,
                sessions=sessions,
                runtimes=runtimes,
            )

        assert raised.value.code == "browser-view-not-active"
        pending = await agents.pending_operations(target, None, None)
        assert pending.observations == ()

    asyncio.run(exercise())


def test_edit_server_runs_the_agent_handoff_analysis(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    studio = configured(notebook_path)
    app = marimo_app(studio.notebook)
    edit_mode(app)
    headers = {"Marimo-Server-Token": str(session_manager(app).skew_protection_token)}

    runtime_calls: list[dict[str, object]] = []

    async def runtime(
        *_args: object,
        **kwargs: object,
    ) -> tuple[CheckResult, ...]:
        runtime_calls.append(kwargs)
        return (CheckResult("runtime", "pass", "Notebook run completed"),)

    async def observe(
        _context: object,
        _presentation: object,
        views: tuple[str, ...],
        revisions: dict[str, str],
        **_kwargs: object,
    ) -> tuple[BrowserObservation, ...]:
        return tuple(
            BrowserObservation(
                view=view,
                runtime="server",
                revision=revisions[view],
                state="ready",
                client_id="browser-client-1234",
                runtime_instance="runtime-instance",
                session_id="s_123456",
                request_id=f"request-{view}",
                sequence=index,
                query="",
            )
            for index, view in enumerate(views)
        )

    monkeypatch.setattr(agent_api, "check_runtime_studio_isolated", runtime)
    monkeypatch.setattr(agent_api, "observe_views", observe)

    with TestClient(app) as client:
        analyzed = client.post(
            "/_marimo-studio/analyze",
            headers=headers,
            json={
                "view": "dashboard",
                "timeout": 0,
                "runtime_timeout": 75,
                "require_browser": True,
            },
        )

    assert analyzed.status_code == 200
    assert analyzed.json()["handoff_ready"] is True
    assert analyzed.json()["stages"]["browser"]["status"] == "ready"
    assert analyzed.json()["actions"] == []
    assert runtime_calls[0]["timeout"] == 75


def test_code_mode_analysis_requires_one_named_view(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    studio = configured(notebook_path)
    app = marimo_app(studio.notebook)
    edit_mode(app)
    headers = {
        "Marimo-Server-Token": str(session_manager(app).skew_protection_token),
        "Marimo-Session-Id": "s_123456",
    }
    observed: list[dict[str, object]] = []

    async def runtime(*_args: object, **_kwargs: object) -> tuple[CheckResult, ...]:
        return (CheckResult("runtime", "pass", "Notebook run completed"),)

    async def observe(
        _context: object,
        _presentation: object,
        views: tuple[str, ...],
        revisions: dict[str, str],
        **kwargs: object,
    ) -> tuple[BrowserObservation, ...]:
        observed.append(
            {
                key: value
                for key, value in kwargs.items()
                if key not in {"sessions", "runtimes"}
            }
        )
        return (
            BrowserObservation(
                view=views[0],
                runtime="server",
                revision=revisions[views[0]],
                state="ready",
                client_id="browser-client-1234",
                runtime_instance="runtime-instance",
                request_id="request-dashboard",
                sequence=1,
                session_id="s_123456",
                query="",
            ),
        )

    monkeypatch.setattr(PrivateSessionState, "exists", lambda *_args: True)
    monkeypatch.setattr(agent_api, "check_runtime_studio_isolated", runtime)
    monkeypatch.setattr(agent_api, "observe_views", observe)

    with TestClient(app) as client:
        unfocused = client.post(
            "/_marimo-studio/analyze",
            headers=headers,
            json={"timeout": 0, "require_browser": True},
        )
        focused = client.post(
            "/_marimo-studio/analyze",
            headers=headers,
            json={
                "view": "dashboard",
                "timeout": 0,
                "require_browser": True,
            },
        )

    assert unfocused.status_code == 400
    assert unfocused.json()["error"] == "focused-analysis-required"
    assert focused.status_code == 200
    assert focused.json()["handoff_ready"] is True
    assert observed == [
        {
            "runtime": "server",
            "timeout": 0.0,
            "session_id": "s_123456",
            "client_id": None,
            "allow_view_activation": False,
        }
    ]


def test_agent_analysis_rejects_unknown_request_fields(
    notebook_path: Path,
) -> None:
    studio = configured(notebook_path)
    app = marimo_app(studio.notebook)
    edit_mode(app)
    headers = {"Marimo-Server-Token": str(session_manager(app).skew_protection_token)}

    with TestClient(app) as client:
        response = client.post(
            "/_marimo-studio/analyze",
            headers=headers,
            json={"view": "dashboard", "unexpected": True},
        )

    assert response.status_code == 400
    assert response.json()["error"] == "invalid-analysis-request"


def test_agent_analysis_rejects_an_out_of_range_runtime_timeout(
    notebook_path: Path,
) -> None:
    studio = configured(notebook_path)
    app = marimo_app(studio.notebook)
    edit_mode(app)
    headers = {"Marimo-Server-Token": str(session_manager(app).skew_protection_token)}

    with TestClient(app) as client:
        response = client.post(
            "/_marimo-studio/analyze",
            headers=headers,
            json={"view": "dashboard", "runtime_timeout": 301},
        )

    assert response.status_code == 400
    assert response.json()["error"] == "invalid-analysis-request"
