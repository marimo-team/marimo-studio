from __future__ import annotations

import asyncio
from importlib.metadata import entry_points
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from urllib.parse import urlencode

import pytest
from starlette.middleware import Middleware
from starlette.testclient import TestClient

import marimo_studio._compat.server.session_state as session_state_module
from marimo_studio._compat.server.existing_session import (
    PrivateExistingSessionAttachment,
)
from marimo_studio._compat.server.session_state import PrivateSessionState
from marimo_studio._delivery.urls import (
    SERVER_INSTANCE_QUERY_PARAM,
)
from marimo_studio._server.presentation.ports import ProjectionUnavailable
from marimo_studio._server.server_instance import server_instance_id
from marimo_studio.errors._internal import RuntimeStartupError

from ..app_helpers import configured as _configured
from ..app_helpers import edit_mode as _edit_mode
from ..app_helpers import marimo_app as _marimo_app
from ..app_helpers import session_manager as _session_manager


def test_studio_session_runs_after_native_instantiation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from marimo._runtime.commands import ExecuteStaleCellsCommand
    from marimo._session.types import KernelState

    class Session:
        def __init__(self) -> None:
            self.document = SimpleNamespace(
                cells=[
                    SimpleNamespace(id="cell-1", code="value = 1"),
                    SimpleNamespace(id="browser-omitted", code="hidden = 2"),
                ]
            )
            self.session_view = SimpleNamespace(last_executed_code={})
            self.requests: list[tuple[object, object | None]] = []
            self.instantiations: list[tuple[object, object | None]] = []

        @staticmethod
        def kernel_exit_info() -> None:
            return None

        @staticmethod
        def kernel_state() -> KernelState:
            return KernelState.RUNNING

        def put_control_request(
            self,
            request: object,
            *,
            from_consumer_id: object | None,
        ) -> None:
            self.requests.append((request, from_consumer_id))

        def instantiate(self, request: object, *, http_request: object | None) -> None:
            self.instantiations.append((request, http_request))

    session: Any = Session()
    monkeypatch.setattr(
        session_state_module,
        "current_session",
        lambda *_args: session,
    )
    barriers = 0
    completed = asyncio.Event()

    async def read_barrier(*_args: object, **_kwargs: object) -> object:
        nonlocal barriers
        barriers += 1
        completed.set()
        return object()

    monkeypatch.setattr(session_state_module, "read_session_values", read_barrier)
    context: Any = SimpleNamespace()
    state = PrivateSessionState()

    async def exercise() -> None:
        assert state.ensure_started(context, "s_123456") is False
        session.session_view.last_executed_code = {"cell-1": "value = 1"}
        assert state.ensure_started(context, "s_123456") is False
        task = state._starting[session]
        await asyncio.wait_for(completed.wait(), timeout=1)
        await asyncio.wait_for(task, timeout=1)
        callback_turn = asyncio.Event()
        asyncio.get_running_loop().call_soon(callback_turn.set)
        await asyncio.wait_for(callback_turn.wait(), timeout=1)
        assert state.ensure_started(context, "s_123456") is True

    asyncio.run(exercise())

    assert len(session.requests) == 1
    assert len(session.instantiations) == 1
    assert session.instantiations[0][1] is None
    assert barriers == 1
    request, consumer_id = session.requests[0]
    assert isinstance(request, ExecuteStaleCellsCommand)
    assert consumer_id is None


