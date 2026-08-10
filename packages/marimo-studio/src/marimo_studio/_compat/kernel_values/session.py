"""Invoke Studio's projection functions through a Marimo session queue."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from types import MethodType
from typing import Any, cast
from uuid import uuid4
from weakref import WeakKeyDictionary, WeakSet

from marimo._session.extensions.types import EventAwareExtension

from marimo_studio._compat.kernel_values.models import (
    DEFAULT_MAX_VALUE_BYTES,
    FUNCTION_NAME,
    NAMESPACE,
    OUTPUT_FUNCTION_NAME,
    ValueReadUnavailable,
)
from marimo_studio.types import (
    OutputRenderResult,
    RenderedOutput,
    ValueReadError,
    ValueReadResult,
)


class _FunctionResultWaiter(EventAwareExtension):
    def __init__(
        self,
        call_id: str,
        loop: asyncio.AbstractEventLoop,
        parser: Callable[[object], object] | None = None,
        operation: str = "value",
    ) -> None:
        super().__init__()
        self.call_id = call_id
        self.loop = loop
        self.parser = parser or _parse_result
        self.operation = operation
        self.future: asyncio.Future[object] = loop.create_future()

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
            if self.future.done():
                return
            if not message.found:
                self.future.set_exception(
                    ValueReadUnavailable(
                        f"{self.operation}-function-unavailable",
                        f"The kernel {self.operation} function is still starting.",
                        transient=True,
                    )
                )
                return
            if message.status.code != "ok":
                self.future.set_exception(
                    ValueReadUnavailable(
                        f"{self.operation}-function-error",
                        message.status.message
                        or f"The kernel {self.operation} function failed.",
                        transient=False,
                    )
                )
                return
            try:
                result = self.parser(message.return_value)
            except ValueReadUnavailable as error:
                self.future.set_exception(error)
            else:
                self.future.set_result(result)

        self.loop.call_soon_threadsafe(complete)

    def consumer_detached(self) -> None:
        def complete() -> None:
            if self.future.done():
                return
            self.future.set_exception(
                ValueReadUnavailable(
                    "consumer-unavailable",
                    "The Marimo browser connection is no longer active.",
                    transient=True,
                    status_code=409,
                )
            )

        self.loop.call_soon_threadsafe(complete)


_CONSUMERS_WITH_OUTPUT_CLEANUP: WeakSet[object] = WeakSet()
_PENDING_OUTPUT_READS: WeakKeyDictionary[object, WeakSet[_FunctionResultWaiter]] = (
    WeakKeyDictionary()
)


def _attach_output_cleanup(session: Any, consumer: Any, consumer_id: str) -> None:
    if consumer in _CONSUMERS_WITH_OUTPUT_CLEANUP:
        return
    original = consumer.on_detach

    def on_detach(current: Any) -> None:
        try:
            if session.room.get_consumer(current.consumer_id) is None:
                pending = tuple(_PENDING_OUTPUT_READS.pop(current, ()))
                for waiter in pending:
                    waiter.consumer_detached()
                from marimo._runtime.commands import InvokeFunctionCommand
                from marimo._types.ids import RequestId

                session.put_control_request(
                    InvokeFunctionCommand(
                        function_call_id=RequestId(uuid4().hex),
                        namespace=NAMESPACE,
                        function_name=OUTPUT_FUNCTION_NAME,
                        args={
                            "selectors": [],
                            "active_selectors": [],
                            "consumer_id": consumer_id,
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
        raise ValueReadUnavailable(
            "invalid-value-response",
            "The kernel returned an invalid value response.",
            transient=False,
        )
    raw_values = value.get("values")
    raw_errors = value.get("errors")
    if not isinstance(raw_values, dict) or not isinstance(raw_errors, dict):
        raise ValueReadUnavailable(
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
            raise ValueReadUnavailable(
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
        raise ValueReadUnavailable(
            "invalid-output-response",
            "The kernel returned an invalid output response.",
            transient=False,
        )
    raw_outputs = value.get("outputs")
    raw_errors = value.get("errors")
    if not isinstance(raw_outputs, dict) or not isinstance(raw_errors, dict):
        raise ValueReadUnavailable(
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
            raise ValueReadUnavailable(
                "invalid-output-response",
                "The kernel returned an invalid rendered output.",
                transient=False,
            )
        reset_ids = cast(list[str], reset_ui_object_ids)
        if any(not item.startswith(f"{owner_cell_id}-") for item in reset_ids):
            raise ValueReadUnavailable(
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
            raise ValueReadUnavailable(
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
    timeout: float,
    parser: Callable[[object], object],
    operation: str,
) -> object:
    from marimo._runtime.commands import InvokeFunctionCommand
    from marimo._session.capabilities import consumer_can
    from marimo._types.ids import ConsumerId, RequestId

    native_consumer_id = ConsumerId(consumer_id)
    consumer = session.room.get_consumer(native_consumer_id)
    if consumer is None:
        raise ValueReadUnavailable(
            "consumer-unavailable",
            "The Marimo browser connection is no longer active.",
            transient=True,
            status_code=409,
        )
    if not consumer_can(
        session.room.get_capabilities(consumer),
        InvokeFunctionCommand,
    ):
        raise ValueReadUnavailable(
            "interaction-forbidden",
            f"This Marimo connection cannot read live kernel {operation}s.",
            transient=False,
            status_code=403,
        )

    call_id = uuid4().hex
    waiter = _FunctionResultWaiter(
        call_id,
        asyncio.get_running_loop(),
        parser,
        operation,
    )
    pending: WeakSet[_FunctionResultWaiter] | None = None
    if operation == "output" and hasattr(consumer, "on_detach"):
        pending = _PENDING_OUTPUT_READS.setdefault(consumer, WeakSet())
        pending.add(waiter)
    try:
        with session.scoped(waiter):
            session.put_control_request(
                InvokeFunctionCommand(
                    function_call_id=RequestId(call_id),
                    namespace=NAMESPACE,
                    function_name=function_name,
                    args=args,
                ),
                from_consumer_id=native_consumer_id,
            )
            return await asyncio.wait_for(waiter.future, timeout=timeout)
    except TimeoutError as error:
        output_read = operation == "output"
        raise ValueReadUnavailable(
            "output-read-timeout" if output_read else "read-timeout",
            f"Timed out while reading {operation}s from the Marimo kernel.",
            transient=not output_read,
        ) from error
    finally:
        if pending is not None:
            pending.discard(waiter)
            if not pending:
                _PENDING_OUTPUT_READS.pop(consumer, None)


async def read_session_values(
    session: Any,
    selectors: tuple[str, ...],
    *,
    consumer_id: str,
    timeout: float = 5.0,
    max_value_bytes: int = DEFAULT_MAX_VALUE_BYTES,
) -> ValueReadResult:
    """Read exact selectors through a Marimo session's command queue."""
    result = await _invoke_session_function(
        session,
        function_name=FUNCTION_NAME,
        args={
            "selectors": list(selectors),
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
    selectors: tuple[str, ...],
    active_selectors: tuple[str, ...],
    *,
    consumer_id: str,
    timeout: float = 5.0,
    max_output_bytes: int = DEFAULT_MAX_VALUE_BYTES,
) -> OutputRenderResult:
    """Render exact selectors through a Marimo session's command queue."""
    from marimo._types.ids import ConsumerId

    consumer = session.room.get_consumer(ConsumerId(consumer_id))
    if consumer is not None and hasattr(consumer, "on_detach"):
        _attach_output_cleanup(session, consumer, consumer_id)
    result = await _invoke_session_function(
        session,
        function_name=OUTPUT_FUNCTION_NAME,
        args={
            "selectors": list(selectors),
            "active_selectors": list(active_selectors),
            "consumer_id": consumer_id,
            "max_output_bytes": max_output_bytes,
        },
        consumer_id=consumer_id,
        timeout=timeout,
        parser=_parse_output_result,
        operation="output",
    )
    assert isinstance(result, OutputRenderResult)
    return result
