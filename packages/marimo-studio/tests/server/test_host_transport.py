from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from urllib.parse import urlencode

import pytest
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from marimo_studio._server.host_integration import HostEntryHandler
from marimo_studio._server.notebook_scope import NotebookScopeRegistry
from marimo_studio._server.ports import (
    EditorSessionIdentity,
    ServerGateway,
    SessionOwner,
    SessionState,
)
from marimo_studio._server.presentation.admission import (
    NATIVE_SESSION_ADMISSION_SCOPE_KEY,
    NativeSessionAdmission,
)
from marimo_studio._server.records import ServerContext
from marimo_studio._server.route_policy import StudioRoutePolicy
from marimo_studio._server.security import SecurityPolicy
from marimo_studio._server.studio.session_handoff import (
    HostSessionTicket,
)

_SESSION_ID = "s_123456"


@dataclass
class _Sessions:
    claim: object = field(default_factory=object)
    identity: EditorSessionIdentity | None = None
    released: bool = False

    def owner(self, _context: ServerContext, _session_id: str) -> SessionOwner:
        return SessionOwner("current", self.claim)

    def editor_identity(
        self,
        _context: ServerContext,
        _session_id: str,
    ) -> EditorSessionIdentity | None:
        return self.identity

    def release_editor_identity(
        self,
        _context: ServerContext,
        _session_id: str,
    ) -> bool:
        self.released = True
        self.identity = None
        return True

    @staticmethod
    def is_session_id(value: object) -> bool:
        return isinstance(value, str) and value.startswith("s_")

    @staticmethod
    def matches_creation_query(*_args: object) -> bool:
        return True


class _Gateway:
    def __init__(self, context: ServerContext) -> None:
        self._context = context

    async def location(self, _request: object) -> object:
        return SimpleNamespace(notebook=self._context.notebook)

    def context(self, _location: object) -> ServerContext:
        return self._context


class _TransportHarness:
    def __init__(self, notebook: Path) -> None:
        self.context = cast(
            ServerContext,
            SimpleNamespace(
                base_url="",
                file_key=str(notebook),
                mode="edit",
                notebook=notebook,
                server_token="server-token",
            ),
        )
        self.sessions = _Sessions()
        self.notebooks = NotebookScopeRegistry()
        self.handler = HostEntryHandler(
            StudioRoutePolicy(edit_root="marimo"),
            SecurityPolicy(),
            cast(ServerGateway, _Gateway(self.context)),
            cast(SessionState, self.sessions),
            self.notebooks,
        )
        self.sent: list[Message] = []

    async def bind_studio(self) -> None:
        clients = self.notebooks.get(self.context.notebook).clients
        lease = await clients.bind_session(_SESSION_ID, "browser-client")
        assert lease is not None
        assert clients.accept_session_binding(lease, self.sessions.claim) is not None

    async def authorize(self) -> None:
        capability = HostSessionTicket.issue(
            self.context,
            _SESSION_ID,
            (),
        ).capability
        handled = await self.handler.serve(
            _unreachable,
            _scope(
                "/",
                query=urlencode(
                    {
                        "session_id": _SESSION_ID,
                        "marimo_studio_handoff": capability,
                    }
                ),
            ),
            _receive,
            self.send,
            relative="/",
            mode="edit",
        )
        assert handled
        self.sent.clear()

    async def transport(
        self,
        path: str,
        app: ASGIApp,
        *,
        websocket: bool = False,
    ) -> bool:
        return await self.handler.serve(
            app,
            (
                _websocket_scope(path, query=f"session_id={_SESSION_ID}")
                if websocket
                else _scope(path, query=f"session_id={_SESSION_ID}")
            ),
            _receive,
            self.send,
            relative=path,
            mode="edit",
        )

    async def send(self, message: Message) -> None:
        self.sent.append(message)

    async def close(self) -> None:
        self.handler.close()
        await self.notebooks.close()


