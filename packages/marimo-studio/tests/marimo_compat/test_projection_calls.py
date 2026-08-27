from __future__ import annotations

import asyncio
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

import marimo_studio._compat.kernel_values.query as kernel_query_module
import marimo_studio._compat.kernel_values.session as kernel_session_module
from marimo_studio._compat.kernel_values import (
    read_session_values,
    render_session_outputs,
)
from marimo_studio._compat.kernel_values.query_authorization import (
    authorized_query_arguments,
)
from marimo_studio._compat.kernel_values.session import _FunctionResultWaiter
from marimo_studio._server.presentation.ports import (
    ProjectionUnavailable,
    QuerySyncUnavailable,
)
from marimo_studio._server.presentation.query_state import query_fingerprint

from .values_test_support import (
    _bound_projection,
)


def test_query_sync_waits_for_a_matching_kernel_acknowledgement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from marimo._messaging.notification import (
        ConsumerCapabilities,
        FunctionCallResultNotification,
        HumanReadableStatus,
    )
    from marimo._messaging.serde import serialize_kernel_message
    from marimo._types.ids import ConsumerId

    class Consumer:
        consumer_id = ConsumerId("editor")

    consumer = Consumer()

    class Room:
        main_consumer = consumer

        @staticmethod
        def get_consumer(consumer_id: ConsumerId) -> object | None:
            return consumer if consumer_id == consumer.consumer_id else None

        @staticmethod
        def get_capabilities(current: object) -> ConsumerCapabilities:
            assert current is consumer
            return ConsumerCapabilities.EDITOR

    class Session:
        room = Room()

        def __init__(self) -> None:
            self.waiter: _FunctionResultWaiter | None = None
            self.request: Any | None = None

        @contextmanager
        def scoped(self, waiter: _FunctionResultWaiter):
            self.waiter = waiter
            yield

        def put_control_request(self, request: Any, **_kwargs: object) -> None:
            self.request = request
            assert self.waiter is not None
            fingerprint = query_fingerprint({"region": "emea"})
            self.waiter.on_notification_sent(
                self,
                serialize_kernel_message(
                    FunctionCallResultNotification(
                        function_call_id=request.function_call_id,
                        return_value={
                            "operation_id": "query-1",
                            "fingerprint": fingerprint,
                            "binding_generation": 3,
                            "query_generation": 7,
                            "deadline": 9_000_000_000.0,
                            "status": "applied",
                        },
                        status=HumanReadableStatus(code="ok"),
                        found=True,
                    )
                ),
            )

    session = Session()
    monkeypatch.setattr(
        kernel_query_module,
        "current_session",
        lambda _context, session_id: session if session_id == "s_123456" else None,
    )

    asyncio.run(
        kernel_query_module.sync_query_state(
            cast(Any, SimpleNamespace(notebook=Path("/tmp/notebook.py"))),
            "s_123456",
            {"region": "emea"},
            "query-1",
            binding_generation=3,
            query_generation=7,
            deadline=9_000_000_000.0,
        )
    )

    assert session.request is not None
    assert session.request.function_name == "sync_query"
    assert session.request.args == authorized_query_arguments(
        query={"region": "emea"},
        operation_id="query-1",
        fingerprint=query_fingerprint({"region": "emea"}),
        binding_generation=3,
        query_generation=7,
        deadline=9_000_000_000.0,
        session_id="s_123456",
        notebook=Path("/tmp/notebook.py"),
    )


