from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from starlette.testclient import TestClient

from marimo_studio._compat.server.session_state import PrivateSessionState
from marimo_studio._server.agent import browser as browser_agent
from marimo_studio._server.agent.clients import StudioClientRegistry
from marimo_studio._server.agent.coordinator import AgentCoordinator
from marimo_studio._server.agent.events import ObservationRequest
from marimo_studio._server.notebook_scope import NotebookScope
from marimo_studio._server.ports import SessionState
from marimo_studio._server.presentation.service import NotebookPresentation
from marimo_studio._server.runtime.catalog import RuntimeRegistry
from marimo_studio._validation.evidence import BrowserObservation
from marimo_studio.errors import AgentRequestError

from ..agent_support import agent_edit_server
from ..client_test_support import bind_native_session
from ..helpers import ready_runtime_status


def test_browser_observation_endpoint_rejects_an_oversized_timeout(
    notebook_path: Path,
) -> None:
    server = agent_edit_server(notebook_path)
    revision = (
        NotebookPresentation(server.studio.notebook).snapshot("dashboard").revision
    )

    with TestClient(server.app) as client:
        response = client.post(
            "/_marimo-studio/observations",
            headers=server.headers,
            json={
                "schema": 1,
                "views": ["dashboard"],
                "revisions": {"dashboard": revision},
                "runtime": "server",
                "timeout": 10**1000,
                "browserClient": None,
            },
        )

    assert response.status_code == 400
    assert response.json()["error"] == "invalid-browser-timeout"


def test_authenticated_agent_connection_returns_the_mutation_token(
    notebook_path: Path,
) -> None:
    server = agent_edit_server(notebook_path, token="test-token")

    with TestClient(server.app) as client:
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
        "notebook": str(server.studio.notebook),
        "server_token": server.headers["Marimo-Server-Token"],
    }


def test_edit_workspace_validates_and_records_browser_observations(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server = agent_edit_server(notebook_path)
    revision = (
        NotebookPresentation(server.studio.notebook).snapshot("dashboard").revision
    )
    diagnostic = {
        "code": "runtime-disconnected",
        "severity": "error",
        "message": "The runtime disconnected.",
        "hint": "Reconnect the notebook runtime.",
        "view": "dashboard",
        "scope": "runtime",
    }
    session_id = "s_view01"

    def observation_payload(current_session: str | None) -> dict[str, object]:
        return {
            "schema": 1,
            "view": "dashboard",
            "runtime": "server",
            "revision": revision,
            "state": "error",
            "diagnostics": [diagnostic],
            "clientId": "browser-client-1234",
            "runtimeInstance": "runtime-instance",
            "sessionId": current_session,
            "requestId": "request-dashboard",
            "sequence": 4,
            "query": "",
            "projectionInstances": [],
            "runtimeStatus": {
                "runtime": "server",
                "view": "dashboard",
                "revision": revision,
                "sessionId": current_session,
                "current": {
                    "phase": "failed",
                    "diagnostics": [diagnostic],
                },
                "transitions": [
                    {
                        "sequence": 0,
                        "observedAt": 1_000,
                        "revision": revision,
                        "sessionId": current_session,
                        "phase": "failed",
                        "diagnostics": [diagnostic],
                        "diagnosticsTruncated": False,
                    }
                ],
            },
        }

    async def record(
        _coordinator: AgentCoordinator,
        observation: BrowserObservation,
    ) -> bool:
        return observation.request_id == "request-dashboard"

    validated: list[str] = []

    def validate(observation: BrowserObservation, *_args: object) -> None:
        validated.append(observation.view)

    monkeypatch.setattr(AgentCoordinator, "record", record)
    monkeypatch.setattr(browser_agent, "validate_projection_evidence", validate)

    async def no_live_cells(*_args: object, **_kwargs: object) -> None:
        return None

    monkeypatch.setattr(
        PrivateSessionState,
        "live_cells",
        no_live_cells,
    )

    with TestClient(server.app) as client:
        missing_session = client.put(
            "/_marimo-studio/views/dashboard/observation",
            headers=server.headers,
            json=observation_payload(None),
        )
        recorded = client.put(
            "/_marimo-studio/views/dashboard/observation",
            headers=server.headers,
            json=observation_payload(session_id),
        )

    assert missing_session.status_code == 400
    assert missing_session.json()["error"] == "invalid-browser-observation"
    assert recorded.status_code == 204
    assert validated == ["dashboard"]


def test_edit_workspace_requests_browser_observations(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server = agent_edit_server(notebook_path)
    revision = (
        NotebookPresentation(server.studio.notebook).snapshot("dashboard").revision
    )
    session_id = "s_view01"

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
                session_id=session_id,
                request_id="request-dashboard",
                sequence=4,
                query="",
            ),
        )

    monkeypatch.setattr(browser_agent, "observe_views", observe)

    with TestClient(server.app) as client:
        observed = client.post(
            "/_marimo-studio/observations",
            headers=server.headers,
            json={
                "schema": 1,
                "views": ["dashboard"],
                "revisions": {"dashboard": revision},
                "runtime": "server",
                "timeout": 10,
                "browserClient": None,
            },
        )

    assert observed.json()["observations"] == [
        {
            "view": "dashboard",
            "state": "error",
            "runtime": "server",
            "revision": revision,
            "diagnostics": [],
            "client_id": "browser-client-1234",
            "runtime_instance": "runtime-instance",
            "session_id": session_id,
            "request_id": "request-dashboard",
            "sequence": 4,
            "query": "",
        }
    ]


