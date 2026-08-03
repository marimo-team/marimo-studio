"""Enable Marimo session replay for opted-in Studio documents."""

from __future__ import annotations

from threading import Lock
from typing import Any
from weakref import WeakSet

from marimo_studio._compat.server.models import ServerContext

DOCUMENT_REPLAY_QUERY_PARAM = "marimo_studio_resume"

_DOCUMENT_REPLAY_MANAGERS: WeakSet[Any] = WeakSet()
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
        enabled = connector.manager in _DOCUMENT_REPLAY_MANAGERS
    if not requested or not enabled:
        return reconnect(connector, session)

    session.disconnect_main_consumer()
    connector.handler._reconnect_session(session, replay=True)
    return session, reconnect_type


def configure_document_replay(context: ServerContext, enabled: bool) -> None:
    """Configure session replay for documents served by this manager."""
    global _DOCUMENT_REPLAY_PATCHED

    with _DOCUMENT_REPLAY_LOCK:
        if enabled:
            _DOCUMENT_REPLAY_MANAGERS.add(context._session_manager)
        else:
            _DOCUMENT_REPLAY_MANAGERS.discard(context._session_manager)
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
