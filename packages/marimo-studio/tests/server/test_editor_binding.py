from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from urllib.parse import urlencode

from starlette.requests import Request

from marimo_studio._server.agent.clients import StudioClientRegistry
from marimo_studio._server.editor_bridge import _bind_editor_session
from marimo_studio._server.ports import (
    EditorSessionIdentity,
    SessionOwner,
    SessionState,
)
from marimo_studio._server.presentation.admission import NativeSessionAdmission
from marimo_studio._server.records import ServerContext
from marimo_studio._server.server_instance import server_instance_id
from marimo_studio._server.studio.editor_capability import editor_binding_capability

_CLIENT_ID = "browser-client-1234"
_SESSION_ID = "s_123456"
_LIFETIME_OWNER = object()


class _Sessions:
    def __init__(self) -> None:
        self.claim: object | None = None
        self.identity: EditorSessionIdentity | None = None
        self.retried: list[object] = []
        self.state = "unclaimed"

    @staticmethod
    def is_session_id(value: object) -> bool:
        return isinstance(value, str) and value.startswith("s_")

    def owner(self, _context: ServerContext, _session_id: str) -> SessionOwner:
        return SessionOwner(cast(Any, self.state), self.claim)

    def editor_identity(
        self,
        _context: ServerContext,
        _session_id: str,
    ) -> EditorSessionIdentity | None:
        return self.identity

    def retry_startup(
        self,
        _context: ServerContext,
        _session_id: str,
        claim: object,
    ) -> bool:
        self.retried.append(claim)
        return True


def _context() -> ServerContext:
    return cast(
        ServerContext,
        SimpleNamespace(
            base_url="",
            file_key="notebook.py",
            mode="edit",
            notebook=Path("/workspace/notebook.py"),
            server_token="server-token",
        ),
    )


def _request(session_id: str = _SESSION_ID) -> Request:
    context = _context()
    capability = editor_binding_capability(
        context.server_token,
        context.file_key,
        context.base_url,
        _CLIENT_ID,
        session_id,
    )
    return Request(
        {
            "type": "http",
            "method": "GET",
            "scheme": "http",
            "path": "/",
            "raw_path": b"/",
            "query_string": urlencode(
                {
                    "marimo_studio_client": _CLIENT_ID,
                    "marimo_studio_editor": capability,
                    "marimo_studio_server": server_instance_id(context.server_token),
                    "session_id": session_id,
                }
            ).encode(),
            "headers": [],
            "client": ("127.0.0.1", 1),
            "server": ("127.0.0.1", 2),
            "root_path": "",
            "auth": SimpleNamespace(scopes=("edit",)),
        }
    )


def _notebooks(clients: StudioClientRegistry) -> Any:
    return SimpleNamespace(get=lambda _notebook: SimpleNamespace(clients=clients))


async def _bind(
    clients: StudioClientRegistry,
    sessions: _Sessions,
    request: Request,
) -> NativeSessionAdmission:
    context = _context()
    binding = await _bind_editor_session(
        _notebooks(clients),
        request,
        context,
        cast(SessionState, sessions),
        bind_session=True,
        expected_server_instance=server_instance_id(context.server_token),
        lifetime_owner=_LIFETIME_OWNER,
    )
    assert binding.status == "bound"
    assert binding.admission is not None
    return binding.admission


def test_editor_client_keeps_one_server_assigned_session() -> None:
    async def exercise() -> None:
        clients = StudioClientRegistry()
        sessions = _Sessions()

        await _bind(clients, sessions, _request())
        conflicting = await _bind_editor_session(
            _notebooks(clients),
            _request("s_654321"),
            _context(),
            cast(SessionState, sessions),
            bind_session=True,
            expected_server_instance=server_instance_id(_context().server_token),
            lifetime_owner=_LIFETIME_OWNER,
        )

        retained = await clients.binding_for_client(_CLIENT_ID)
        assert conflicting.status == "invalid"
        assert retained is not None and retained.session_id == _SESSION_ID
        await clients.close()

    asyncio.run(exercise())


def test_connector_preclaim_rejects_and_releases_the_editor_binding() -> None:
    async def exercise() -> None:
        clients = StudioClientRegistry()
        sessions = _Sessions()
        admission = await _bind(clients, sessions, _request())
        preclaim = object()
        sessions.state = "current"
        sessions.claim = preclaim

        assert admission.on_reject is not None
        admission.on_reject()

        assert await clients.binding_for_client(_CLIENT_ID) is None
        await clients.close()

    asyncio.run(exercise())


