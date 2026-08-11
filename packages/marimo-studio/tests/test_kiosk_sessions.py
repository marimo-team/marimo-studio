from __future__ import annotations

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

from marimo_studio._compat.server import kiosk
from marimo_studio._compat.server.kiosk import route_kiosk_consumer
from marimo_studio._urls import STUDIO_CLIENT_QUERY_PARAM


class _SessionManager:
    def __init__(self) -> None:
        self.sessions: dict[str, object] = {}

    def get_session(self, session_id: object) -> object | None:
        return self.sessions.get(str(session_id))


class _ConnectorManager(_SessionManager):
    mode = SessionMode.EDIT

    def __init__(self) -> None:
        super().__init__()
        self.fallback: object | None = None
        self.fallback_calls = 0

    def get_session_by_file_key(self, _file_key: str) -> object | None:
        self.fallback_calls += 1
        return self.fallback


def _connect_kiosk(
    manager: _ConnectorManager,
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
            SimpleNamespace(
                session_id=consumer_id,
                file_key="notebook.py",
            ),
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


def test_kiosk_consumers_resolve_to_their_exact_editor_sessions() -> None:
    manager = _SessionManager()
    first = object()
    second = object()
    manager.sessions = {"s_first1": first, "s_second": second}

    route_kiosk_consumer(manager, "s_view01", first)
    route_kiosk_consumer(manager, "s_view02", second)

    assert manager.get_session("s_view01") is first
    assert manager.get_session("s_view02") is second
    assert manager.get_session("s_second") is second


def test_connected_kiosk_consumers_use_marimos_native_resolution() -> None:
    manager = _SessionManager()
    target = object()
    connected = object()
    manager.sessions["s_target"] = target
    route_kiosk_consumer(manager, "s_view01", target)

    manager.sessions["s_view01"] = connected

    assert manager.get_session("s_view01") is connected


def test_connected_kiosk_route_accepts_its_native_session_mapping() -> None:
    manager = _SessionManager()
    target = object()
    manager.sessions["s_target"] = target
    assert route_kiosk_consumer(manager, "s_view01", target)

    manager.sessions["s_view01"] = target

    assert route_kiosk_consumer(manager, "s_view01", target)
    assert manager.get_session("s_view01") is target


def test_delayed_kiosk_consumer_keeps_its_exact_editor_session() -> None:
    manager = _SessionManager()
    first = object()
    second = object()
    manager.sessions = {"s_first1": first, "s_second": second}

    assert route_kiosk_consumer(manager, "s_view01", first)
    for index in range(20):
        assert route_kiosk_consumer(manager, f"s_other{index:02d}", second)

    assert manager.get_session("s_view01") is first


def test_kiosk_route_remains_available_for_reconnect() -> None:
    manager = _SessionManager()
    target = object()
    manager.sessions["s_target"] = target
    route_kiosk_consumer(manager, "s_view01", target)

    assert manager.get_session("s_view01") is target
    assert manager.get_session("s_view01") is target


def test_kiosk_route_rejects_a_disconnected_editor_session() -> None:
    manager = _SessionManager()
    target = object()
    manager.sessions["s_target"] = target
    route_kiosk_consumer(manager, "s_view01", target)

    manager.sessions.clear()

    assert manager.get_session("s_view01") is None


def test_disconnected_kiosk_routes_are_reclaimed_at_capacity() -> None:
    manager = _SessionManager()
    target = object()
    manager.sessions["s_target"] = target

    for index in range(100):
        consumer_id = f"s_view{index:03d}"
        assert route_kiosk_consumer(manager, consumer_id, target)
        assert manager.get_session(consumer_id) is target

    assert route_kiosk_consumer(manager, "s_next01", target)
    assert manager.get_session("s_view000") is None
    assert manager.get_session("s_next01") is target


def test_parallel_bootstraps_for_one_editor_remain_available() -> None:
    manager = _SessionManager()
    target = object()
    manager.sessions["s_target"] = target

    assert route_kiosk_consumer(manager, "s_view001", target)
    assert route_kiosk_consumer(manager, "s_view002", target)

    assert manager.get_session("s_view001") is target
    assert manager.get_session("s_view002") is target


def test_fresh_unclaimed_kiosk_routes_hold_capacity_without_retargeting() -> None:
    manager = _SessionManager()
    sessions = [object() for _ in range(101)]
    manager.sessions = {
        f"s_owner{index:03d}": session for index, session in enumerate(sessions)
    }

    for index in range(100):
        assert route_kiosk_consumer(
            manager,
            f"s_view{index:03d}",
            sessions[index],
        )

    assert not route_kiosk_consumer(manager, "s_overflow", sessions[100])
    assert manager.get_session("s_view000") is sessions[0]
    assert manager.get_session("s_overflow") is None


def test_expired_unclaimed_kiosk_routes_release_capacity() -> None:
    manager = _SessionManager()
    sessions = [object() for _ in range(101)]
    manager.sessions = {
        f"s_owner{index:03d}": session for index, session in enumerate(sessions)
    }
    now = 0.0

    def clock() -> float:
        return now

    for index in range(100):
        assert route_kiosk_consumer(
            manager,
            f"s_view{index:03d}",
            sessions[index],
            clock=clock,
        )

    now = kiosk._PREVIEW_CONNECT_GRACE + 1
    assert route_kiosk_consumer(
        manager,
        "s_overflow",
        sessions[100],
        clock=clock,
    )
    assert manager.get_session("s_view000") is None
    assert manager.get_session("s_overflow") is sessions[100]


def test_unclaimed_kiosk_route_remains_exact_within_connect_grace() -> None:
    manager = _SessionManager()
    target = object()
    manager.sessions["s_target"] = target
    now = 0.0

    def clock() -> float:
        return now

    assert route_kiosk_consumer(manager, "s_view01", target, clock=clock)
    now = kiosk._PREVIEW_CONNECT_GRACE - 0.1

    assert manager.get_session("s_view01") is target


def test_kiosk_route_rejects_a_native_session_id_collision() -> None:
    manager = _SessionManager()
    target = object()
    native = object()
    manager.sessions = {"s_target": target, "s_view01": native}

    assert not route_kiosk_consumer(manager, "s_view01", target)
    assert manager.get_session("s_view01") is native


def test_connected_kiosk_routes_are_not_reclaimed() -> None:
    manager = _SessionManager()
    consumer_ids = [f"s_view{index:03d}" for index in range(100)]
    target = SimpleNamespace(
        room=SimpleNamespace(
            consumers={consumer_id: object() for consumer_id in consumer_ids}
        )
    )
    manager.sessions["s_target"] = target

    for consumer_id in consumer_ids:
        assert route_kiosk_consumer(manager, consumer_id, target)
        assert manager.get_session(consumer_id) is target

    assert not route_kiosk_consumer(manager, "s_overflow", target)
    assert manager.get_session(consumer_ids[0]) is target


def test_reconnected_studio_kiosk_route_never_falls_back_by_file_key() -> None:
    manager = _ConnectorManager()
    target = object()
    manager.sessions["s_target"] = target
    manager.fallback = object()
    route_kiosk_consumer(manager, "s_view01", target)

    assert _connect_kiosk(manager, "s_view01") == (target, ConnectionType.KIOSK)
    assert _connect_kiosk(manager, "s_view01") == (target, ConnectionType.KIOSK)

    assert manager.fallback_calls == 0


def test_parallel_studio_kiosk_routes_never_fall_back_by_file_key() -> None:
    manager = _ConnectorManager()
    target = object()
    manager.sessions["s_target"] = target
    manager.fallback = object()
    route_kiosk_consumer(manager, "s_view01", target)
    route_kiosk_consumer(manager, "s_view02", target)

    assert _connect_kiosk(manager, "s_view01") == (target, ConnectionType.KIOSK)
    assert _connect_kiosk(manager, "s_view02") == (target, ConnectionType.KIOSK)

    assert manager.fallback_calls == 0


def test_inactive_studio_kiosk_route_never_falls_back_by_file_key() -> None:
    manager = _ConnectorManager()
    target = object()
    manager.sessions["s_target"] = target
    manager.fallback = object()
    route_kiosk_consumer(manager, "s_view01", target)
    manager.sessions.clear()

    with pytest.raises(WebSocketDisconnect):
        _connect_kiosk(manager, "s_view01")

    assert manager.fallback_calls == 0
