"""Invoke Studio's projection functions through a Marimo session queue."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from threading import Lock
from types import MethodType
from typing import Any, cast
from uuid import uuid4
from weakref import WeakKeyDictionary, WeakSet

from marimo._session.extensions.types import EventAwareExtension

from marimo_studio._compat.kernel_values.authorization import (
    BoundProjection,
    authorized_output_arguments,
    authorized_value_arguments,
    probe_output_arguments,
    probe_value_arguments,
)
from marimo_studio._compat.kernel_values.models import (
    DEFAULT_MAX_VALUE_BYTES,
    FUNCTION_NAME,
    NAMESPACE,
    OUTPUT_FUNCTION_NAME,
)
from marimo_studio._projections.runtime_records import (
    OutputRenderResult,
    RenderedOutput,
    ValueReadError,
    ValueReadResult,
)
from marimo_studio._server.presentation.ports import ProjectionUnavailable, SelectorSpec


class _FunctionResultWaiter(EventAwareExtension):
    def __init__(
        self,
        call_id: str,
        loop: asyncio.AbstractEventLoop,
        lease: _ProjectionWorkLease,
        parser: Callable[[object], object] | None = None,
        operation: str = "value",
    ) -> None:
        super().__init__()
        self.call_id = call_id
        self.loop = loop
        self.parser = parser or _parse_result
        self.operation = operation
        self.future: asyncio.Future[object] = loop.create_future()
        self.future.add_done_callback(
            lambda future: None if future.cancelled() else future.exception()
        )
        self.terminal: asyncio.Future[object] = loop.create_future()
        self.terminal.add_done_callback(
            lambda future: None if future.cancelled() else future.exception()
        )
        self._lease = lease
        self._close_scope: Callable[[], None] | None = None

    def retain_scope(self, close: Callable[[], None]) -> None:
        self._close_scope = close

    def finish_work(self) -> None:
        close = self._close_scope
        self._close_scope = None
        if close is not None:
            close()
        self._lease.release()
        if self.terminal.done():
            return
        if self.future.cancelled():
            self.terminal.set_exception(
                ProjectionUnavailable(
                    "query-cancelled",
                    "The kernel query operation was cancelled.",
                    transient=True,
                )
            )
        elif self.future.done():
            error = self.future.exception()
            if error is not None:
                self.terminal.set_exception(error)
            else:
                self.terminal.set_result(self.future.result())
        else:
            self.terminal.set_exception(
                ProjectionUnavailable(
                    "session-unavailable",
                    "The Marimo session closed before the kernel replied.",
                    transient=True,
                )
            )

    def on_detach(self) -> None:
        super().on_detach()
        self._reject_unavailable(
            "session-unavailable",
            "The Marimo session closed before the kernel replied.",
            finish=True,
        )

    def on_notification_sent(self, session: Any, notification: Any) -> None:
        del session
        from marimo._messaging.notification import FunctionCallResultNotification
        from marimo._messaging.serde import deserialize_kernel_message

        message = deserialize_kernel_message(notification)
        if (
            not isinstance(message, FunctionCallResultNotification)
            or message.function_call_id != self.call_id
        ):
            return

        def complete() -> None:
            try:
                if self.future.done():
                    return
                if not message.found:
                    self.future.set_exception(
                        ProjectionUnavailable(
                            f"{self.operation}-function-unavailable",
                            f"The kernel {self.operation} function is still starting.",
                            transient=True,
                        )
                    )
                    return
                if message.status.code != "ok":
                    self.future.set_exception(
                        ProjectionUnavailable(
                            f"{self.operation}-function-error",
                            message.status.message
                            or f"The kernel {self.operation} function failed.",
                            transient=False,
                        )
                    )
                    return
                try:
                    result = self.parser(message.return_value)
                except ProjectionUnavailable as error:
                    self.future.set_exception(error)
                else:
                    self.future.set_result(result)
            finally:
                self.finish_work()

        self.loop.call_soon_threadsafe(complete)

    def consumer_detached(self) -> None:
        self._reject_unavailable(
            "consumer-unavailable",
            "The Marimo browser connection is no longer active.",
        )

    def _reject_unavailable(
        self,
        code: str,
        message: str,
        *,
        finish: bool = False,
    ) -> None:
        def complete() -> None:
            try:
                if not self.future.done():
                    self.future.set_exception(
                        ProjectionUnavailable(
                            code,
                            message,
                            transient=True,
                            status_code=409,
                        )
                    )
            finally:
                if finish:
                    self.finish_work()

        self.loop.call_soon_threadsafe(complete)


_CONSUMERS_WITH_OUTPUT_CLEANUP: WeakSet[object] = WeakSet()
_CONSUMERS_WITH_WORK_CLEANUP: WeakSet[object] = WeakSet()
_PENDING_SESSION_WORK: WeakKeyDictionary[object, WeakSet[_FunctionResultWaiter]] = (
    WeakKeyDictionary()
)
MAX_SESSION_PROJECTION_WORK = 16


@dataclass
class _SessionProjectionWork:
    active: int = 0


class _ProjectionWorkLease:
    def __init__(self, state: _SessionProjectionWork) -> None:
        self._state = state
        self._released = False

    def release(self) -> None:
        with _SESSION_PROJECTION_WORK_LOCK:
            if self._released:
                return
            self._released = True
            self._state.active -= 1


_SESSION_PROJECTION_WORK: WeakKeyDictionary[object, _SessionProjectionWork] = (
    WeakKeyDictionary()
)
_SESSION_PROJECTION_WORK_LOCK = Lock()


def _acquire_projection_work(session: object) -> _ProjectionWorkLease:
    with _SESSION_PROJECTION_WORK_LOCK:
        state = _SESSION_PROJECTION_WORK.get(session)
        if state is None:
            state = _SessionProjectionWork()
            _SESSION_PROJECTION_WORK[session] = state
        if state.active >= MAX_SESSION_PROJECTION_WORK:
            raise ProjectionUnavailable(
                "projection-work-limit",
                "The session has too many pending projection operations.",
                transient=True,
                status_code=429,
            )
        state.active += 1
    return _ProjectionWorkLease(state)


def _retain_projection_waiter(session: Any, waiter: _FunctionResultWaiter) -> None:
    scope = session.scoped(waiter)
    scope.__enter__()
    waiter.retain_scope(lambda: scope.__exit__(None, None, None))


def _attach_session_work_cleanup(consumer: Any) -> None:
    if consumer in _CONSUMERS_WITH_WORK_CLEANUP:
        return
    original = consumer.on_detach

    def on_detach(current: Any) -> None:
        try:
            pending = tuple(_PENDING_SESSION_WORK.pop(current, ()))
            for waiter in pending:
                waiter.consumer_detached()
        finally:
            original()

    consumer.on_detach = MethodType(on_detach, consumer)
    _CONSUMERS_WITH_WORK_CLEANUP.add(consumer)


def _attach_output_cleanup(
    session: Any,
    consumer: Any,
    consumer_id: str,
    revision: str,
) -> None:
    _attach_session_work_cleanup(consumer)
    if consumer in _CONSUMERS_WITH_OUTPUT_CLEANUP:
        return
    original = consumer.on_detach

    def on_detach(current: Any) -> None:
        try:
            if session.room.get_consumer(current.consumer_id) is None:
                from marimo._runtime.commands import InvokeFunctionCommand
                from marimo._types.ids import RequestId

                session.put_control_request(
                    InvokeFunctionCommand(
                        function_call_id=RequestId(uuid4().hex),
                        namespace=NAMESPACE,
                        function_name=OUTPUT_FUNCTION_NAME,
                        args={
                            **authorized_output_arguments(
                                revision,
                                (),
                                (),
                                consumer_id,
                            ),
                            "max_output_bytes": DEFAULT_MAX_VALUE_BYTES,
                        },
                    ),
                    from_consumer_id=None,
                )
        except Exception:
            # Session shutdown still closes the renderer and its native owners.
            pass
        finally:
            original()

    consumer.on_detach = MethodType(on_detach, consumer)
    _CONSUMERS_WITH_OUTPUT_CLEANUP.add(consumer)


def _parse_result(value: object) -> ValueReadResult:
    if not isinstance(value, dict):
        raise ProjectionUnavailable(
            "invalid-value-response",
            "The kernel returned an invalid value response.",
            transient=False,
        )
    raw_values = value.get("values")
    raw_errors = value.get("errors")
    if not isinstance(raw_values, dict) or not isinstance(raw_errors, dict):
        raise ProjectionUnavailable(
            "invalid-value-response",
            "The kernel returned an invalid value response.",
            transient=False,
        )
    errors: dict[str, ValueReadError] = {}
    for selector, error in raw_errors.items():
        code = error.get("code") if isinstance(error, dict) else None
        message = error.get("message") if isinstance(error, dict) else None
        if (
            not isinstance(selector, str)
            or not isinstance(error, dict)
            or not isinstance(code, str)
            or not isinstance(message, str)
        ):
            raise ProjectionUnavailable(
                "invalid-value-response",
                "The kernel returned an invalid value error.",
                transient=False,
            )
        errors[selector] = ValueReadError(code, message)
    return ValueReadResult(
        values={str(selector): item for selector, item in raw_values.items()},
        errors=errors,
    )


def _parse_output_result(value: object) -> OutputRenderResult:
    if not isinstance(value, dict):
        raise ProjectionUnavailable(
            "invalid-output-response",
            "The kernel returned an invalid output response.",
            transient=False,
        )
    raw_outputs = value.get("outputs")
    raw_errors = value.get("errors")
    if not isinstance(raw_outputs, dict) or not isinstance(raw_errors, dict):
        raise ProjectionUnavailable(
            "invalid-output-response",
            "The kernel returned an invalid output response.",
            transient=False,
        )
    outputs: dict[str, RenderedOutput] = {}
    for selector, output in raw_outputs.items():
        owner_cell_id = output.get("ownerCellId") if isinstance(output, dict) else None
        mimetype = output.get("mimetype") if isinstance(output, dict) else None
        data = output.get("data") if isinstance(output, dict) else None
        timestamp = output.get("timestamp") if isinstance(output, dict) else None
        reset_ui_object_ids = (
            output.get("resetUiObjectIds") if isinstance(output, dict) else None
        )
        if (
            not isinstance(selector, str)
            or not isinstance(owner_cell_id, str)
            or not isinstance(mimetype, str)
            or not isinstance(data, str)
            or isinstance(timestamp, bool)
            or not isinstance(timestamp, (int, float))
            or not isinstance(reset_ui_object_ids, list)
            or not all(isinstance(item, str) for item in reset_ui_object_ids)
        ):
            raise ProjectionUnavailable(
                "invalid-output-response",
                "The kernel returned an invalid rendered output.",
                transient=False,
            )
        reset_ids = cast(list[str], reset_ui_object_ids)
        if any(not item.startswith(f"{owner_cell_id}-") for item in reset_ids):
            raise ProjectionUnavailable(
                "invalid-output-response",
                "The kernel returned a UI reset owned by another cell.",
                transient=False,
            )
        outputs[selector] = RenderedOutput(
            owner_cell_id=owner_cell_id,
            mimetype=mimetype,
            data=data,
            timestamp=float(timestamp),
            reset_ui_object_ids=tuple(reset_ids),
        )
    errors: dict[str, ValueReadError] = {}
    for selector, error in raw_errors.items():
        code = error.get("code") if isinstance(error, dict) else None
        message = error.get("message") if isinstance(error, dict) else None
        if (
            not isinstance(selector, str)
            or not isinstance(code, str)
            or not isinstance(message, str)
        ):
            raise ProjectionUnavailable(
                "invalid-output-response",
                "The kernel returned an invalid output error.",
                transient=False,
            )
        errors[selector] = ValueReadError(code, message)
    return OutputRenderResult(outputs=outputs, errors=errors)


async def _invoke_session_function(
    session: Any,
    *,
    function_name: str,
    args: dict[str, object],
    consumer_id: str,
    timeout: float | None,
    parser: Callable[[object], object],
    operation: str,
) -> object:
    from marimo._runtime.commands import InvokeFunctionCommand
    from marimo._session.capabilities import consumer_can
    from marimo._types.ids import ConsumerId, RequestId

    native_consumer_id = ConsumerId(consumer_id)
    resource = "query state" if operation == "query" else f"{operation}s"
    consumer = session.room.get_consumer(native_consumer_id)
    if consumer is None:
        raise ProjectionUnavailable(
            "consumer-unavailable",
            "The Marimo browser connection is no longer active.",
            transient=True,
            status_code=409,
        )
    if not consumer_can(
        session.room.get_capabilities(consumer),
        InvokeFunctionCommand,
    ):
        raise ProjectionUnavailable(
            "interaction-forbidden",
            f"This Marimo connection cannot access live kernel {resource}.",
            transient=False,
            status_code=403,
        )

    lease = _acquire_projection_work(session)
    call_id = uuid4().hex
    waiter = _FunctionResultWaiter(
        call_id,
        asyncio.get_running_loop(),
        lease,
        parser,
        operation,
    )
    pending: WeakSet[_FunctionResultWaiter] | None = None
    if operation == "output" and hasattr(consumer, "on_detach"):
        _attach_session_work_cleanup(consumer)
        pending = _PENDING_SESSION_WORK.setdefault(consumer, WeakSet())
        pending.add(waiter)
    _retain_projection_waiter(session, waiter)
    try:
        try:
            session.put_control_request(
                InvokeFunctionCommand(
                    function_call_id=RequestId(call_id),
                    namespace=NAMESPACE,
                    function_name=function_name,
                    args=args,
                ),
                from_consumer_id=native_consumer_id,
            )
        except BaseException:
            waiter.finish_work()
            raise
        result = (
            asyncio.shield(waiter.future) if operation == "query" else waiter.future
        )
        return await asyncio.wait_for(result, timeout=timeout)
    except asyncio.TimeoutError as error:
        output_read = operation == "output"
        query_sync = operation == "query"
        raise ProjectionUnavailable(
            (
                "output-read-timeout"
                if output_read
                else "query-sync-timeout"
                if query_sync
                else "read-timeout"
            ),
            f"Timed out while accessing {resource} in the Marimo kernel.",
            transient=not output_read,
            terminal=waiter.terminal if query_sync else None,
        ) from error
    finally:
        if pending is not None:

            def release_pending(_future: object) -> None:
                pending.discard(waiter)
                if not pending:
                    _PENDING_SESSION_WORK.pop(consumer, None)

            if waiter.future.done():
                release_pending(waiter.future)
            else:
                waiter.future.add_done_callback(release_pending)


async def read_session_values(
    session: Any,
    revision: str,
    projections: tuple[BoundProjection, ...],
    *,
    consumer_id: str,
    timeout: float | None = 5.0,
    max_value_bytes: int = DEFAULT_MAX_VALUE_BYTES,
) -> ValueReadResult:
    """Read exact selectors through a Marimo session's command queue."""
    result = await _invoke_session_function(
        session,
        function_name=FUNCTION_NAME,
        args={
            **authorized_value_arguments(revision, projections),
            "max_value_bytes": max_value_bytes,
        },
        consumer_id=consumer_id,
        timeout=timeout,
        parser=_parse_result,
        operation="value",
    )
    assert isinstance(result, ValueReadResult)
    return result