def test_studio_startup_retries_for_a_new_exact_editor_consumer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from marimo._session.types import KernelState

    class Session:
        def __init__(self) -> None:
            self.document = SimpleNamespace(
                cells=[SimpleNamespace(id="cell-1", code="value = 1")]
            )
            self.session_view = SimpleNamespace(last_executed_code={})
            self.instantiations = 0
            self.requests = 0

        def instantiate(self, _request: object, *, http_request: object | None) -> None:
            assert http_request is None
            self.instantiations += 1

        @staticmethod
        def kernel_state() -> KernelState:
            return KernelState.RUNNING

        @staticmethod
        def kernel_exit_info() -> None:
            return None

        def put_control_request(self, *_args: object, **_kwargs: object) -> None:
            self.requests += 1

    session: Any = Session()
    now = 10.0
    monkeypatch.setattr(
        session_state_module,
        "current_session",
        lambda *_args: session,
    )
    monkeypatch.setattr(session_state_module, "monotonic", lambda: now)
    monkeypatch.setattr(
        session_state_module,
        "_NATIVE_INSTANTIATION_TIMEOUT_SECONDS",
        1.0,
    )
    state = PrivateSessionState()
    context: Any = SimpleNamespace()

    assert state.ensure_started(context, "s_123456") is False
    assert session.instantiations == 1
    now = 11.0
    with pytest.raises(RuntimeStartupError, match="did not initialize"):
        state.ensure_started(context, "s_123456")
    with pytest.raises(RuntimeStartupError, match="did not initialize"):
        state.ensure_started(context, "s_123456")
    assert not state.retry_startup(context, "s_123456", object())
    assert state.retry_startup(context, "s_123456", session)
    assert not state.retry_startup(context, "s_123456", session)
    session.session_view.last_executed_code = {"cell-1": "value = 1"}
    completed = asyncio.Event()

    async def read_barrier(*_args: object, **_kwargs: object) -> object:
        completed.set()
        return object()

    monkeypatch.setattr(session_state_module, "read_session_values", read_barrier)

    async def retry() -> None:
        assert state.ensure_started(context, "s_123456") is False
        task = state._starting[session]
        await asyncio.wait_for(completed.wait(), timeout=1)
        await asyncio.wait_for(task, timeout=1)
        callback_turn = asyncio.Event()
        asyncio.get_running_loop().call_soon(callback_turn.set)
        await asyncio.wait_for(callback_turn.wait(), timeout=1)
        assert state.ensure_started(context, "s_123456") is True

    asyncio.run(retry())
    assert session.requests == 1
    assert session.instantiations == 1


def test_studio_startup_reports_a_stopped_kernel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Session:
        def __init__(self) -> None:
            self.document = SimpleNamespace(
                cells=[SimpleNamespace(id="cell-1", code="value = 1")]
            )
            self.session_view = SimpleNamespace(
                last_executed_code={"cell-1": "value = 1"}
            )
            self.requests = 0

        def kernel_exit_info(self) -> object | None:
            return (
                SimpleNamespace(message="The kernel stopped during startup.")
                if barriers == 1
                else None
            )

        def put_control_request(self, *_args: object, **_kwargs: object) -> None:
            self.requests += 1

    barriers = 0
    session: Any = Session()
    monkeypatch.setattr(
        session_state_module,
        "current_session",
        lambda *_args: session,
    )

    async def read_barrier(*_args: object, **_kwargs: object) -> object:
        nonlocal barriers
        barriers += 1
        if barriers == 1:
            await asyncio.Event().wait()
        return object()

    monkeypatch.setattr(session_state_module, "read_session_values", read_barrier)
    context: Any = SimpleNamespace()
    state = PrivateSessionState()

    async def exercise() -> None:
        assert state.ensure_started(context, "s_123456") is False
        task = state._starting[session]
        with pytest.raises(RuntimeStartupError, match="kernel stopped"):
            await asyncio.wait_for(task, timeout=1)
        callback_turn = asyncio.Event()
        asyncio.get_running_loop().call_soon(callback_turn.set)
        await asyncio.wait_for(callback_turn.wait(), timeout=1)
        with pytest.raises(RuntimeStartupError, match="kernel stopped"):
            state.ensure_started(context, "s_123456")

    asyncio.run(exercise())

    assert barriers == 1
    assert session.requests == 1


def test_studio_startup_retries_a_transient_barrier_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Session:
        def __init__(self) -> None:
            self.document = SimpleNamespace(
                cells=[SimpleNamespace(id="cell-1", code="value = 1")]
            )
            self.session_view = SimpleNamespace(
                last_executed_code={"cell-1": "value = 1"}
            )
            self.requests = 0

        @staticmethod
        def kernel_exit_info() -> None:
            return None

        def put_control_request(self, *_args: object, **_kwargs: object) -> None:
            self.requests += 1

    barriers = 0
    session: Any = Session()
    monkeypatch.setattr(
        session_state_module,
        "current_session",
        lambda *_args: session,
    )

    async def read_barrier(*_args: object, **_kwargs: object) -> object:
        nonlocal barriers
        barriers += 1
        if barriers == 1:
            raise ProjectionUnavailable(
                "consumer-unavailable",
                "The editor connection changed during startup.",
                transient=True,
                status_code=409,
            )
        return object()

    monkeypatch.setattr(session_state_module, "read_session_values", read_barrier)
    context: Any = SimpleNamespace()
    state = PrivateSessionState()

    async def exercise() -> None:
        assert state.ensure_started(context, "s_123456") is False
        first = state._starting[session]
        with pytest.raises(ProjectionUnavailable):
            await asyncio.wait_for(first, timeout=1)
        first_callback = asyncio.Event()
        asyncio.get_running_loop().call_soon(first_callback.set)
        await asyncio.wait_for(first_callback.wait(), timeout=1)

        assert state.ensure_started(context, "s_123456") is False
        second = state._starting[session]
        await asyncio.wait_for(second, timeout=1)
        second_callback = asyncio.Event()
        asyncio.get_running_loop().call_soon(second_callback.set)
        await asyncio.wait_for(second_callback.wait(), timeout=1)
        assert state.ensure_started(context, "s_123456") is True

    asyncio.run(exercise())

    assert barriers == 2
    assert session.requests == 2