def test_concurrent_same_identity_success_preserves_the_shared_binding() -> None:
    async def exercise() -> None:
        clients = StudioClientRegistry()
        sessions = _Sessions()
        winner = await _bind(clients, sessions, _request())
        repeated = await _bind(clients, sessions, _request())
        native = object()
        capability = editor_binding_capability(
            _context().server_token,
            _context().file_key,
            _context().base_url,
            _CLIENT_ID,
            _SESSION_ID,
        )

        assert await clients.connect_stream(_CLIENT_ID, 1, "dashboard") is not None
        assert await clients.session_for_client(_CLIENT_ID) is None
        changed = asyncio.Event()
        unsubscribe = clients.subscribe(changed.set)
        assert winner.on_accept is not None
        winner.on_accept(native)
        assert sessions.retried == [native]
        await asyncio.wait_for(changed.wait(), timeout=1)
        unsubscribe()
        assert winner.binding_current is not None and winner.binding_current()
        assert repeated.binding_current is not None and repeated.binding_current()
        assert await clients.session_for_client(_CLIENT_ID) == _SESSION_ID
        snapshot = await clients.snapshot_for_client(_CLIENT_ID)
        assert snapshot is not None and not snapshot.binding_replaced
        assert snapshot.target.session_id == _SESSION_ID
        sessions.state = "current"
        sessions.claim = native
        sessions.identity = EditorSessionIdentity(_CLIENT_ID, capability)
        assert repeated.on_reject is not None
        repeated.on_reject()

        assert await clients.binding_for_client(_CLIENT_ID) is not None
        await clients.close()

    asyncio.run(exercise())


def test_registry_close_invalidates_an_outstanding_native_admission() -> None:
    async def exercise() -> None:
        clients = StudioClientRegistry()
        sessions = _Sessions()
        admission = await _bind(clients, sessions, _request())

        await clients.close()

        assert admission.binding_current is not None
        assert not admission.binding_current()

    asyncio.run(exercise())


def test_new_native_incarnation_rotates_the_binding_generation() -> None:
    async def exercise() -> None:
        clients = StudioClientRegistry()
        sessions = _Sessions()
        first = await _bind(clients, sessions, _request())
        assert await clients.connect_stream(_CLIENT_ID, 1, "dashboard") is not None
        assert first.on_accept is not None
        first.on_accept(object())
        before = await clients.snapshot_for_client(_CLIENT_ID)
        assert before is not None
        operation_id = "editor-incarnation-handoff"
        assert await clients.begin_active_view_handoff(
            _CLIENT_ID,
            operation_id,
            "dashboard",
            "report",
        )

        replacement = await _bind(clients, sessions, _request())
        assert replacement.on_accept is not None
        replacement.on_accept(object())
        after = await clients.snapshot_for_client(_CLIENT_ID)

        assert after is not None
        assert after.target.binding_generation > before.target.binding_generation
        assert after.target.active_view == "dashboard"
        assert after.binding_replaced
        assert first.binding_current is not None and not first.binding_current()
        assert replacement.binding_current is not None and replacement.binding_current()
        assert await clients.rollback_active_view_handoff(_CLIENT_ID, operation_id)
        assert first.on_close is not None
        closed = first.on_close()
        assert closed is not None
        await closed
        assert await clients.session_for_client(_CLIENT_ID) == _SESSION_ID
        await clients.close()

    asyncio.run(exercise())


def test_current_native_identity_restores_a_pruned_client_binding() -> None:
    async def exercise() -> None:
        cleanup_started = asyncio.Event()
        release_cleanup = asyncio.Event()

        async def wait(_delay: float) -> None:
            cleanup_started.set()
            await release_cleanup.wait()

        clients = StudioClientRegistry(disconnect_grace=0, wait=wait)
        sessions = _Sessions()
        assert await clients.bind_session(_SESSION_ID, _CLIENT_ID) is not None
        await cleanup_started.wait()
        removed = asyncio.Event()
        unsubscribe = clients.subscribe(removed.set)
        release_cleanup.set()
        await asyncio.wait_for(removed.wait(), timeout=1)
        unsubscribe()
        assert await clients.binding_for_client(_CLIENT_ID) is None
        native = object()
        capability = editor_binding_capability(
            _context().server_token,
            _context().file_key,
            _context().base_url,
            _CLIENT_ID,
            _SESSION_ID,
        )
        sessions.state = "current"
        sessions.claim = native
        sessions.identity = EditorSessionIdentity(_CLIENT_ID, capability)

        admission = await _bind(clients, sessions, _request())

        assert admission.mode == "current"
        assert admission.expected_claim is native
        assert await clients.binding_for_client(_CLIENT_ID) is not None
        await clients.close()

    asyncio.run(exercise())
