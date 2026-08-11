"""Attach a Studio consumer to one exact existing Marimo session."""

from __future__ import annotations

import time
from collections import OrderedDict
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from threading import RLock
from typing import Any
from weakref import WeakKeyDictionary, ref

from marimo._server.api.endpoints.ws.ws_session_connector import SessionConnector

from marimo_studio._capabilities import ServerContext
from marimo_studio._compat.patch import (
    CallbackCloseHandle,
    CompositeCloseHandle,
    ReversiblePatch,
)
from marimo_studio._compat.server.gateway import context_handle
from marimo_studio._compat.server.session_state import current_session
from marimo_studio._urls import STUDIO_CLIENT_QUERY_PARAM

_MAX_ROUTES = 100
_PREVIEW_CONNECT_GRACE = 30.0


@dataclass
class _SessionRoute:
    owner: object
    session: Any
    registered_at: float
    claimed: bool = False


class _SessionRouter:
    def __init__(self, manager: Any, clock: Callable[[], float]) -> None:
        self._manager = ref(manager)
        self._clock = clock
        self._routes: OrderedDict[str, _SessionRoute] = OrderedDict()
        self._lock = RLock()

    def register(self, owner: object, consumer_id: str, session: Any) -> bool:
        with self._lock:
            self._prune()
            native_session = self._native_session(consumer_id)
            if native_session is not None and native_session is not session:
                return False
            current = self._routes.get(consumer_id)
            if current is not None:
                if current.owner is not owner or current.session is not session:
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
            self._routes[consumer_id] = _SessionRoute(
                owner,
                session,
                self._clock(),
            )
            return True

    def resolve(self, session_id: object) -> Any:
        key = str(session_id)
        native = self._native_session(key)
        if native is not None:
            return native
        with self._lock:
            self._prune()
            route = self._routes.get(key)
            if route is None or not self._is_active(route.session):
                self._routes.pop(key, None)
                return None
            route.claimed = True
            self._routes.move_to_end(key)
            return route.session

    def remove_owner(self, owner: object) -> None:
        with self._lock:
            self._routes = OrderedDict(
                (consumer_id, route)
                for consumer_id, route in self._routes.items()
                if route.owner is not owner
            )

    def _native_session(self, session_id: object) -> Any:
        manager = self._manager()
        return manager.get_session(session_id) if manager is not None else None

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
        manager = self._manager()
        sessions = getattr(manager, "sessions", {}) if manager is not None else {}
        return any(session is candidate for candidate in sessions.values())

    @staticmethod
    def _is_connected(consumer_id: str, session: Any) -> bool:
        consumers = getattr(getattr(session, "room", None), "consumers", None)
        return isinstance(consumers, Mapping) and consumer_id in consumers


_ROUTERS: WeakKeyDictionary[Any, _SessionRouter] = WeakKeyDictionary()
_ROUTERS_LOCK = RLock()


def _router(manager: Any, clock: Callable[[], float]) -> _SessionRouter:
    with _ROUTERS_LOCK:
        router = _ROUTERS.get(manager)
        if router is None:
            router = _SessionRouter(manager, clock)
            _ROUTERS[manager] = router
        return router


def _connect_replacement(native_connect: Any) -> Any:
    from marimo._server.api.endpoints.ws.ws_session_connector import ConnectionType
    from marimo._server.codes import WebSocketCloseReason, WebSocketCodes
    from marimo._session.model import SessionMode
    from starlette.websockets import WebSocketDisconnect

    def connect_existing(connector: SessionConnector) -> tuple[Any, ConnectionType]:
        if connector.connection.query_params.get(STUDIO_CLIENT_QUERY_PARAM) is None:
            return native_connect(connector)
        if connector.manager.mode is not SessionMode.EDIT:
            raise WebSocketDisconnect(
                WebSocketCodes.FORBIDDEN,
                WebSocketCloseReason.KIOSK_NOT_ALLOWED,
            )
        with _ROUTERS_LOCK:
            router = _ROUTERS.get(connector.manager)
        session = router.resolve(connector.params.session_id) if router else None
        if session is None:
            raise WebSocketDisconnect(
                WebSocketCodes.NORMAL_CLOSE,
                WebSocketCloseReason.NO_SESSION,
            )
        connector.handler._connect_kiosk(session)
        return session, ConnectionType.KIOSK

    return connect_existing


_CONNECT_PATCH = ReversiblePatch(
    "existing-session-attachment",
    SessionConnector,
    "_connect_kiosk",
    _connect_replacement,
)


class PrivateExistingSessionAttachment:
    """Own exact-session registrations for one Studio application lifespan."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._owner = object()
        self._managers: WeakKeyDictionary[Any, None] = WeakKeyDictionary()
        self._active = False

    def open(self) -> CompositeCloseHandle:
        with _ROUTERS_LOCK:
            if self._active:
                raise RuntimeError("The existing-session adapter is already open")
            self._active = True
        try:
            patch = _CONNECT_PATCH.open()
        except BaseException:
            with _ROUTERS_LOCK:
                self._active = False
            raise
        return CompositeCloseHandle(
            (
                patch,
                CallbackCloseHandle(self.close),
            )
        )

    def attach(
        self,
        context: ServerContext,
        consumer_id: str,
        session_id: str,
    ) -> bool:
        session = current_session(context, session_id)
        if session is None:
            return False
        manager = context_handle(context).session_manager
        with _ROUTERS_LOCK:
            if not self._active:
                return False
            router = _router(manager, self._clock)
            registered = router.register(self._owner, consumer_id, session)
            if registered:
                self._managers[manager] = None
            return registered

    def close(self) -> None:
        with _ROUTERS_LOCK:
            self._active = False
            for manager in tuple(self._managers):
                router = _ROUTERS.get(manager)
                if router is not None:
                    router.remove_owner(self._owner)
            self._managers.clear()


__all__ = ["PrivateExistingSessionAttachment"]
