from __future__ import annotations

import asyncio
import threading
from collections.abc import AsyncIterator
from pathlib import Path
from urllib.parse import urlencode

import pytest
from starlette.testclient import TestClient
from starlette.types import Message
from starlette.websockets import WebSocket, WebSocketDisconnect

from marimo_studio._delivery.urls import (
    SERVER_INSTANCE_QUERY_PARAM,
    STUDIO_CLIENT_QUERY_PARAM,
    WORKSPACE_EVENTS_CAPABILITY_QUERY_PARAM,
    WORKSPACE_STREAM_QUERY_PARAM,
)
from marimo_studio._server.event_socket import (
    EVENT_SOCKET_SCOPE_KEY,
    EventSocketResponse,
    is_event_socket_route,
)
from marimo_studio._server.server_instance import server_instance_id
from marimo_studio._server.streaming import StreamingResponseCleanupError

from ..app_helpers import configured as _configured
from ..app_helpers import edit_mode as _edit_mode
from ..app_helpers import marimo_app as _marimo_app
from ..app_helpers import session_manager as _session_manager


def test_view_event_socket_sends_the_ready_baseline(notebook_path: Path) -> None:
    studio = _configured(notebook_path)
    app = _marimo_app(studio.notebook)
    _edit_mode(app)

    with TestClient(app) as client:
        instance = server_instance_id(str(_session_manager(app).skew_protection_token))
        events = (
            "/_marimo-studio/views/dashboard/dev/events"
            f"?{SERVER_INSTANCE_QUERY_PARAM}={instance}"
        )
        with client.websocket_connect(events) as socket:
            ready = socket.receive_json()
        plain = client.get(events)

    assert ready["event"] == "ready"
    assert ready["data"]["view"] == "dashboard"
    assert plain.status_code == 426
    assert plain.json()["error"] == "websocket-required"


def test_closing_the_event_socket_releases_its_event_owner(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    studio = _configured(notebook_path)
    app = _marimo_app(studio.notebook)
    _edit_mode(app)
    released = threading.Event()

    async def events(*_args: object, **_options: object) -> AsyncIterator[str]:
        try:
            yield '{"event":"ready","data":{}}'
            await asyncio.Future()
        finally:
            released.set()

    monkeypatch.setattr("marimo_studio._server.support.change_events", events)
    with TestClient(app) as client:
        instance = server_instance_id(str(_session_manager(app).skew_protection_token))
        with client.websocket_connect(
            "/_marimo-studio/views/dashboard/dev/events"
            f"?{SERVER_INSTANCE_QUERY_PARAM}={instance}"
        ) as socket:
            assert socket.receive_json()["event"] == "ready"
        assert released.wait(timeout=5)


def test_rejected_event_socket_closes_with_the_route_status(
    notebook_path: Path,
) -> None:
    studio = _configured(notebook_path)
    app = _marimo_app(studio.notebook)
    _edit_mode(app)

    with TestClient(app) as client:
        query = urlencode(
            {
                SERVER_INSTANCE_QUERY_PARAM: server_instance_id(
                    str(_session_manager(app).skew_protection_token)
                ),
                STUDIO_CLIENT_QUERY_PARAM: "browser-client-1234",
                WORKSPACE_STREAM_QUERY_PARAM: "1",
                WORKSPACE_EVENTS_CAPABILITY_QUERY_PARAM: "forged",
            }
        )
        with (
            client.websocket_connect(f"/_marimo-studio/dev/events?{query}") as socket,
            pytest.raises(WebSocketDisconnect) as closed,
        ):
            socket.receive_text()

    assert closed.value.code == 4403


def test_event_socket_reports_owner_cleanup_failure_after_client_disconnect() -> None:
    async def events() -> AsyncIterator[str]:
        try:
            yield '{"event":"ready","data":{}}'
            await asyncio.Future()
        finally:
            raise RuntimeError("event owner cleanup failed")

    async def exercise() -> list[Message]:
        incoming: asyncio.Queue[Message] = asyncio.Queue()
        incoming.put_nowait({"type": "websocket.connect"})
        sent: list[Message] = []

        async def send(message: Message) -> None:
            sent.append(message)
            if message["type"] == "websocket.send":
                incoming.put_nowait({"type": "websocket.disconnect", "code": 1001})

        scope = {"type": "websocket", "path": "/", "headers": [], "query_string": b""}
        socket = WebSocket(scope, incoming.get, send)
        with pytest.raises(StreamingResponseCleanupError, match="cleanup failed"):
            await EventSocketResponse(events())(
                {**scope, EVENT_SOCKET_SCOPE_KEY: socket},
                incoming.get,
                send,
            )
        return sent

    sent = asyncio.run(exercise())
    assert [message["type"] for message in sent] == [
        "websocket.accept",
        "websocket.send",
    ]


@pytest.mark.parametrize(
    ("relative", "expected"),
    [
        ("/_marimo-studio/dev/events", True),
        ("/_marimo-studio/views/dashboard/dev/events", True),
        ("/_marimo-studio/presentation/d.cap/_marimo-studio/dev/events", True),
        ("/_marimo-studio-extra/dev/events", False),
        ("/_marimo-studio/dev/events/more", False),
    ],
)
def test_event_socket_routes_stay_inside_the_studio_namespace(
    relative: str, expected: bool
) -> None:
    assert is_event_socket_route(relative) is expected
