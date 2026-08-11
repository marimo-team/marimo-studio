from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from marimo._server.api.endpoints.ws.ws_session_connector import (
    ConnectionType,
    SessionConnector,
)
from marimo._session.model import SessionMode
from starlette.datastructures import QueryParams
from starlette.websockets import WebSocketDisconnect

from marimo_studio._capabilities import CloseHandle, ServerContext, ServerHandle
from marimo_studio._compat.server.existing_session import (
    _PREVIEW_CONNECT_GRACE,
    PrivateExistingSessionAttachment,
)
from marimo_studio._compat.server.gateway import _ContextHandle
from marimo_studio._urls import STUDIO_CLIENT_QUERY_PARAM


class _Session:
    def __init__(self, file_key: str = "notebook.py") -> None:
        self.initialization_id = file_key
        self.app_file_manager = SimpleNamespace(path=Path(file_key))
        self.room = SimpleNamespace(consumers={})


class _Manager:
    mode = SessionMode.EDIT

    def __init__(self) -> None:
        self.sessions: dict[str, _Session] = {}
        self.fallback: object | None = None
        self.fallback_calls = 0

    def get_session(self, session_id: object) -> _Session | None:
        return self.sessions.get(str(session_id))

    def get_session_by_file_key(self, _file_key: str) -> object | None:
        self.fallback_calls += 1
        return self.fallback


def _context(manager: _Manager) -> ServerContext:
    return ServerContext(
        notebook=Path("notebook.py").resolve(),
        file_key="notebook.py",
        base_url="",
        mode="edit",
        dev=True,
        routing_query=(),
        user_config={},
        config_overrides={},
        server_token="token",
        handle=ServerHandle(_ContextHandle(server=None, session_manager=manager)),
    )


def _connect(
    manager: _Manager,
    consumer_id: str,
) -> tuple[object, ConnectionType]:
    connected: list[object] = []
    connector = SessionConnector(
        manager=cast(Any, manager),
        handler=cast(
            Any,
            SimpleNamespace(_connect_kiosk=lambda session: connected.append(session)),
        ),
        params=cast(
            Any,
            SimpleNamespace(session_id=consumer_id, file_key="notebook.py"),
        ),
        connection=cast(
            Any,
            SimpleNamespace(
                query_params=QueryParams({STUDIO_CLIENT_QUERY_PARAM: "client-1234"})
            ),
        ),
    )
    result = connector._connect_kiosk()
    assert connected == [result[0]]
    return result


def _open(
    manager: _Manager,
    *,
    clock: Any | None = None,
) -> tuple[PrivateExistingSessionAttachment, CloseHandle]:
    adapter = (
        PrivateExistingSessionAttachment()
        if clock is None
        else PrivateExistingSessionAttachment(clock)
    )
    handle = adapter.open()
    return adapter, handle


def test_preview_consumers_attach_to_the_exact_editor_session() -> None:
    manager = _Manager()
    first = _Session()
    second = _Session()
    manager.sessions = {"s_first1": first, "s_second": second}
    adapter, handle = _open(manager)
    try:
        assert adapter.attach(_context(manager), "s_view01", "s_first1")
        assert adapter.attach(_context(manager), "s_view02", "s_second")

        assert _connect(manager, "s_view01") == (first, ConnectionType.KIOSK)
        assert _connect(manager, "s_view02") == (second, ConnectionType.KIOSK)
        assert manager.get_session("s_view01") is None
    finally:
        handle.close()


def test_studio_preview_never_falls_back_to_a_file_session() -> None:
    manager = _Manager()
    target = _Session()
    manager.sessions["s_target"] = target
    manager.fallback = _Session()
    adapter, handle = _open(manager)
    try:
        assert adapter.attach(_context(manager), "s_view01", "s_target")
        manager.sessions.clear()

        with pytest.raises(WebSocketDisconnect):
            _connect(manager, "s_view01")

        assert manager.fallback_calls == 0
    finally:
        handle.close()


def test_native_consumer_id_collision_is_rejected() -> None:
    manager = _Manager()
    target = _Session()
    native = _Session()
    manager.sessions = {"s_target": target, "s_view01": native}
    adapter, handle = _open(manager)
    try:
        assert not adapter.attach(_context(manager), "s_view01", "s_target")
        assert manager.get_session("s_view01") is native
    finally:
        handle.close()


def test_fresh_unclaimed_routes_hold_capacity() -> None:
    manager = _Manager()
    target = _Session()
    manager.sessions["s_target"] = target
    adapter, handle = _open(manager)
    try:
        for index in range(100):
            assert adapter.attach(
                _context(manager),
                f"s_view{index:03d}",
                "s_target",
            )
        assert not adapter.attach(_context(manager), "s_overflow", "s_target")
    finally:
        handle.close()


def test_expired_unclaimed_routes_release_capacity() -> None:
    now = 0.0
    manager = _Manager()
    target = _Session()
    manager.sessions["s_target"] = target
    adapter, handle = _open(manager, clock=lambda: now)
    try:
        for index in range(100):
            assert adapter.attach(
                _context(manager),
                f"s_view{index:03d}",
                "s_target",
            )
        now = _PREVIEW_CONNECT_GRACE + 1
        assert adapter.attach(_context(manager), "s_overflow", "s_target")
        with pytest.raises(WebSocketDisconnect):
            _connect(manager, "s_view000")
        assert _connect(manager, "s_overflow") == (target, ConnectionType.KIOSK)
    finally:
        handle.close()


def test_final_lifecycle_close_restores_the_connector() -> None:
    original = SessionConnector._connect_kiosk
    first = PrivateExistingSessionAttachment()
    second = PrivateExistingSessionAttachment()
    first_handle = first.open()
    replacement = SessionConnector._connect_kiosk
    second_handle = second.open()

    first_handle.close()
    assert SessionConnector._connect_kiosk is replacement

    second_handle.close()
    assert SessionConnector._connect_kiosk is original


def test_lifecycle_close_removes_owned_routes() -> None:
    manager = _Manager()
    target = _Session()
    manager.sessions["s_target"] = target
    adapter, handle = _open(manager)
    assert adapter.attach(_context(manager), "s_view01", "s_target")

    handle.close()
    verifier = PrivateExistingSessionAttachment()
    verifier_handle = verifier.open()
    try:
        with pytest.raises(WebSocketDisconnect):
            _connect(manager, "s_view01")
    finally:
        verifier_handle.close()
