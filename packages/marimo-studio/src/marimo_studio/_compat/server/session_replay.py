"""Replay opted-in Marimo sessions through a lifespan-owned patch."""

from __future__ import annotations

from pathlib import Path
from threading import RLock
from typing import Any
from weakref import WeakKeyDictionary

from marimo._runtime.params import QueryParams
from marimo._server.api.endpoints.ws.ws_session_connector import SessionConnector

from marimo_studio._compat.patch import (
    CallbackCloseHandle,
    CompositeCloseHandle,
    ReversiblePatch,
)
from marimo_studio._compat.server.gateway import context_handle
from marimo_studio._compat.server.session_state import session_matches_notebook
from marimo_studio._delivery.urls import DOCUMENT_REPLAY_QUERY_PARAM
from marimo_studio._server.records import ServerContext
from marimo_studio.errors._internal import CompatibilityError

_FILES: WeakKeyDictionary[Any, dict[str, dict[object, Path]]] = WeakKeyDictionary()
_LOCK = RLock()


def _reconnect_replacement(native_reconnect: Any) -> Any:
    from marimo._server.api.endpoints.ws.ws_session_connector import ConnectionType

    def reconnect(connector: Any, session: Any) -> tuple[Any, Any]:
        requested = (
            connector.connection.query_params.get(DOCUMENT_REPLAY_QUERY_PARAM) == "1"
        )
        with _LOCK:
            registrations = _FILES.get(connector.manager, {}).get(
                connector.params.file_key,
                {},
            )
            replay = any(
                session_matches_notebook(
                    session,
                    file_key=connector.params.file_key,
                    notebook=notebook,
                )
                for notebook in registrations.values()
            )
        if not requested or not replay:
            return native_reconnect(connector, session)
        session.disconnect_main_consumer()
        connector.handler._reconnect_session(session, replay=True)
        return session, ConnectionType.RECONNECT

    return reconnect


_RECONNECT_PATCH = ReversiblePatch(
    "session-replay",
    SessionConnector,
    "_reconnect_session",
    _reconnect_replacement,
)


class _ReplayInstallation:
    def __init__(self) -> None:
        self._lock = RLock()
        self._users = 0
        self._patch: CallbackCloseHandle | None = None

    def open(self) -> CallbackCloseHandle:
        with self._lock:
            if self._users == 0:
                if DOCUMENT_REPLAY_QUERY_PARAM in QueryParams.IGNORED_KEYS:
                    raise CompatibilityError(
                        "Another owner registered the Studio session replay query key."
                    )
                patch = _RECONNECT_PATCH.open()
                try:
                    QueryParams.IGNORED_KEYS.add(DOCUMENT_REPLAY_QUERY_PARAM)
                except BaseException:
                    patch.close()
                    raise
                self._patch = patch
            self._users += 1
        return CallbackCloseHandle(self._release)

    def _release(self) -> None:
        with self._lock:
            if self._users <= 0:
                raise RuntimeError("Unbalanced session replay release")
            if self._users > 1:
                self._users -= 1
                return
            if DOCUMENT_REPLAY_QUERY_PARAM not in QueryParams.IGNORED_KEYS:
                raise CompatibilityError(
                    "Another owner removed the Studio session replay query key."
                )
            patch = self._patch
            assert patch is not None
            patch.close()
            QueryParams.IGNORED_KEYS.remove(DOCUMENT_REPLAY_QUERY_PARAM)
            self._users = 0
            self._patch = None


_INSTALLATION = _ReplayInstallation()


class PrivateSessionReplay:
    """Own replay registrations for one Studio application lifespan."""

    def __init__(self) -> None:
        self._owner = object()
        self._managers: WeakKeyDictionary[Any, None] = WeakKeyDictionary()

    def open(self) -> CompositeCloseHandle:
        return CompositeCloseHandle(
            (
                _INSTALLATION.open(),
                CallbackCloseHandle(self.close),
            )
        )

    def configure(self, context: ServerContext, enabled: bool) -> None:
        manager = context_handle(context).session_manager
        with _LOCK:
            files = _FILES.setdefault(manager, {})
            owners = files.setdefault(context.file_key, {})
            if enabled:
                owners[self._owner] = context.notebook
                self._managers[manager] = None
                return
            owners.pop(self._owner, None)
            if not owners:
                files.pop(context.file_key, None)
            if not files:
                _FILES.pop(manager, None)

    def close(self) -> None:
        with _LOCK:
            for manager in tuple(self._managers):
                files = _FILES.get(manager)
                if files is None:
                    continue
                for file_key, owners in tuple(files.items()):
                    owners.pop(self._owner, None)
                    if not owners:
                        files.pop(file_key, None)
                if not files:
                    _FILES.pop(manager, None)
            self._managers.clear()