def test_timed_out_query_remains_owned_until_the_kernel_terminal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from marimo._messaging.notification import (
        ConsumerCapabilities,
        FunctionCallResultNotification,
        HumanReadableStatus,
    )
    from marimo._messaging.serde import serialize_kernel_message
    from marimo._types.ids import ConsumerId

    class Consumer:
        consumer_id = ConsumerId("editor")

        def on_detach(self) -> None:
            return None

    consumer = Consumer()

    class Room:
        main_consumer = consumer

        @staticmethod
        def get_consumer(consumer_id: ConsumerId) -> object | None:
            return consumer if consumer_id == consumer.consumer_id else None

        @staticmethod
        def get_capabilities(current: object) -> ConsumerCapabilities:
            assert current is consumer
            return ConsumerCapabilities.EDITOR

    class Session:
        room = Room()

        def __init__(self) -> None:
            self.waiter: _FunctionResultWaiter | None = None
            self.request: Any | None = None

        @contextmanager
        def scoped(self, waiter: _FunctionResultWaiter):
            self.waiter = waiter
            yield

        def put_control_request(self, request: Any, **_kwargs: object) -> None:
            self.request = request

    async def exercise() -> None:
        session = Session()
        monkeypatch.setattr(kernel_query_module, "_QUERY_SYNC_TIMEOUT_SECONDS", 0.01)
        monkeypatch.setattr(
            kernel_query_module,
            "current_session",
            lambda _context, session_id: session if session_id == "s_123456" else None,
        )
        deadline = 9_000_000_000.0
        with pytest.raises(QuerySyncUnavailable) as raised:
            await kernel_query_module.sync_query_state(
                cast(Any, SimpleNamespace(notebook=Path("/tmp/notebook.py"))),
                "s_123456",
                {"region": "emea"},
                "query-1",
                binding_generation=3,
                query_generation=7,
                deadline=deadline,
            )
        terminal = raised.value.terminal
        assert terminal is not None
        assert session.waiter is not None
        assert terminal is session.waiter.terminal
        assert session.request is not None
        consumer.on_detach()
        assert isinstance(terminal, asyncio.Future)
        assert not terminal.done()

        result = {
            "operation_id": "query-1",
            "fingerprint": query_fingerprint({"region": "emea"}),
            "binding_generation": 3,
            "query_generation": 7,
            "deadline": deadline,
            "status": "expired",
        }
        session.waiter.on_notification_sent(
            session,
            serialize_kernel_message(
                FunctionCallResultNotification(
                    function_call_id=session.request.function_call_id,
                    return_value=result,
                    status=HumanReadableStatus(code="ok"),
                    found=True,
                )
            ),
        )
        assert await terminal == result

    asyncio.run(exercise())


def test_kernel_value_read_rejects_a_viewer_before_dispatch() -> None:
    from marimo._messaging.notification import ConsumerCapabilities
    from marimo._types.ids import ConsumerId

    consumer = object()

    class ViewerRoom:
        @staticmethod
        def get_consumer(consumer_id: ConsumerId) -> object | None:
            return consumer if consumer_id == ConsumerId("viewer") else None

        @staticmethod
        def get_capabilities(current: object) -> ConsumerCapabilities:
            assert current is consumer
            return ConsumerCapabilities.VIEWER

    class ViewerSession:
        room = ViewerRoom()

        @staticmethod
        def put_control_request(*_: object, **__: object) -> None:
            raise AssertionError("viewer request reached the kernel queue")

    with pytest.raises(ProjectionUnavailable) as raised:
        asyncio.run(
            read_session_values(
                ViewerSession(),
                "revision-1",
                (_bound_projection("context.good"),),
                consumer_id="viewer",
            )
        )

    assert raised.value.code == "interaction-forbidden"
    assert raised.value.status_code == 403


def test_output_timeout_is_terminal_after_one_kernel_dispatch() -> None:
    from marimo._messaging.notification import ConsumerCapabilities
    from marimo._types.ids import ConsumerId

    consumer = object()

    class Room:
        @staticmethod
        def get_consumer(consumer_id: ConsumerId) -> object | None:
            return consumer if consumer_id == ConsumerId("editor") else None

        @staticmethod
        def get_capabilities(current: object) -> ConsumerCapabilities:
            assert current is consumer
            return ConsumerCapabilities.EDITOR

    class Session:
        room = Room()
        dispatched = 0

        @staticmethod
        @contextmanager
        def scoped(_: object):
            yield

        def put_control_request(self, *_: object, **__: object) -> None:
            self.dispatched += 1

    session = Session()
    with pytest.raises(ProjectionUnavailable) as raised:
        asyncio.run(
            render_session_outputs(
                session,
                "revision-1",
                (_bound_projection("summary", "output"),),
                (_bound_projection("summary", "output"),),
                consumer_id="editor",
                timeout=0,
            )
        )

    assert session.dispatched == 1
    assert raised.value.code == "output-read-timeout"
    assert raised.value.transient is False


