"""Protect Marimo session replay integration."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import Mock

import pytest
from marimo._runtime.params import QueryParams as RuntimeQueryParams
from marimo._server.api.endpoints.ws.ws_session_connector import (
    ConnectionType,
    SessionConnector,
)
from starlette.datastructures import QueryParams

from marimo_studio._compat.server.gateway import _ContextHandle
from marimo_studio._compat.server.session_replay import (
    DOCUMENT_REPLAY_QUERY_PARAM,
    PrivateSessionReplay,
)
from marimo_studio._server.records import ServerContext, ServerHandle
from marimo_studio.errors._internal import CompatibilityError


def test_replay_configuration_uses_the_gateway_canonical_notebook() -> None:
    class Manager:
        pass

    class CanonicalNotebook:
        def resolve(self) -> None:
            raise AssertionError("canonical notebook paths must not be resolved here")

    manager = Manager()
    context = cast(
        ServerContext,
        SimpleNamespace(
            file_key="analysis.py",
            handle=ServerHandle(_ContextHandle(server=None, session_manager=manager)),
            notebook=CanonicalNotebook(),
        ),
    )
    replay = PrivateSessionReplay()

    replay.configure(context, True)
    replay.configure(context, False)


def test_document_replay_requires_an_opted_in_manager_and_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Manager:
        pass

    manager = Manager()
    other_manager = Manager()
    session = SimpleNamespace(
        initialization_id="analysis.py",
        app_file_manager=SimpleNamespace(path=Path("analysis.py")),
        disconnect_main_consumer=Mock(),
        connect_consumer=Mock(),
    )
    handler = SimpleNamespace(
        cancel_close_handle=None,
        params=SimpleNamespace(kiosk=False),
        _write_kernel_ready_from_session_view=Mock(),
        _replay_previous_session=Mock(),
    )
    reconnect = Mock(return_value=("fallback", "new"))
    monkeypatch.setattr(SessionConnector, "_reconnect_session", reconnect)
    replay = PrivateSessionReplay()
    handle = replay.open()

    def context(
        active_manager: Manager, file_key: str = "analysis.py"
    ) -> ServerContext:
        return ServerContext(
            notebook=Path(file_key).resolve(),
            file_key=file_key,
            base_url="",
            internal_url=None,
            mode="run",
            dev=False,
            routing_query=(),
            user_config={},
            config_overrides={},
            server_token="",
            handle=ServerHandle(
                _ContextHandle(server=None, session_manager=active_manager)
            ),
        )

    replay.configure(context(manager), True)

    def connector(
        active_manager: Manager,
        requested: bool,
        file_key: str = "analysis.py",
    ) -> SessionConnector:
        query = {DOCUMENT_REPLAY_QUERY_PARAM: "1"} if requested else {}
        return SessionConnector(
            manager=cast(Any, active_manager),
            params=cast(Any, SimpleNamespace(file_key=file_key)),
            connection=cast(
                Any,
                SimpleNamespace(query_params=QueryParams(query)),
            ),
            handler=cast(Any, handler),
        )

    try:
        assert connector(manager, True)._reconnect_session(cast(Any, session)) == (
            session,
            ConnectionType.RECONNECT,
        )
        assert connector(manager, False)._reconnect_session(cast(Any, session)) == (
            "fallback",
            "new",
        )
        assert connector(other_manager, True)._reconnect_session(
            cast(Any, session)
        ) == (
            "fallback",
            "new",
        )
        assert connector(manager, True, "other.py")._reconnect_session(
            cast(Any, session)
        ) == (
            "fallback",
            "new",
        )

        session.disconnect_main_consumer.assert_called_once_with()
        session.connect_consumer.assert_called_once_with(handler, main=True)
        handler._write_kernel_ready_from_session_view.assert_called_once_with(
            session, False
        )
        handler._replay_previous_session.assert_called_once_with(session)
    finally:
        handle.close()


def test_document_replay_requires_the_session_to_match_the_registered_notebook(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Manager:
        pass

    manager = Manager()
    session = SimpleNamespace(
        initialization_id="first.py",
        app_file_manager=SimpleNamespace(path=Path("first.py")),
        disconnect_main_consumer=Mock(),
    )
    handler = SimpleNamespace(_reconnect_session=Mock())
    reconnect = Mock(return_value=("fallback", "native"))
    monkeypatch.setattr(SessionConnector, "_reconnect_session", reconnect)
    replay = PrivateSessionReplay()
    handle = replay.open()
    context = ServerContext(
        notebook=Path("second.py").resolve(),
        file_key="second.py",
        base_url="",
        internal_url=None,
        mode="run",
        dev=False,
        routing_query=(),
        user_config={},
        config_overrides={},
        server_token="",
        handle=ServerHandle(_ContextHandle(server=None, session_manager=manager)),
    )
    replay.configure(context, True)
    connector = SessionConnector(
        manager=cast(Any, manager),
        params=cast(
            Any,
            SimpleNamespace(file_key="second.py"),
        ),
        connection=cast(
            Any,
            SimpleNamespace(
                query_params=QueryParams({DOCUMENT_REPLAY_QUERY_PARAM: "1"}),
            ),
        ),
        handler=cast(Any, handler),
    )

    try:
        assert connector._reconnect_session(cast(Any, session)) == (
            "fallback",
            "native",
        )
        reconnect.assert_called_once_with(connector, session)
        session.disconnect_main_consumer.assert_not_called()
        handler._reconnect_session.assert_not_called()
    finally:
        handle.close()


def test_document_replay_restores_process_state_after_the_final_owner() -> None:
    original = SessionConnector._reconnect_session
    first_handle = PrivateSessionReplay().open()
    replacement = SessionConnector._reconnect_session
    second_handle = PrivateSessionReplay().open()

    try:
        assert DOCUMENT_REPLAY_QUERY_PARAM in RuntimeQueryParams.IGNORED_KEYS
        first_handle.close()
        assert SessionConnector._reconnect_session is replacement
        assert DOCUMENT_REPLAY_QUERY_PARAM in RuntimeQueryParams.IGNORED_KEYS

        second_handle.close()
        assert SessionConnector._reconnect_session is original
        assert DOCUMENT_REPLAY_QUERY_PARAM not in RuntimeQueryParams.IGNORED_KEYS
    finally:
        try:
            first_handle.close()
        finally:
            second_handle.close()


def test_document_replay_retries_after_query_registration_conflict() -> None:
    original = SessionConnector._reconnect_session
    handle = PrivateSessionReplay().open()
    replacement = SessionConnector._reconnect_session

    try:
        RuntimeQueryParams.IGNORED_KEYS.remove(DOCUMENT_REPLAY_QUERY_PARAM)
        with pytest.raises(CompatibilityError, match="removed"):
            handle.close()

        assert SessionConnector._reconnect_session is replacement
        RuntimeQueryParams.IGNORED_KEYS.add(DOCUMENT_REPLAY_QUERY_PARAM)
        handle.close()
        assert SessionConnector._reconnect_session is original
        assert DOCUMENT_REPLAY_QUERY_PARAM not in RuntimeQueryParams.IGNORED_KEYS
    finally:
        if SessionConnector._reconnect_session is replacement:
            RuntimeQueryParams.IGNORED_KEYS.add(DOCUMENT_REPLAY_QUERY_PARAM)
            handle.close()
        else:
            RuntimeQueryParams.IGNORED_KEYS.discard(DOCUMENT_REPLAY_QUERY_PARAM)


def test_document_replay_retries_after_patch_restoration_conflict() -> None:
    original = SessionConnector._reconnect_session
    handle = PrivateSessionReplay().open()
    replacement = SessionConnector._reconnect_session

    def foreign(connector: object, session: object) -> tuple[object, object]:
        return connector, session

    cast(Any, SessionConnector)._reconnect_session = foreign
    try:
        with pytest.raises(CompatibilityError, match="before Studio could restore"):
            handle.close()

        assert DOCUMENT_REPLAY_QUERY_PARAM in RuntimeQueryParams.IGNORED_KEYS
        cast(Any, SessionConnector)._reconnect_session = replacement
        handle.close()
        assert SessionConnector._reconnect_session is original
        assert DOCUMENT_REPLAY_QUERY_PARAM not in RuntimeQueryParams.IGNORED_KEYS
    finally:
        cast(Any, SessionConnector)._reconnect_session = original
        RuntimeQueryParams.IGNORED_KEYS.discard(DOCUMENT_REPLAY_QUERY_PARAM)