async def render_session_outputs(
    session: Any,
    revision: str,
    projections: tuple[BoundProjection, ...],
    active_projections: tuple[BoundProjection, ...],
    *,
    consumer_id: str,
    timeout: float = 5.0,
    max_output_bytes: int = DEFAULT_MAX_VALUE_BYTES,
) -> OutputRenderResult:
    """Render exact selectors through a Marimo session's command queue."""
    from marimo._types.ids import ConsumerId

    consumer = session.room.get_consumer(ConsumerId(consumer_id))
    if consumer is not None and hasattr(consumer, "on_detach"):
        _attach_output_cleanup(session, consumer, consumer_id, revision)
    result = await _invoke_session_function(
        session,
        function_name=OUTPUT_FUNCTION_NAME,
        args={
            **authorized_output_arguments(
                revision,
                projections,
                active_projections,
                consumer_id,
            ),
            "max_output_bytes": max_output_bytes,
        },
        consumer_id=consumer_id,
        timeout=timeout,
        parser=_parse_output_result,
        operation="output",
    )
    assert isinstance(result, OutputRenderResult)
    return result


async def read_probe_values(
    session: Any,
    specifications: Mapping[str, SelectorSpec],
    *,
    consumer_id: str,
    timeout: float = 5.0,
    max_value_bytes: int = DEFAULT_MAX_VALUE_BYTES,
) -> ValueReadResult:
    """Read selectors granted by one internal runtime probe lease."""
    result = await _invoke_session_function(
        session,
        function_name=FUNCTION_NAME,
        args={
            **probe_value_arguments(specifications),
            "max_value_bytes": max_value_bytes,
        },
        consumer_id=consumer_id,
        timeout=timeout,
        parser=_parse_result,
        operation="value",
    )
    assert isinstance(result, ValueReadResult)
    return result


async def render_probe_outputs(
    session: Any,
    specifications: Mapping[str, SelectorSpec],
    active_specifications: Mapping[str, SelectorSpec],
    *,
    consumer_id: str,
    timeout: float = 5.0,
    max_output_bytes: int = DEFAULT_MAX_VALUE_BYTES,
) -> OutputRenderResult:
    """Render selectors granted by one internal runtime probe lease."""
    result = await _invoke_session_function(
        session,
        function_name=OUTPUT_FUNCTION_NAME,
        args={
            **probe_output_arguments(
                specifications,
                active_specifications,
                consumer_id,
            ),
            "max_output_bytes": max_output_bytes,
        },
        consumer_id=consumer_id,
        timeout=timeout,
        parser=_parse_output_result,
        operation="output",
    )
    assert isinstance(result, OutputRenderResult)
    return result