def test_show_http_rejects_mixed_session_and_browser_selectors(
    notebook_path: Path,
) -> None:
    server = agent_edit_server(notebook_path)

    with TestClient(server.app) as client:
        mixed_activation = client.patch(
            "/_marimo-studio/views/dashboard/show",
            headers={**server.headers, "Marimo-Session-Id": "s_123456"},
            json={"schema": 1, "browser_client": "browser-client-1234"},
        )

    assert mixed_activation.status_code == 400
    assert mixed_activation.json()["error"] == "invalid-show-request"
    assert mixed_activation.json()["field"] == "browser_client"


def test_browser_mutation_http_rejects_noncanonical_records(
    notebook_path: Path,
) -> None:
    server = agent_edit_server(notebook_path)
    cases = (
        (
            "PATCH",
            "/_marimo-studio/views/dashboard/show",
            {},
            "invalid-show-request",
            "request",
        ),
        (
            "POST",
            "/_marimo-studio/activations/1/ack",
            {
                "schema": True,
                "clientId": "browser-client-1234",
                "view": "dashboard",
            },
            "invalid-activation-ack",
            None,
        ),
        (
            "POST",
            "/_marimo-studio/active-view-handoffs/handoff-operation-1",
            {
                "schema": True,
                "clientId": "browser-client-1234",
                "fromView": "dashboard",
                "toView": "report",
            },
            "invalid-active-view-handoff",
            None,
        ),
    )

    with TestClient(server.app) as client:
        for method, path, payload, error, field in cases:
            response = client.request(
                method,
                path,
                headers=server.headers,
                json=payload,
            )
            assert response.status_code == 400, path
            assert response.json()["error"] == error, path
            if field is not None:
                assert response.json()["field"] == field, path


def test_external_observation_uses_the_selected_browser_session() -> None:
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

    async def project(
        _snapshot: object,
        _context: object,
        _runtime: str,
        session_id: str | None,
        binding_id: str | None,
        presentation_session_id: str | None,
        runtime_session_id: str | None,
        *,
        client_id: str | None = None,
    ) -> object:
        assert presentation_session_id == session_id
        assert runtime_session_id == session_id
        projected_sessions.append((session_id, binding_id))
        return SimpleNamespace(instance=f"runtime-{session_id}")

    runtimes = cast(
        RuntimeRegistry,
        SimpleNamespace(project=project),
    )
    sessions = cast(SessionState, SimpleNamespace(exists=lambda *_args: True))
    requested = asyncio.Event()
    activation_requested = asyncio.Event()
    observation_requests: list[ObservationRequest] = []
    request_observation = agents.request_observation
    activate = agents.activate

    async def capture_activation(*args: Any, **kwargs: Any):
        activation = await activate(*args, **kwargs)
        activation_requested.set()
        return activation

    async def capture_observation_request(*args: Any, **kwargs: Any):
        request = await request_observation(*args, **kwargs)
        observation_requests.append(request)
        requested.set()
        return request

    cast(Any, agents).request_observation = capture_observation_request
    cast(Any, agents).activate = capture_activation

    async def exercise() -> tuple[BrowserObservation, ...]:
        client_id = "browser-client-1234"
        assert await clients.connect_stream(client_id, 1, "overview")
        await bind_native_session(clients, "s_123456", client_id)
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
        await asyncio.wait_for(activation_requested.wait(), timeout=1)
        pending = await agents.pending_operations(target, None, None)
        assert pending.activation is not None
        outcome = await agents.acknowledge_activation(
            client_id,
            pending.activation.generation,
            "dashboard",
        )
        assert outcome.value == "applied"
        await asyncio.wait_for(requested.wait(), timeout=1)
        request = observation_requests[0]
        assert request.binding_session_id == "s_123456"
        assert request.runtime_session_id == "s_123456"
        assert request.active_view_generation is not None
        assert request.active_view_generation > target.active_view_generation
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
                runtime_status=ready_runtime_status(
                    "dashboard",
                    "revision-1",
                ),
            )
        )
        return await observing

    observations = asyncio.run(exercise())

    assert projected_sessions == [("s_123456", "s_123456")]
    assert observations[0].session_id == "s_123456"


def test_code_mode_observation_rejects_an_inactive_view() -> None:
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
        assert await clients.connect_stream(client_id, 1, "dashboard")
        await bind_native_session(clients, "s_123456", client_id)
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


def test_code_mode_observation_rejects_an_active_view_changed_during_snapshot() -> None:
    clients = StudioClientRegistry()
    agents = AgentCoordinator(clients)
    snapshot = SimpleNamespace(
        revision="revision-1",
        resolved=SimpleNamespace(workspace=object()),
    )

    async def snapshot_async(_view: str) -> object:
        assert await clients.connect_stream("browser-client-1234", 1, "executive")
        return snapshot

    presentation: Any = SimpleNamespace(snapshot_async=snapshot_async)
    notebook_scope = NotebookScope(
        notebook=Path("analysis.py"),
        presentation=presentation,
        clients=clients,
        agents=agents,
    )
    context: Any = SimpleNamespace()

    async def project(*_args: object, client_id: str | None = None) -> object:
        return SimpleNamespace(instance="runtime-instance")

    runtimes = cast(
        RuntimeRegistry,
        SimpleNamespace(project=project),
    )
    sessions = cast(SessionState, SimpleNamespace(exists=lambda *_args: True))

    async def exercise() -> None:
        client_id = "browser-client-1234"
        assert await clients.connect_stream(client_id, 1, "dashboard")
        await bind_native_session(clients, "s_123456", client_id)
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