def _scope(path: str, *, query: str) -> Scope:
    return cast(
        Scope,
        {
            "type": "http",
            "method": "GET",
            "scheme": "http",
            "path": path,
            "raw_path": path.encode(),
            "root_path": "",
            "query_string": query.encode(),
            "headers": [],
            "auth": SimpleNamespace(scopes=("read", "edit")),
            "server": ("testserver", 80),
            "client": ("testclient", 1),
        },
    )


def _websocket_scope(path: str, *, query: str) -> Scope:
    scope = dict(_scope(path, query=query))
    scope.update(
        {
            "type": "websocket",
            "scheme": "ws",
            "subprotocols": [],
        }
    )
    scope.pop("method")
    return cast(Scope, scope)


async def _receive() -> Message:
    return {"type": "http.request", "body": b"", "more_body": False}


async def _unreachable(scope: Scope, receive: Receive, send: Send) -> None:
    del scope, receive, send
    raise AssertionError("Request unexpectedly reached Marimo")


def test_studio_owned_native_transport_requires_handoff(
    notebook_path: Path,
) -> None:
    async def exercise() -> None:
        harness = _TransportHarness(notebook_path)
        harness.sessions.identity = EditorSessionIdentity("client", "capability")
        try:
            assert await harness.transport("/sse", _unreachable)
            assert harness.sent[0]["status"] == 403
        finally:
            await harness.close()

    asyncio.run(exercise())


@pytest.mark.parametrize("replace_claim", [False, True])
def test_unsettled_admission_restores_only_the_same_session(
    notebook_path: Path,
    replace_claim: bool,
) -> None:
    async def exercise() -> None:
        harness = _TransportHarness(notebook_path)
        await harness.bind_studio()
        await harness.authorize()

        async def downstream(scope: Scope, receive: Receive, send: Send) -> None:
            del scope, receive, send
            if replace_claim:
                harness.sessions.claim = object()

        try:
            assert await harness.transport("/sse", downstream)
            restored = await harness.notebooks.get(
                notebook_path
            ).clients.binding_for_session(_SESSION_ID)
            if replace_claim:
                assert restored is None
            else:
                assert restored is not None
                assert restored.client_id == "browser-client"
        finally:
            await harness.close()

    asyncio.run(exercise())


def test_accepted_admission_commits_the_native_session_transfer(
    notebook_path: Path,
) -> None:
    async def exercise() -> None:
        harness = _TransportHarness(notebook_path)
        await harness.bind_studio()
        await harness.authorize()

        async def downstream(scope: Scope, receive: Receive, send: Send) -> None:
            del receive, send
            admission = cast(
                NativeSessionAdmission,
                scope[NATIVE_SESSION_ADMISSION_SCOPE_KEY],
            )
            assert admission.on_accept is not None
            admission.settled = True
            admission.on_accept(harness.sessions.claim)

        try:
            assert await harness.transport("/sse", downstream)
            assert harness.sessions.released
            assert (
                await harness.notebooks.get(notebook_path).clients.binding_for_session(
                    _SESSION_ID
                )
                is None
            )
            assert not harness.handler.session_active(harness.context, _SESSION_ID)
        finally:
            await harness.close()

    asyncio.run(exercise())


def test_sync_transport_cannot_consume_the_handoff(notebook_path: Path) -> None:
    async def exercise() -> None:
        harness = _TransportHarness(notebook_path)
        harness.sessions.identity = EditorSessionIdentity("client", "capability")
        await harness.authorize()
        reached_main = False

        async def downstream(scope: Scope, receive: Receive, send: Send) -> None:
            del scope, receive, send
            nonlocal reached_main
            reached_main = True

        try:
            assert await harness.transport("/ws_sync", _unreachable, websocket=True)
            assert harness.sent[0] == {
                "type": "websocket.close",
                "code": 1008,
                "reason": "The host session handoff is not authorized.",
            }
            harness.sent.clear()
            assert await harness.transport("/sse", downstream)
            assert reached_main
        finally:
            await harness.close()

    asyncio.run(exercise())
