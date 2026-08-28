"""Attach a Studio consumer to one exact existing Marimo session."""

from __future__ import annotations

import asyncio
import time
from collections import OrderedDict
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from functools import wraps
from pathlib import Path
from threading import Lock, RLock
from typing import Any, cast
from weakref import WeakKeyDictionary, ref

from marimo._server.api.endpoints.ws.session_handler import SessionHandler
from marimo._server.api.endpoints.ws.ws_session_connector import SessionConnector
from marimo._server.api.endpoints.ws_endpoint import WebSocketHandler
from starlette.websockets import WebSocketDisconnect, WebSocketState

from marimo_studio._compat.patch import (
    CallbackCloseHandle,
    CompositeCloseHandle,
    ReversiblePatch,
)
from marimo_studio._compat.server.editor_session_lifetimes import (
    _accept_studio_session,
    _close_manager_session_lifetimes,
    _close_studio_session_lifetimes,
    _notify_closed_studio_session,
    _open_studio_session_lifetimes,
    _schedule_studio_session_close,
    _track_manager_session_lifetimes,
    session_is_owned,
)
from marimo_studio._compat.server.gateway import context_handle
from marimo_studio._compat.server.session_state import (
    current_session,
    session_creation_query_matches,
    session_matches_notebook,
)
from marimo_studio._delivery.urls import (
    DOCUMENT_LIFECYCLE_QUERY_PARAM,
    SERVER_INSTANCE_QUERY_PARAM,
    STUDIO_CLIENT_QUERY_PARAM,
)
from marimo_studio._server.ports import CloseHandle
from marimo_studio._server.presentation.admission import (
    NATIVE_SESSION_ADMISSION_SCOPE_KEY,
    NativeSessionAdmission,
)
from marimo_studio._server.records import ServerContext
from marimo_studio._server.server_instance import server_instance_id

_MAX_ROUTES = 100
_PREVIEW_CONNECT_GRACE = 30.0


class _StudioSessionRejected(WebSocketDisconnect):
    pass


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


def _query_matches_session(connector: SessionConnector, session: Any) -> bool:
    return session_creation_query_matches(
        session,
        connector.connection.query_params.multi_items(),
    )


def _session_connect_replacement(native_connect: Any) -> Any:
    from marimo._server.api.endpoints.ws.ws_session_connector import ConnectionType
    from marimo._server.codes import WebSocketCloseReason, WebSocketCodes

    @wraps(native_connect)
    def connect_current_server(connector: SessionConnector) -> Any:
        admission = _native_session_admission(connector)
        query = connector.connection.query_params
        client_id = query.get(STUDIO_CLIENT_QUERY_PARAM)
        instance_id = query.get(SERVER_INSTANCE_QUERY_PARAM)
        try:
            if (client_id is not None or instance_id is not None) and (
                instance_id
                != server_instance_id(str(connector.manager.skew_protection_token))
            ):
                raise _StudioSessionRejected(
                    WebSocketCodes.NORMAL_CLOSE,
                    WebSocketCloseReason.NO_SESSION,
                )
            _verify_native_admission(connector)
            if (
                admission is not None
                and admission.mode == "current"
                and admission.replay_on_reconnect
            ):
                session = connector.manager.get_session(connector.params.session_id)
                assert session is not None and session is admission.expected_claim
                session.disconnect_main_consumer()
                connector.handler._reconnect_session(session, replay=True)
                connected = (session, ConnectionType.RECONNECT)
            elif (
                client_id is not None
                and not connector.params.kiosk
                and connector.manager.get_session(connector.params.session_id) is None
                and connector.manager.get_session_by_file_key(connector.params.file_key)
                is not None
            ):
                connected = connector._create_new_session()
            else:
                connected = native_connect(connector)
        except BaseException:
            _settle_native_admission(admission, accepted=False)
            raise
        if not _settle_native_admission(
            admission,
            accepted=True,
            native_claim=connected[0],
            manager=connector.manager,
            session_id=connector.params.session_id,
        ):
            raise _StudioSessionRejected(
                WebSocketCodes.NORMAL_CLOSE,
                WebSocketCloseReason.NO_SESSION,
            )
        return connected

    return connect_current_server


def _verify_native_admission(connector: SessionConnector) -> None:
    from marimo._server.codes import WebSocketCloseReason, WebSocketCodes

    admission = _native_session_admission(connector)
    if admission is None:
        return
    session_id = str(connector.params.session_id)
    valid = (
        session_id == admission.runtime_session_id
        and connector.params.file_key == admission.file_key
        and (admission.binding_current is None or admission.binding_current())
    )
    existing = connector.manager.get_session(connector.params.session_id)
    if admission.mode == "fresh":
        valid = valid and existing is None
    else:
        valid = (
            valid
            and existing is admission.expected_claim
            and session_matches_notebook(
                existing,
                file_key=admission.file_key,
                notebook=Path(admission.notebook),
            )
        )
    if valid:
        return
    _settle_native_admission(admission, accepted=False)
    raise _StudioSessionRejected(
        WebSocketCodes.NORMAL_CLOSE,
        WebSocketCloseReason.NO_SESSION,
    )


