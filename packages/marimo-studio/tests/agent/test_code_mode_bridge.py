"""Protect the code-mode transport boundary."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from urllib.parse import urlencode

import pytest
from starlette.types import Message, Receive, Scope, Send

from marimo_studio._compat.code_mode import (
    STUDIO_NOTEBOOK_PATH_KEY,
    STUDIO_SESSION_ID_KEY,
    attach_code_mode_session,
)
from marimo_studio._delivery.urls import (
    EDITOR_BINDING_CAPABILITY_QUERY_PARAM,
    SERVER_INSTANCE_QUERY_PARAM,
)
from marimo_studio._server import editor_bridge
from marimo_studio._server import middleware as studio_middleware
from marimo_studio._server.ports import ServerAdapters, SessionOwner
from marimo_studio._server.presentation.admission import (
    NATIVE_SESSION_ADMISSION_SCOPE_KEY,
    NativeSessionAdmission,
)
from marimo_studio._server.server_instance import server_instance_id
from marimo_studio._server.studio.editor_capability import (
    editor_binding_capability,
)

_SERVER_TOKEN = "server-token"


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
    monkeypatch.setattr(editor_bridge, "discover_studio", lambda _path: None)
    middleware = studio_middleware.PresentationMiddleware(
        downstream,
        lambda: _adapters(location),
    )
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
        STUDIO_NOTEBOOK_PATH_KEY: str(notebook_path.resolve()),
        STUDIO_SESSION_ID_KEY: "s_123456",
    }


def test_editor_transport_binds_its_marimo_session_to_the_studio_tab(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    delegated: list[Scope] = []

    async def downstream(scope: Scope, receive: Receive, send: Send) -> None:
        del receive, send
        delegated.append(scope)

    location = SimpleNamespace(notebook=notebook_path)
    monkeypatch.setattr(editor_bridge, "native_editor_target", lambda _relative: "/ws")
    middleware = studio_middleware.PresentationMiddleware(
        downstream,
        lambda: _adapters(location),
    )
    scope = _websocket_scope(("edit",), notebook_path)

    async def receive() -> Message:
        return {"type": "websocket.connect"}

    async def send(_message: Message) -> None:
        return None

    async def exercise() -> None:
        await middleware(scope, receive, send)
        clients = middleware._notebooks.get(notebook_path).clients
        admission = delegated[0][NATIVE_SESSION_ADMISSION_SCOPE_KEY]
        assert isinstance(admission, NativeSessionAdmission)
        assert admission.on_accept is not None
        admission.on_accept(object())
        assert await clients.connect_stream("browser-client-1234", 1)
        assert await clients.session_for_client("browser-client-1234") == "s_123456"
        assert admission.mode == "fresh"

    asyncio.run(exercise())


@pytest.mark.parametrize("target", ("/ws_sync", "/sse"))
def test_native_editor_transports_require_the_binding_capability(
    notebook_path: Path,
    target: str,
) -> None:
    delegated: list[Scope] = []

    async def downstream(scope: Scope, receive: Receive, send: Send) -> None:
        del receive, send
        delegated.append(scope)

    middleware = studio_middleware.PresentationMiddleware(
        downstream,
        lambda: _adapters(SimpleNamespace(notebook=notebook_path)),
    )
    scope = _websocket_scope(("edit",), notebook_path, target=target)
    scope["query_string"] = b""
    sent: list[Message] = []

    async def receive() -> Message:
        return {"type": "websocket.connect"}

    async def send(message: Message) -> None:
        sent.append(message)

    asyncio.run(middleware(scope, receive, send))

    assert delegated == []
    assert sent == [
        {
            "type": "websocket.close",
            "code": 1008,
            "reason": "The editor binding capability is invalid.",
        }
    ]


def test_editor_lsp_websocket_keeps_native_auth_routing(notebook_path: Path) -> None:
    delegated: list[Scope] = []

    async def downstream(scope: Scope, receive: Receive, send: Send) -> None:
        del receive, send
        delegated.append(scope)

    middleware = studio_middleware.PresentationMiddleware(
        downstream,
        lambda: _adapters(SimpleNamespace(notebook=notebook_path)),
    )
    scope = _websocket_scope(
        ("edit",),
        notebook_path,
        target="/lsp/pylsp",
    )
    scope["query_string"] = b"access_token=native-token"

    async def receive() -> Message:
        return {"type": "websocket.connect"}

    async def send(_message: Message) -> None:
        return None

    asyncio.run(middleware(scope, receive, send))

    assert [item["path"] for item in delegated] == ["/lsp/pylsp"]


def test_editor_transport_requires_edit_access_before_binding_a_session(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def downstream(scope: Scope, receive: Receive, send: Send) -> None:
        del scope, receive, send

    location = SimpleNamespace(notebook=notebook_path)
    monkeypatch.setattr(editor_bridge, "native_editor_target", lambda _relative: "/ws")
    middleware = studio_middleware.PresentationMiddleware(
        downstream,
        lambda: _adapters(location),
    )
    scope = _websocket_scope(("read",), notebook_path)

    async def receive() -> Message:
        return {"type": "websocket.connect"}

    async def send(_message: Message) -> None:
        return None

    asyncio.run(middleware(scope, receive, send))

    assert not middleware._notebooks.contains(notebook_path)


def test_stale_editor_transport_does_not_bind_a_studio_client(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def downstream(scope: Scope, receive: Receive, send: Send) -> None:
        del scope, receive, send

    location = SimpleNamespace(notebook=notebook_path)
    monkeypatch.setattr(editor_bridge, "native_editor_target", lambda _relative: "/ws")
    middleware = studio_middleware.PresentationMiddleware(
        downstream,
        lambda: _adapters(location),
    )
    scope = _websocket_scope(
        ("edit",),
        notebook_path,
        server_instance="stale-server",
    )

    async def receive() -> Message:
        return {"type": "websocket.connect"}

    async def send(_message: Message) -> None:
        return None

    asyncio.run(middleware(scope, receive, send))

    assert not middleware._notebooks.contains(notebook_path)


def _adapters(location: Any) -> ServerAdapters:
    async def resolve_location(_connection: object) -> object:
        return location

    notebook = cast(Path, location.notebook)
    context = SimpleNamespace(
        base_url="",
        file_key=str(notebook),
        mode="edit",
        notebook=notebook,
        server_token=_SERVER_TOKEN,
    )
    server = SimpleNamespace(
        base_url=lambda _scope: "",
        relative_path=lambda scope, _base: scope["path"],
        mode=lambda _scope: "edit",
        location=resolve_location,
        context=lambda _location: context,
    )
    sessions = SimpleNamespace(
        is_session_id=lambda value: value == "s_123456",
        owner=lambda _context, _session_id: SessionOwner("unclaimed", None),
        editor_identity=lambda _context, _session_id: None,
        retry_startup=lambda _context, _session_id, _claim: False,
        retire=lambda _context, _session_id: False,
    )
    return cast(
        ServerAdapters,
        SimpleNamespace(
            server=server,
            editor_runtime=SimpleNamespace(),
            document_transactions=SimpleNamespace(),
            session_state=sessions,
            sessions=SimpleNamespace(claim_editor_lifetime=lambda _context: object()),
            persistence=SimpleNamespace(enable=lambda _location: None),
            code_mode=SimpleNamespace(attach_session=attach_code_mode_session),
            browser=SimpleNamespace(),
        ),
    )


def _websocket_scope(
    scopes: tuple[str, ...],
    notebook: Path,
    *,
    server_instance: str = server_instance_id(_SERVER_TOKEN),
    capability: str | None = None,
    target: str = "/ws",
) -> Scope:
    binding_capability = capability or editor_binding_capability(
        _SERVER_TOKEN,
        str(notebook),
        "",
        "browser-client-1234",
        "s_123456",
    )
    return {
        "type": "websocket",
        "scheme": "ws",
        "path": f"/_marimo-studio/editor{target}",
        "raw_path": f"/_marimo-studio/editor{target}".encode(),
        "root_path": "",
        "query_string": urlencode(
            {
                "marimo_studio_client": "browser-client-1234",
                "session_id": "s_123456",
                SERVER_INSTANCE_QUERY_PARAM: server_instance,
                EDITOR_BINDING_CAPABILITY_QUERY_PARAM: binding_capability,
            }
        ).encode(),
        "headers": [],
        "server": ("testserver", 80),
        "client": ("testclient", 1),
        "subprotocols": [],
        "app": SimpleNamespace(),
        "auth": SimpleNamespace(scopes=scopes),
    }
