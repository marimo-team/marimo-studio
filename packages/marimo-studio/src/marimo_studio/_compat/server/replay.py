"""Enable Marimo session replay for opted-in Studio documents."""

from __future__ import annotations

from threading import Lock
from typing import Any
from weakref import WeakKeyDictionary

from marimo_studio._compat.server.models import ServerContext

DOCUMENT_REPLAY_QUERY_PARAM = "marimo_studio_resume"

_DOCUMENT_REPLAY_FILES: WeakKeyDictionary[Any, set[str]] = WeakKeyDictionary()
_DOCUMENT_REPLAY_LOCK = Lock()
_DOCUMENT_REPLAY_PATCHED = False


def _reconnect_with_document_replay(
    connector: Any,
    session: Any,
    reconnect: Any,
    reconnect_type: Any,
) -> tuple[Any, Any]:
    requested = (
        connector.connection.query_params.get(DOCUMENT_REPLAY_QUERY_PARAM) == "1"
    )
    with _DOCUMENT_REPLAY_LOCK:
        enabled = connector.params.file_key in _DOCUMENT_REPLAY_FILES.get(
            connector.manager,
            set(),
        )
    if not requested or not enabled:
        return reconnect(connector, session)

    session.disconnect_main_consumer()
    connector.handler._reconnect_session(session, replay=True)
    return session, reconnect_type


def configure_document_replay(context: ServerContext, enabled: bool) -> None:
    """Configure session replay for documents served by this manager."""
    global _DOCUMENT_REPLAY_PATCHED

    with _DOCUMENT_REPLAY_LOCK:
        files = _DOCUMENT_REPLAY_FILES.setdefault(context._session_manager, set())
        if enabled:
            files.add(context.file_key)
        else:
            files.discard(context.file_key)
            if not files:
                _DOCUMENT_REPLAY_FILES.pop(context._session_manager, None)
        if not enabled or _DOCUMENT_REPLAY_PATCHED:
            return

        from marimo._runtime.params import QueryParams
        from marimo._server.api.endpoints.ws.ws_session_connector import (
            ConnectionType,
            SessionConnector,
        )

        connector_class: Any = SessionConnector
        reconnect = connector_class._reconnect_session

        def reconnect_session(connector: Any, session: Any) -> tuple[Any, Any]:
            return _reconnect_with_document_replay(
                connector,
                session,
                reconnect,
                ConnectionType.RECONNECT,
            )

        connector_class._reconnect_session = reconnect_session
        QueryParams.IGNORED_KEYS.add(DOCUMENT_REPLAY_QUERY_PARAM)
        _DOCUMENT_REPLAY_PATCHED = True