def _native_session_admission(
    connector: SessionConnector,
) -> NativeSessionAdmission | None:
    return _scope_native_session_admission(getattr(connector.connection, "scope", {}))


def _scope_native_session_admission(scope: object) -> NativeSessionAdmission | None:
    admission = (
        scope.get(NATIVE_SESSION_ADMISSION_SCOPE_KEY)
        if isinstance(scope, Mapping)
        else None
    )
    return admission if isinstance(admission, NativeSessionAdmission) else None


def _settle_native_admission(
    admission: NativeSessionAdmission | None,
    *,
    accepted: bool,
    native_claim: object | None = None,
    manager: object | None = None,
    session_id: object | None = None,
) -> bool:
    if admission is None or admission.settled:
        return admission is None or not admission.rejected
    admission.settled = True
    admission.rejected = not accepted
    if accepted and native_claim is not None:
        admission.expected_claim = native_claim
        if (
            admission.on_close is not None
            and manager is not None
            and session_id is not None
            and not _accept_studio_session(
                manager,
                session_id,
                native_claim,
                admission.on_close,
                admission.lifetime_owner,
            )
        ):
            admission.rejected = True
            admission.force_reject_binding = True
            session_manager = cast(Any, manager)
            try:
                incumbent = session_is_owned(native_claim)
                if (
                    not incumbent
                    and session_manager.get_session(session_id) is native_claim
                ):
                    session_manager.close_session(session_id)
                if (
                    not incumbent
                    and session_manager.get_session(session_id) is native_claim
                ):
                    raise RuntimeError("Marimo retained a rejected Studio session")
            finally:
                if admission.on_reject is not None:
                    admission.on_reject()
            return False
        if admission.on_accept is not None:
            admission.on_accept(native_claim)
    elif not accepted and admission.on_reject is not None:
        admission.on_reject()
    return accepted


def _disconnect_replacement(native_disconnect: Any) -> Any:
    from marimo._session.model import SessionMode

    @wraps(native_disconnect)
    def disconnect(
        handler: SessionHandler,
        error: Exception,
        cleanup: Callable[[], Any],
    ) -> None:
        connection = getattr(handler, "websocket", None) or getattr(
            handler, "request", None
        )
        admission = _scope_native_session_admission(getattr(connection, "scope", {}))
        session = (
            admission.expected_claim
            if admission is not None
            and admission.on_close is not None
            and admission.settled
            and not admission.rejected
            else None
        )

        def cleanup_and_notify() -> None:
            try:
                cleanup()
            finally:
                if session is not None:
                    asyncio.get_running_loop().call_soon(
                        _notify_closed_studio_session,
                        session,
                    )

        studio_ttl = (
            session is not None
            and handler.mode is SessionMode.EDIT
            and handler.manager.ttl_seconds is None
        )
        try:
            native_disconnect(
                handler,
                error,
                cleanup_and_notify if session is not None else cleanup,
            )
        finally:
            if studio_ttl:
                _schedule_studio_session_close(session)

    return disconnect


def _connect_kiosk_replacement(native_connect: Any) -> Any:
    from marimo._server.api.endpoints.ws.ws_session_connector import ConnectionType
    from marimo._server.codes import WebSocketCloseReason, WebSocketCodes
    from marimo._session.model import SessionMode

    @wraps(native_connect)
    def connect_existing(connector: SessionConnector) -> tuple[Any, ConnectionType]:
        query = connector.connection.query_params
        client_id = query.get(STUDIO_CLIENT_QUERY_PARAM)
        if not connector.params.kiosk:
            return native_connect(connector)
        if connector.manager.mode is not SessionMode.EDIT:
            raise _StudioSessionRejected(
                WebSocketCodes.FORBIDDEN,
                WebSocketCloseReason.KIOSK_NOT_ALLOWED,
            )
        if client_id is None:
            session = connector.manager.get_session(connector.params.session_id)
            if session is None:
                session = connector.manager.get_session_by_file_key(
                    connector.params.file_key
                )
            if session is not None and not _query_matches_session(connector, session):
                return connector._create_new_session()
            return native_connect(connector)
        with _ROUTERS_LOCK:
            router = _ROUTERS.get(connector.manager)
        session = router.resolve(connector.params.session_id) if router else None
        if session is None:
            raise _StudioSessionRejected(
                WebSocketCodes.NORMAL_CLOSE,
                WebSocketCloseReason.NO_SESSION,
            )
        if query.get(
            DOCUMENT_LIFECYCLE_QUERY_PARAM
        ) is None and not _query_matches_session(connector, session):
            return connector._create_new_session()
        connector.handler._connect_kiosk(session)
        return session, ConnectionType.KIOSK

    return connect_existing


