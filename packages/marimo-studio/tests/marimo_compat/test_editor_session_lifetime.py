"""Protect native editor disconnect and session lifetime ownership."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any, cast

import pytest
from marimo._server.api.endpoints.ws.session_handler import SessionHandler
from marimo._server.api.endpoints.ws.sse_handler import SSESessionHandler
from marimo._server.api.endpoints.ws_endpoint import WebSocketHandler
from marimo._session.model import ConnectionState, SessionMode
from starlette.websockets import WebSocketDisconnect, WebSocketState

import marimo_studio._compat.server.editor_session_lifetimes as lifetime_module
import marimo_studio._compat.server.existing_session as existing_session_module
from marimo_studio._compat.server.existing_session import (
    PrivateExistingSessionAttachment,
)
from marimo_studio._server.presentation.admission import (
    NATIVE_SESSION_ADMISSION_SCOPE_KEY,
    NativeSessionAdmission,
)

from .session_adapter_test_support import Manager as _Manager
from .session_adapter_test_support import context as _context
from .session_adapter_test_support import open_adapter as _open


def _own_admission(
    adapter: PrivateExistingSessionAttachment,
    manager: object,
    admission: NativeSessionAdmission,
) -> object:
    owner = adapter.claim_editor_lifetime(_context(cast(Any, manager)))
    assert owner is not None
    admission.lifetime_owner = owner
    return owner


class _Session:
    def __init__(
        self,
        *,
        ttl_seconds: int = 0,
        state: ConnectionState = ConnectionState.OPEN,
        disconnect_closes: bool = True,
    ) -> None:
        self.ttl_seconds = ttl_seconds
        self.state = state
        self.disconnect_closes = disconnect_closes

    def disconnect_consumer(self, _consumer: object) -> None:
        if self.disconnect_closes:
            self.state = ConnectionState.CLOSED

    def connection_state(self) -> ConnectionState:
        return self.state


class _SessionManager:
    mode = SessionMode.EDIT
    ttl_seconds: int | None = None

    def __init__(self, session: _Session) -> None:
        self.session: _Session | None = session

    def get_session(self, session_id: object) -> _Session | None:
        return self.session if str(session_id) == "s_native" else None

    def close_session(self, session_id: object) -> None:
        if str(session_id) == "s_native":
            self.session = None


def _accepted_admission(
    adapter: PrivateExistingSessionAttachment,
    manager: _SessionManager,
    session: _Session,
    on_close: Any,
) -> NativeSessionAdmission:
    admission = NativeSessionAdmission(
        expected_claim=session,
        file_key="notebook.py",
        mode="current",
        notebook="notebook.py",
        runtime_session_id="s_native",
        on_close=on_close,
    )
    _own_admission(adapter, manager, admission)
    existing_session_module._settle_native_admission(
        admission,
        accepted=True,
        native_claim=session,
        manager=manager,
        session_id="s_native",
    )
    return admission


def test_websocket_safe_close_is_terminal_after_client_disconnect() -> None:
    close_calls = 0

    async def close(_code: int, _reason: str) -> None:
        nonlocal close_calls
        close_calls += 1

    handler = cast(
        Any,
        SimpleNamespace(
            websocket=SimpleNamespace(
                application_state=WebSocketState.CONNECTED,
                client_state=WebSocketState.DISCONNECTED,
                close=close,
            )
        ),
    )
    _adapter, handle = _open(_Manager())
    try:
        asyncio.run(WebSocketHandler._safe_close(handler, 1000, "closed"))
    finally:
        handle.close()

    assert close_calls == 0


def test_websocket_safe_close_settles_a_transport_disconnect_race() -> None:
    async def close(_code: int, _reason: str) -> None:
        raise WebSocketDisconnect(code=1006)

    handler = cast(
        Any,
        SimpleNamespace(
            websocket=SimpleNamespace(
                application_state=WebSocketState.CONNECTED,
                client_state=WebSocketState.CONNECTED,
                close=close,
            )
        ),
    )
    _adapter, handle = _open(_Manager())
    try:
        asyncio.run(WebSocketHandler._safe_close(handler, 1000, "closed"))
    finally:
        handle.close()


@pytest.mark.parametrize("handler_type", [WebSocketHandler, SSESessionHandler])
def test_studio_editor_session_ttl_closes_only_the_disconnected_claim(
    handler_type: type[WebSocketHandler] | type[SSESessionHandler],
) -> None:
    async def exercise() -> None:
        session = _Session()
        manager = _SessionManager(session)
        _adapter, handle = _open(cast(Any, manager))
        closed = asyncio.Event()
        admission = _accepted_admission(
            _adapter,
            manager,
            session,
            closed.set,
        )
        handler = cast(
            Any,
            SimpleNamespace(
                manager=manager,
                params=SimpleNamespace(session_id="s_native"),
                mode=SessionMode.EDIT,
                status=ConnectionState.OPEN,
                cancel_close_handle=None,
                **{
                    (
                        "websocket" if handler_type is WebSocketHandler else "request"
                    ): SimpleNamespace(
                        scope={NATIVE_SESSION_ADMISSION_SCOPE_KEY: admission}
                    )
                },
            ),
        )
        cleaned: list[object] = []
        try:
            handler_type._on_disconnect(
                handler,
                RuntimeError("closed"),
                lambda: cleaned.append(session),
            )
            await asyncio.wait_for(closed.wait(), timeout=1)
        finally:
            handle.close()

        assert cleaned == [session]
        assert manager.session is None
        assert closed.is_set()

    asyncio.run(exercise())


def test_studio_editor_session_ttl_is_cancelled_by_reconnect() -> None:
    async def exercise() -> None:
        session = _Session()
        manager = _SessionManager(session)
        _adapter, handle = _open(cast(Any, manager))
        admission = _accepted_admission(
            _adapter,
            manager,
            session,
            lambda: None,
        )
        handler = cast(
            Any,
            SimpleNamespace(
                manager=manager,
                websocket=SimpleNamespace(
                    scope={NATIVE_SESSION_ADMISSION_SCOPE_KEY: admission}
                ),
                params=SimpleNamespace(session_id="s_native"),
                mode=SessionMode.EDIT,
                status=ConnectionState.OPEN,
                cancel_close_handle=None,
            ),
        )
        try:
            SessionHandler._on_disconnect(handler, RuntimeError("closed"), lambda: None)
            timer = lifetime_module._STUDIO_SESSION_LIFETIMES[session].timer
            assert timer is not None
            session.state = ConnectionState.OPEN
            lifetime_module._accept_studio_session(
                manager,
                "s_native",
                session,
                admission.on_close,
                admission.lifetime_owner,
            )
            assert timer.cancelled()
            assert lifetime_module._STUDIO_SESSION_LIFETIMES[session].timer is None
            assert manager.session is session
        finally:
            handle.close()

        assert manager.session is None

    asyncio.run(exercise())


def test_configured_native_session_ttl_remains_the_only_close_owner() -> None:
    async def exercise() -> None:
        session = _Session(
            ttl_seconds=60,
            state=ConnectionState.CLOSED,
            disconnect_closes=False,
        )
        manager = _SessionManager(session)
        manager.ttl_seconds = 30
        _adapter, handle = _open(cast(Any, manager))
        admission = _accepted_admission(
            _adapter,
            manager,
            session,
            lambda: None,
        )
        handler = cast(
            Any,
            SimpleNamespace(
                manager=manager,
                websocket=SimpleNamespace(
                    scope={NATIVE_SESSION_ADMISSION_SCOPE_KEY: admission}
                ),
                params=SimpleNamespace(session_id="s_native"),
                mode=SessionMode.EDIT,
                status=ConnectionState.OPEN,
                cancel_close_handle=None,
            ),
        )
        try:
            SessionHandler._on_disconnect(handler, RuntimeError("closed"), lambda: None)
            assert handler.cancel_close_handle is not None
            lifetime = lifetime_module._STUDIO_SESSION_LIFETIMES[session]
            assert lifetime.timer is None
            handler.cancel_close_handle.cancel()
            assert manager.session is session
        finally:
            handle.close()

        assert manager.session is None

    asyncio.run(exercise())


def test_studio_editor_session_ttl_survives_disconnect_cleanup_failure() -> None:
    async def exercise() -> None:
        session = _Session()
        manager = _SessionManager(session)
        closed = asyncio.Event()
        _adapter, handle = _open(cast(Any, manager))
        admission = _accepted_admission(
            _adapter,
            manager,
            session,
            closed.set,
        )
        handler = cast(
            Any,
            SimpleNamespace(
                manager=manager,
                websocket=SimpleNamespace(
                    scope={NATIVE_SESSION_ADMISSION_SCOPE_KEY: admission}
                ),
                params=SimpleNamespace(session_id="s_native"),
                mode=SessionMode.EDIT,
                status=ConnectionState.OPEN,
                cancel_close_handle=None,
            ),
        )

        def fail_cleanup() -> None:
            raise RuntimeError("cleanup failed")

        try:
            with pytest.raises(RuntimeError, match="cleanup failed"):
                SessionHandler._on_disconnect(
                    handler,
                    RuntimeError("closed"),
                    fail_cleanup,
                )
            await asyncio.wait_for(closed.wait(), timeout=1)
        finally:
            handle.close()

        assert manager.session is None

    asyncio.run(exercise())
