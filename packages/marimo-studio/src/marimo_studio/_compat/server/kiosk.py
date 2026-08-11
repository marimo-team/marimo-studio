"""Route a Studio preview consumer to its owning Marimo editor session."""

from __future__ import annotations

import time
from collections import OrderedDict
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from threading import RLock
from typing import Any

from marimo_studio._urls import STUDIO_CLIENT_QUERY_PARAM

_ROUTER_ATTRIBUTE = "_marimo_studio_kiosk_router"
_CONNECTOR_GUARD_ATTRIBUTE = "_marimo_studio_exact_kiosk_guard"
_MAX_ROUTES = 100
_PREVIEW_CONNECT_GRACE = 30.0


@dataclass
class _KioskRoute:
    session: Any
    registered_at: float
    claimed: bool = False


class _KioskSessionRouter:
    def __init__(
        self,
        resolve: Callable[[object], Any],
        active_sessions: Callable[[], tuple[Any, ...]],
        clock: Callable[[], float],
    ) -> None:
        self._resolve = resolve
        self._active_sessions = active_sessions
        self._clock = clock
        self._routes: OrderedDict[str, _KioskRoute] = OrderedDict()
        self._lock = RLock()

    def register(self, consumer_id: str, session: Any) -> bool:
        with self._lock:
            self._prune()
            native_session = self._resolve(consumer_id)
            if native_session is not None and native_session is not session:
                return False
            current = self._routes.get(consumer_id)
            if current is not None:
                if current.session is not session:
                    return False
                if not current.claimed:
                    current.registered_at = self._clock()
                self._routes.move_to_end(consumer_id)
                return True
            if len(self._routes) >= _MAX_ROUTES:
                retired = next(
                    (
                        key
                        for key, route in self._routes.items()
                        if route.claimed and not self._is_connected(key, route.session)
                    ),
                    None,
                )
                if retired is None:
                    return False
                self._routes.pop(retired)
            self._routes[consumer_id] = _KioskRoute(session, self._clock())
            return True

    def resolve(self, session_id: object) -> Any:
        existing = self._resolve(session_id)
        key = str(session_id)
        if existing is not None:
            return existing
        with self._lock:
            self._prune()
            route = self._routes.get(key)
            if route is None or not self._is_active(route.session):
                self._routes.pop(key, None)
                return None
            route.claimed = True
            self._routes.move_to_end(key)
            return route.session

    def _prune(self) -> None:
        now = self._clock()
        inactive = [
            key
            for key, route in self._routes.items()
            if not self._is_active(route.session)
            or (
                not route.claimed
                and now - route.registered_at >= _PREVIEW_CONNECT_GRACE
            )
        ]
        for key in inactive:
            self._routes.pop(key, None)

    def _is_active(self, session: Any) -> bool:
        return any(session is candidate for candidate in self._active_sessions())

    @staticmethod
    def _is_connected(consumer_id: str, session: Any) -> bool:
        room = getattr(session, "room", None)
        consumers = getattr(room, "consumers", None)
        return isinstance(consumers, Mapping) and consumer_id in consumers


def route_kiosk_consumer(
    session_manager: Any,
    consumer_id: str,
    session: Any,
    *,
    clock: Callable[[], float] = time.monotonic,
) -> bool:
    """Resolve a Studio kiosk consumer to its exact editor session."""
    _install_exact_kiosk_guard()
    router = getattr(session_manager, _ROUTER_ATTRIBUTE, None)
    if not isinstance(router, _KioskSessionRouter):
        router = _KioskSessionRouter(
            session_manager.get_session,
            lambda: tuple(session_manager.sessions.values()),
            clock,
        )
        setattr(session_manager, _ROUTER_ATTRIBUTE, router)
        session_manager.get_session = router.resolve
    return router.register(consumer_id, session)


def _install_exact_kiosk_guard() -> None:
    from marimo._server.api.endpoints.ws.ws_session_connector import (
        ConnectionType,
        SessionConnector,
    )
    from marimo._server.codes import WebSocketCloseReason, WebSocketCodes
    from marimo._session.model import SessionMode
    from starlette.websockets import WebSocketDisconnect

    if getattr(SessionConnector, _CONNECTOR_GUARD_ATTRIBUTE, False):
        return
    native_connect = SessionConnector._connect_kiosk

    def connect_kiosk(self: SessionConnector) -> tuple[Any, ConnectionType]:
        query = self.connection.query_params
        if query.get(STUDIO_CLIENT_QUERY_PARAM) is None:
            return native_connect(self)
        if self.manager.mode is not SessionMode.EDIT:
            raise WebSocketDisconnect(
                WebSocketCodes.FORBIDDEN,
                WebSocketCloseReason.KIOSK_NOT_ALLOWED,
            )
        router = getattr(self.manager, _ROUTER_ATTRIBUTE, None)
        session = (
            router.resolve(self.params.session_id)
            if isinstance(router, _KioskSessionRouter)
            else None
        )
        if session is None:
            raise WebSocketDisconnect(
                WebSocketCodes.NORMAL_CLOSE,
                WebSocketCloseReason.NO_SESSION,
            )
        self.handler._connect_kiosk(session)
        return session, ConnectionType.KIOSK

    SessionConnector._connect_kiosk = connect_kiosk
    setattr(SessionConnector, _CONNECTOR_GUARD_ATTRIBUTE, True)


__all__ = ["route_kiosk_consumer"]