def _start_replacement(native_start: Any) -> Any:
    @wraps(native_start)
    async def start(handler: WebSocketHandler) -> None:
        try:
            await native_start(handler)
        except _StudioSessionRejected as error:
            await handler._safe_close(error.code, error.reason or "")

    return start


def _safe_close_replacement(native_close: Any) -> Any:
    @wraps(native_close)
    async def safe_close(handler: WebSocketHandler, code: int, reason: str) -> None:
        websocket = handler.websocket
        if (
            websocket.client_state is WebSocketState.DISCONNECTED
            or websocket.application_state is WebSocketState.DISCONNECTED
        ):
            return
        try:
            await native_close(handler, code, reason)
        except WebSocketDisconnect:
            return

    return safe_close


_SESSION_CONNECT_PATCH = ReversiblePatch(
    "server-instance-routing",
    SessionConnector,
    "connect",
    _session_connect_replacement,
)
_KIOSK_CONNECT_PATCH = ReversiblePatch(
    "existing-session-attachment",
    SessionConnector,
    "_connect_kiosk",
    _connect_kiosk_replacement,
)
_START_PATCH = ReversiblePatch(
    "existing-session-rejection",
    WebSocketHandler,
    "start",
    _start_replacement,
)
_DISCONNECT_PATCH = ReversiblePatch(
    "studio-editor-session-ttl",
    SessionHandler,
    "_on_disconnect",
    _disconnect_replacement,
)
_SAFE_CLOSE_PATCH = ReversiblePatch(
    "websocket-close-disconnect",
    WebSocketHandler,
    "_safe_close",
    _safe_close_replacement,
)


class PrivateExistingSessionAttachment:
    """Own exact-session registrations for one Studio application lifespan."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._owner = object()
        self._managers: WeakKeyDictionary[Any, None] = WeakKeyDictionary()
        self._active = False
        self._closing = False
        self._close_lock = Lock()

    def open(self) -> CompositeCloseHandle:
        with _ROUTERS_LOCK:
            if self._active or self._closing:
                raise RuntimeError("The existing-session adapter is already open")
            self._active = True
        patches: list[CloseHandle] = []
        try:
            for patch in (
                _SESSION_CONNECT_PATCH,
                _KIOSK_CONNECT_PATCH,
                _START_PATCH,
                _DISCONNECT_PATCH,
                _SAFE_CLOSE_PATCH,
            ):
                patches.append(patch.open())
        except BaseException as setup_error:
            with _ROUTERS_LOCK:
                self._active = False
            try:
                CompositeCloseHandle(patches).close()
            except BaseException as cleanup_error:
                raise setup_error from cleanup_error
            raise
        if not _open_studio_session_lifetimes():
            with _ROUTERS_LOCK:
                self._active = False
            CompositeCloseHandle(patches).close()
            raise RuntimeError("Studio session lifetime cleanup is in progress")
        installed = CompositeCloseHandle(patches)
        cleanup = CallbackCloseHandle(self.close)

        def close_owned() -> None:
            cleanup.close()
            installed.close()

        return CompositeCloseHandle((CallbackCloseHandle(close_owned),))

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
            if not self._active or self._closing:
                return False
            router = _router(manager, self._clock)
            registered = router.register(self._owner, consumer_id, session)
            if registered:
                self._managers[manager] = None
            return registered

    def claim_editor_lifetime(self, context: ServerContext) -> object | None:
        manager = context_handle(context).session_manager
        with _ROUTERS_LOCK:
            if self._active and not self._closing:
                if not _track_manager_session_lifetimes(manager, self._owner):
                    return None
                self._managers[manager] = None
                return self._owner
            return None

    def close(self) -> None:
        with self._close_lock:
            with _ROUTERS_LOCK:
                if not self._active and not self._closing:
                    return
                self._closing = True
                managers = tuple(self._managers)
                for manager in managers:
                    router = _ROUTERS.get(manager)
                    if router is not None:
                        router.remove_owner(self._owner)
            for manager in managers:
                _close_manager_session_lifetimes(manager, self._owner)
            _close_studio_session_lifetimes()
            with _ROUTERS_LOCK:
                self._active = False
                self._closing = False
                self._managers.clear()
