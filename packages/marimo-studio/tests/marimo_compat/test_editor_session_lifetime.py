"""Protect native editor disconnect and session lifetime ownership."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any, cast

import pytest
from marimo._server.api.endpoints.ws.sse_handler import SSESessionHandler
from marimo._server.api.endpoints.ws_endpoint import WebSocketHandler
from marimo._session.events import SessionEventBus
from marimo._session.model import ConnectionState, SessionMode
from starlette.websockets import WebSocketDisconnect, WebSocketState

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
        self._event_bus = SessionEventBus()
        self.session: _Session | None = session

    @property
    def sessions(self) -> dict[str, _Session]:
        return {"s_native": self.session} if self.session is not None else {}

    def get_session(self, session_id: object) -> _Session | None:
        return self.session if str(session_id) == "s_native" else None

    def close_session(self, session_id: object) -> None:
        # Marimo removes the session before it emits the closed event.
        if str(session_id) == "s_native" and self.session is not None:
            session, self.session = self.session, None
            asyncio.get_running_loop().create_task(
                self._event_bus.emit_session_closed(cast(Any, session))
            )


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


@pytest.mark.parametrize(
    ("application_state", "client_state"),
    (
        (WebSocketState.CONNECTED, WebSocketState.DISCONNECTED),
        (WebSocketState.DISCONNECTED, WebSocketState.CONNECTED),
    ),
    ids=("client", "application"),
)
def test_websocket_safe_close_is_terminal_after_disconnect(
    application_state: WebSocketState,
    client_state: WebSocketState,
) -> None:
    close_calls = 0

    async def close(_code: int, _reason: str) -> None:
        nonlocal close_calls
        close_calls += 1

    handler = cast(
        Any,
        SimpleNamespace(
            websocket=SimpleNamespace(
                application_state=application_state,
                client_state=client_state,
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
@pytest.mark.parametrize("ttl", [None, 0])
def test_editor_disconnect_follows_native_session_ttl(
    handler_type: type[WebSocketHandler] | type[SSESessionHandler],
    ttl: int | None,
) -> None:
    async def exercise() -> None:
        session = _Session()
        manager = _SessionManager(session)
        manager.ttl_seconds = ttl
        adapter, handle = _open(cast(Any, manager))
        closed = asyncio.Event()
        admission = _accepted_admission(adapter, manager, session, closed.set)
        handler = cast(
            Any,
            SimpleNamespace(
                manager=manager,
                params=SimpleNamespace(session_id="s_native"),
                mode=SessionMode.EDIT,
                status=ConnectionState.OPEN,
                cancel_close_handle=None,
                _session=session,
                **{
                    (
                        "websocket" if handler_type is WebSocketHandler else "request"
                    ): SimpleNamespace(
                        scope={NATIVE_SESSION_ADMISSION_SCOPE_KEY: admission}
                    )
                },
            ),
        )
        try:
            handler_type._on_disconnect(handler)
            if ttl is None:
                barrier = asyncio.Event()
                asyncio.get_running_loop().call_soon(barrier.set)
                await barrier.wait()
                assert manager.session is session
                assert not closed.is_set()
            else:
                await asyncio.wait_for(closed.wait(), timeout=1)
                assert manager.session is None
        finally:
            handle.close()
        assert closed.is_set()

    asyncio.run(exercise())
