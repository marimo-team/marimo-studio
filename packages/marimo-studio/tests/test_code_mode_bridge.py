from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlencode

import pytest
from starlette.types import Message, Receive, Scope, Send

from marimo_studio._compat.code_mode import (
    STUDIO_SESSION_ID_KEY,
)
from marimo_studio._server import editor_bridge
from marimo_studio._server import middleware as studio_middleware


@pytest.mark.parametrize(
    "path,delegated",
    [
        ("/api/ai/chat", "/api/ai/chat"),
        ("/_marimo-studio/editor/api/ai/chat", "/api/ai/chat"),
        ("/api/kernel/execute", "/api/kernel/execute"),
    ],
)
def test_code_mode_routes_receive_the_calling_session(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    path: str,
    delegated: str,
) -> None:
    captured: list[Scope] = []

    async def downstream(scope: Scope, receive: Receive, send: Send) -> None:
        del receive
        captured.append(scope)
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    location = SimpleNamespace(notebook=notebook_path)
    monkeypatch.setattr(studio_middleware, "server_base_url", lambda _scope: "")
    monkeypatch.setattr(
        studio_middleware,
        "relative_request_path",
        lambda scope, _base: scope["path"],
    )
    monkeypatch.setattr(studio_middleware, "server_mode", lambda _scope: "edit")
    monkeypatch.setattr(editor_bridge, "server_location", lambda _request: location)
    monkeypatch.setattr(editor_bridge, "discover_studio", lambda _path: None)
    middleware = studio_middleware.PresentationMiddleware(downstream)
    scope: Scope = {
        "type": "http",
        "method": "POST",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "root_path": "",
        "query_string": b"",
        "headers": [(b"marimo-session-id", b"s_123456")],
        "server": ("testserver", 80),
        "client": ("testclient", 1),
        "app": SimpleNamespace(),
    }

    async def receive() -> Message:
        return {"type": "http.request", "body": b"", "more_body": False}

    sent: list[Message] = []

    async def send(message: Message) -> None:
        sent.append(message)

    asyncio.run(middleware(scope, receive, send))

    assert captured[0]["path"] == delegated
    assert captured[0]["meta"] == {
        STUDIO_SESSION_ID_KEY: "s_123456",
    }


def test_editor_transport_binds_its_marimo_session_to_the_studio_tab(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def downstream(scope: Scope, receive: Receive, send: Send) -> None:
        del scope, receive, send

    location = SimpleNamespace(notebook=notebook_path)
    monkeypatch.setattr(studio_middleware, "server_base_url", lambda _scope: "")
    monkeypatch.setattr(
        studio_middleware,
        "relative_request_path",
        lambda scope, _base: scope["path"],
    )
    monkeypatch.setattr(studio_middleware, "server_mode", lambda _scope: "edit")
    monkeypatch.setattr(editor_bridge, "native_editor_target", lambda _relative: "/ws")
    monkeypatch.setattr(editor_bridge, "server_location", lambda _connection: location)
    middleware = studio_middleware.PresentationMiddleware(downstream)
    scope = _websocket_scope(("edit",))

    async def receive() -> Message:
        return {"type": "websocket.connect"}

    async def send(_message: Message) -> None:
        return None

    async def exercise() -> None:
        await middleware(scope, receive, send)
        clients = middleware._notebooks.get(notebook_path).clients
        await clients.connect("browser-client-1234")
        assert await clients.session_for_client("browser-client-1234") == "s_123456"

    asyncio.run(exercise())


def test_editor_transport_requires_edit_access_before_binding_a_session(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def downstream(scope: Scope, receive: Receive, send: Send) -> None:
        del scope, receive, send

    location = SimpleNamespace(notebook=notebook_path)
    monkeypatch.setattr(studio_middleware, "server_base_url", lambda _scope: "")
    monkeypatch.setattr(
        studio_middleware,
        "relative_request_path",
        lambda scope, _base: scope["path"],
    )
    monkeypatch.setattr(studio_middleware, "server_mode", lambda _scope: "edit")
    monkeypatch.setattr(editor_bridge, "native_editor_target", lambda _relative: "/ws")
    monkeypatch.setattr(editor_bridge, "server_location", lambda _connection: location)
    middleware = studio_middleware.PresentationMiddleware(downstream)
    scope = _websocket_scope(("read",))

    async def receive() -> Message:
        return {"type": "websocket.connect"}

    async def send(_message: Message) -> None:
        return None

    asyncio.run(middleware(scope, receive, send))

    assert not middleware._notebooks.contains(notebook_path)


def _websocket_scope(scopes: tuple[str, ...]) -> Scope:
    return {
        "type": "websocket",
        "scheme": "ws",
        "path": "/_marimo-studio/editor/ws",
        "raw_path": b"/_marimo-studio/editor/ws",
        "root_path": "",
        "query_string": urlencode(
            {
                "marimo_studio_client": "browser-client-1234",
                "session_id": "s_123456",
            }
        ).encode(),
        "headers": [],
        "server": ("testserver", 80),
        "client": ("testclient", 1),
        "subprotocols": [],
        "app": SimpleNamespace(),
        "auth": SimpleNamespace(scopes=scopes),
    }