def test_timed_out_projection_calls_cannot_grow_the_session_backlog(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from marimo._messaging.notification import ConsumerCapabilities
    from marimo._types.ids import ConsumerId

    consumer = object()

    class Room:
        @staticmethod
        def get_consumer(consumer_id: ConsumerId) -> object | None:
            return consumer if consumer_id == ConsumerId("editor") else None

        @staticmethod
        def get_capabilities(current: object) -> ConsumerCapabilities:
            assert current is consumer
            return ConsumerCapabilities.EDITOR

    class Session:
        room = Room()

        def __init__(self) -> None:
            self.dispatched = 0

        @staticmethod
        @contextmanager
        def scoped(_: object):
            yield

        def put_control_request(self, *_: object, **__: object) -> None:
            self.dispatched += 1

    monkeypatch.setattr(kernel_session_module, "MAX_SESSION_PROJECTION_WORK", 2)
    session = Session()

    async def exhaust() -> ProjectionUnavailable:
        for _index in range(2):
            with pytest.raises(ProjectionUnavailable) as timed_out:
                await read_session_values(
                    session,
                    "revision-1",
                    (_bound_projection("summary"),),
                    consumer_id="editor",
                    timeout=0,
                )
            assert timed_out.value.code == "read-timeout"
        with pytest.raises(ProjectionUnavailable) as limited:
            await read_session_values(
                session,
                "revision-1",
                (_bound_projection("summary"),),
                consumer_id="editor",
                timeout=0,
            )
        return limited.value

    error = asyncio.run(exhaust())

    assert session.dispatched == 2
    assert error.code == "projection-work-limit"
    assert error.status_code == 429
    assert error.transient is True


def test_cancelled_projection_calls_retain_session_backlog_ownership(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from marimo._messaging.notification import ConsumerCapabilities
    from marimo._types.ids import ConsumerId

    consumer = object()

    class Room:
        @staticmethod
        def get_consumer(consumer_id: ConsumerId) -> object | None:
            return consumer if consumer_id == ConsumerId("editor") else None

        @staticmethod
        def get_capabilities(current: object) -> ConsumerCapabilities:
            assert current is consumer
            return ConsumerCapabilities.EDITOR

    class Session:
        room = Room()

        def __init__(self) -> None:
            self.dispatched = asyncio.Event()
            self.requests = 0
            self.waiters: list[_FunctionResultWaiter] = []

        @contextmanager
        def scoped(self, waiter: _FunctionResultWaiter):
            self.waiters.append(waiter)
            yield

        def put_control_request(self, *_: object, **__: object) -> None:
            self.requests += 1
            self.dispatched.set()

    monkeypatch.setattr(kernel_session_module, "MAX_SESSION_PROJECTION_WORK", 1)
    session = Session()

    async def cancel() -> ProjectionUnavailable:
        first = asyncio.create_task(
            read_session_values(
                session,
                "revision-1",
                (_bound_projection("summary"),),
                consumer_id="editor",
            )
        )
        await session.dispatched.wait()
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        with pytest.raises(ProjectionUnavailable) as limited:
            await read_session_values(
                session,
                "revision-1",
                (_bound_projection("summary"),),
                consumer_id="editor",
                timeout=0,
            )
        for waiter in session.waiters:
            waiter.on_detach()
        return limited.value

    error = asyncio.run(cancel())

    assert session.requests == 1
    assert error.code == "projection-work-limit"


def test_disconnected_projection_calls_retain_backlog_ownership(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from marimo._messaging.notification import ConsumerCapabilities
    from marimo._types.ids import ConsumerId

    class Consumer:
        consumer_id = ConsumerId("preview-backlog")

        def on_detach(self) -> None:
            return

    consumer = Consumer()

    class Room:
        connected = True

        def get_consumer(self, consumer_id: ConsumerId) -> object | None:
            return (
                consumer
                if self.connected and consumer_id == consumer.consumer_id
                else None
            )

        @staticmethod
        def get_capabilities(current: object) -> ConsumerCapabilities:
            assert current is consumer
            return ConsumerCapabilities.EDITOR

    class Session:
        room = Room()

        def __init__(self) -> None:
            self.dispatched = asyncio.Event()
            self.requests = 0

        @staticmethod
        @contextmanager
        def scoped(_: object):
            yield

        def put_control_request(self, *_: object, **__: object) -> None:
            self.requests += 1
            self.dispatched.set()

    monkeypatch.setattr(kernel_session_module, "MAX_SESSION_PROJECTION_WORK", 1)
    session = Session()

    async def disconnect() -> ProjectionUnavailable:
        first = asyncio.create_task(
            render_session_outputs(
                session,
                "revision-1",
                (_bound_projection("summary", "output"),),
                (_bound_projection("summary", "output"),),
                consumer_id=str(consumer.consumer_id),
                timeout=10,
            )
        )
        await session.dispatched.wait()
        session.room.connected = False
        consumer.on_detach()
        with pytest.raises(ProjectionUnavailable) as detached:
            await asyncio.wait_for(first, timeout=1)
        assert detached.value.code == "consumer-unavailable"
        session.room.connected = True
        with pytest.raises(ProjectionUnavailable) as limited:
            await render_session_outputs(
                session,
                "revision-1",
                (_bound_projection("summary", "output"),),
                (_bound_projection("summary", "output"),),
                consumer_id=str(consumer.consumer_id),
                timeout=0,
            )
        return limited.value

    error = asyncio.run(disconnect())

    assert session.requests == 2
    assert error.code == "projection-work-limit"


def test_output_consumer_detach_finishes_read_and_releases_owners() -> None:
    from marimo._messaging.notification import ConsumerCapabilities
    from marimo._runtime.commands import InvokeFunctionCommand
    from marimo._types.ids import ConsumerId

    class Consumer:
        consumer_id = ConsumerId("preview-a")

        def __init__(self) -> None:
            self.detached = False

        def on_detach(self) -> None:
            self.detached = True

    consumer = Consumer()

    class Room:
        connected = True

        def get_consumer(self, consumer_id: ConsumerId) -> object | None:
            if self.connected and consumer_id == consumer.consumer_id:
                return consumer
            return None

        @staticmethod
        def get_capabilities(current: object) -> ConsumerCapabilities:
            assert current is consumer
            return ConsumerCapabilities.EDITOR

    class Session:
        room = Room()

        def __init__(self) -> None:
            self.requests: list[tuple[object, object]] = []
            self.dispatched: asyncio.Event | None = None

        @staticmethod
        @contextmanager
        def scoped(_: object):
            yield

        def put_control_request(self, request: object, **kwargs: object) -> None:
            self.requests.append((request, kwargs.get("from_consumer_id")))
            if self.dispatched is not None:
                self.dispatched.set()

    session = Session()

    async def disconnect() -> ProjectionUnavailable:
        session.dispatched = asyncio.Event()
        read = asyncio.create_task(
            render_session_outputs(
                session,
                "revision-1",
                (_bound_projection("summary", "output"),),
                (_bound_projection("summary", "output"),),
                consumer_id=str(consumer.consumer_id),
                timeout=10,
            )
        )
        await session.dispatched.wait()
        session.room.connected = False
        consumer.on_detach()
        with pytest.raises(ProjectionUnavailable) as raised:
            await asyncio.wait_for(read, timeout=1)
        return raised.value

    error = asyncio.run(disconnect())

    assert error.code == "consumer-unavailable"
    raw_cleanup, origin = session.requests[-1]
    cleanup = cast(InvokeFunctionCommand, raw_cleanup)
    assert cleanup.args["revision"] == "revision-1"
    assert cleanup.args["projections"] == []
    assert cleanup.args["active_projections"] == []
    assert cleanup.args["consumer_id"] == "preview-a"
    assert cleanup.args["max_output_bytes"] == 1_000_000
    assert isinstance(cleanup.args["authorization"], str)
    assert origin is None
    assert consumer.detached is True


def test_output_detach_queues_cleanup_when_projection_quota_is_saturated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from marimo._messaging.notification import ConsumerCapabilities
    from marimo._runtime.commands import InvokeFunctionCommand
    from marimo._types.ids import ConsumerId

    class Consumer:
        consumer_id = ConsumerId("preview-saturated")

        def on_detach(self) -> None:
            return

    consumer = Consumer()

    class Room:
        connected = True

        def get_consumer(self, consumer_id: ConsumerId) -> object | None:
            return (
                consumer
                if self.connected and consumer_id == consumer.consumer_id
                else None
            )

        @staticmethod
        def get_capabilities(current: object) -> ConsumerCapabilities:
            assert current is consumer
            return ConsumerCapabilities.EDITOR

    class Session:
        room = Room()

        def __init__(self) -> None:
            self.dispatched = asyncio.Event()
            self.requests: list[object] = []
            self.waiters: list[_FunctionResultWaiter] = []

        @contextmanager
        def scoped(self, waiter: _FunctionResultWaiter):
            self.waiters.append(waiter)
            yield

        def put_control_request(self, request: object, **_kwargs: object) -> None:
            self.requests.append(request)
            self.dispatched.set()

    monkeypatch.setattr(kernel_session_module, "MAX_SESSION_PROJECTION_WORK", 1)
    session = Session()

    async def disconnect() -> ProjectionUnavailable:
        read = asyncio.create_task(
            render_session_outputs(
                session,
                "revision-1",
                (_bound_projection("summary", "output"),),
                (_bound_projection("summary", "output"),),
                consumer_id=str(consumer.consumer_id),
                timeout=10,
            )
        )
        await session.dispatched.wait()
        session.room.connected = False
        consumer.on_detach()
        with pytest.raises(ProjectionUnavailable) as raised:
            await asyncio.wait_for(read, timeout=1)
        for waiter in session.waiters:
            waiter.on_detach()
        return raised.value

    error = asyncio.run(disconnect())

    assert error.code == "consumer-unavailable"
    assert len(session.requests) == 2
    cleanup = cast(InvokeFunctionCommand, session.requests[-1])
    assert cleanup.args["projections"] == []
    assert cleanup.args["active_projections"] == []
    assert cleanup.args["consumer_id"] == "preview-saturated"


def test_session_detach_finishes_value_read_without_a_timeout() -> None:
    from marimo._messaging.notification import ConsumerCapabilities
    from marimo._session.events import SessionEventBus
    from marimo._types.ids import ConsumerId

    consumer = object()

    class Room:
        @staticmethod
        def get_consumer(consumer_id: ConsumerId) -> object | None:
            return consumer if consumer_id == ConsumerId("editor") else None

        @staticmethod
        def get_capabilities(current: object) -> ConsumerCapabilities:
            assert current is consumer
            return ConsumerCapabilities.EDITOR

    class Session:
        room = Room()

        def __init__(self) -> None:
            self.dispatched: asyncio.Event | None = None
            self.extension: Any | None = None
            self.event_bus = SessionEventBus()

        @contextmanager
        def scoped(self, extension: Any):
            self.extension = extension
            extension.on_attach(self, self.event_bus)
            try:
                yield
            finally:
                extension.on_detach()

        def put_control_request(self, *_: object, **__: object) -> None:
            assert self.dispatched is not None
            self.dispatched.set()

    session = Session()

    async def close_session() -> ProjectionUnavailable:
        session.dispatched = asyncio.Event()
        read = asyncio.create_task(
            read_session_values(
                session,
                "revision-1",
                (_bound_projection("summary"),),
                consumer_id="editor",
                timeout=None,
            )
        )
        await session.dispatched.wait()
        assert session.extension is not None
        session.extension.on_detach()
        with pytest.raises(ProjectionUnavailable) as raised:
            await asyncio.wait_for(read, timeout=1)
        return raised.value

    error = asyncio.run(close_session())

    assert error.code == "session-unavailable"
    assert error.status_code == 409
