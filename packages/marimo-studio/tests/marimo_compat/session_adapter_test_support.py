from __future__ import annotations

from pathlib import Path
from threading import Event, RLock
from types import SimpleNamespace
from typing import Any, cast

from marimo._server.api.endpoints.ws.ws_session_connector import (
    ConnectionType,
    SessionConnector,
)
from marimo._session.model import ConnectionState, SessionMode
from starlette.datastructures import QueryParams

from marimo_studio._compat.server.existing_session import (
    PrivateExistingSessionAttachment,
)
from marimo_studio._compat.server.gateway import _ContextHandle
from marimo_studio._delivery.urls import STUDIO_CLIENT_QUERY_PARAM
from marimo_studio._server.ports import CloseHandle
from marimo_studio._server.records import ServerContext, ServerHandle


class Session:
    def __init__(
        self,
        file_key: str = "notebook.py",
        query: dict[str, str | list[str]] | None = None,
    ) -> None:
        self.ttl_seconds = 120
        self._connection_state = ConnectionState.CLOSED
        self.initialization_id = file_key
        self.app_file_manager = SimpleNamespace(path=Path(file_key))
        self.room = SimpleNamespace(consumers={})
        self._kernel_manager = SimpleNamespace(
            app_metadata=SimpleNamespace(query_params=query or {})
        )

    def connection_state(self) -> ConnectionState:
        return self._connection_state


class Manager:
    mode = SessionMode.EDIT

    def __init__(self) -> None:
        self.ttl_seconds: int | None = None
        self.sessions: dict[str, Session] = {}
        self.fallback: object | None = None
        self.fallback_calls = 0
        self.skew_protection_token = "token"

    def get_session(self, session_id: object) -> Session | None:
        return self.sessions.get(str(session_id))

    def get_session_by_file_key(self, _file_key: str) -> object | None:
        self.fallback_calls += 1
        return self.fallback

    def close_session(self, session_id: object) -> None:
        self.sessions.pop(str(session_id), None)


class ObservedRLock:
    def __init__(self) -> None:
        self._lock = RLock()
        self.contended = Event()

    def __enter__(self) -> ObservedRLock:
        if not self._lock.acquire(blocking=False):
            self.contended.set()
            self._lock.acquire()
        return self

    def __exit__(self, *_: object) -> None:
        self._lock.release()


def context(manager: Manager) -> ServerContext:
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


def connect(
    manager: Manager,
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
                kiosk=True,
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


def open_adapter(
    manager: Manager,
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