def test_session_state_close_cancels_a_pending_startup_barrier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Session:
        def __init__(self) -> None:
            self.document = SimpleNamespace(
                cells=[SimpleNamespace(id="cell-1", code="value = 1")]
            )
            self.session_view = SimpleNamespace(
                last_executed_code={"cell-1": "value = 1"}
            )

        @staticmethod
        def kernel_exit_info() -> None:
            return None

        @staticmethod
        def put_control_request(*_args: object, **_kwargs: object) -> None:
            return None

    session: Any = Session()
    monkeypatch.setattr(
        session_state_module,
        "current_session",
        lambda *_args: session,
    )
    state = PrivateSessionState()
    context: Any = SimpleNamespace()

    async def exercise() -> None:
        started = asyncio.Event()
        cancelled = asyncio.Event()

        async def read_barrier(*_args: object, **_kwargs: object) -> object:
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

        monkeypatch.setattr(session_state_module, "read_session_values", read_barrier)
        assert state.ensure_started(context, "s_123456") is False
        await asyncio.wait_for(started.wait(), timeout=1)

        await asyncio.wait_for(state.close(), timeout=1)

        assert cancelled.is_set()
        with pytest.raises(RuntimeStartupError, match="shutting down"):
            state.ensure_started(context, "s_123456")

    asyncio.run(exercise())


def test_package_registers_marimo_extension_points() -> None:
    server = {
        point.name: point.load()
        for point in entry_points(group="marimo.server.asgi.middleware")
    }
    kernel = {
        point.name: point.load()
        for point in entry_points(group="marimo.kernel.lifespan")
    }

    assert isinstance(server["marimo-studio"], Middleware)
    assert callable(kernel["marimo-studio"])


def test_session_id_validation_tracks_marimos_server_boundary() -> None:
    sessions = PrivateSessionState()
    assert sessions.is_session_id("s_abc123")
    assert not sessions.is_session_id("s_ABC123")
    assert not sessions.is_session_id("s_short")
    assert not sessions.is_session_id(None)


def test_stale_studio_preview_receives_terminal_session_close(
    notebook_path: Path,
) -> None:
    studio = _configured(notebook_path)
    app = _marimo_app(studio.notebook)
    _edit_mode(app)
    manager = _session_manager(app)
    query = urlencode(
        {
            "session_id": "s_stale1",
            "kiosk": "true",
            "marimo_studio_client": "browser-client-1234",
            SERVER_INSTANCE_QUERY_PARAM: server_instance_id(
                str(manager.skew_protection_token)
            ),
        }
    )

    attachment = PrivateExistingSessionAttachment()
    handle = attachment.open()
    try:
        with (
            TestClient(app) as client,
            client.websocket_connect(f"/ws?{query}") as websocket,
        ):
            close = websocket.receive()
    finally:
        handle.close()

    assert close == {
        "type": "websocket.close",
        "code": 1000,
        "reason": "MARIMO_NO_SESSION",
    }


def test_stale_studio_editor_does_not_create_a_session(
    notebook_path: Path,
) -> None:
    studio = _configured(notebook_path)
    app = _marimo_app(studio.notebook)
    _edit_mode(app)
    manager = _session_manager(app)
    query = urlencode(
        {
            "session_id": "s_stale1",
            "marimo_studio_client": "browser-client-1234",
            SERVER_INSTANCE_QUERY_PARAM: "stale-server",
        }
    )

    attachment = PrivateExistingSessionAttachment()
    handle = attachment.open()
    try:
        with (
            TestClient(app) as client,
            client.websocket_connect(f"/ws?{query}") as websocket,
        ):
            close = websocket.receive()
    finally:
        handle.close()

    assert close == {
        "type": "websocket.close",
        "code": 1000,
        "reason": "MARIMO_NO_SESSION",
    }
    assert manager.get_session("s_stale1") is None


def test_stale_development_stream_stops_reconnecting(
    notebook_path: Path,
) -> None:
    studio = _configured(notebook_path)
    app = _marimo_app(studio.notebook)
    _edit_mode(app)

    with TestClient(app) as client:
        response = client.get(
            "/_marimo-studio/views/dashboard/dev/events",
            params={SERVER_INSTANCE_QUERY_PARAM: "stale-server"},
        )

    assert response.status_code == 204
