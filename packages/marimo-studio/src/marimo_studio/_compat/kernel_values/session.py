"""Invoke Studio's value reader through a Marimo session queue."""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import uuid4

from marimo._session.extensions.types import EventAwareExtension

from marimo_studio._compat.kernel_values.models import (
    DEFAULT_MAX_VALUE_BYTES,
    FUNCTION_NAME,
    NAMESPACE,
    ValueReadUnavailable,
)
from marimo_studio.types import ValueReadError, ValueReadResult


class _FunctionResultWaiter(EventAwareExtension):
    def __init__(
        self,
        call_id: str,
        loop: asyncio.AbstractEventLoop,
    ) -> None:
        super().__init__()
        self.call_id = call_id
        self.loop = loop
        self.future: asyncio.Future[ValueReadResult] = loop.create_future()

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
                        "value-function-unavailable",
                        "The kernel value function is still starting.",
                        transient=True,
                    )
                )
                return
            if message.status.code != "ok":
                self.future.set_exception(
                    ValueReadUnavailable(
                        "value-function-error",
                        message.status.message or "The kernel value function failed.",
                        transient=False,
                    )
                )
                return
            try:
                result = _parse_result(message.return_value)
            except ValueReadUnavailable as error:
                self.future.set_exception(error)
            else:
                self.future.set_result(result)

        self.loop.call_soon_threadsafe(complete)


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


async def read_session_values(
    session: Any,
    selectors: tuple[str, ...],
    *,
    consumer_id: str,
    timeout: float = 5.0,
    max_value_bytes: int = DEFAULT_MAX_VALUE_BYTES,
) -> ValueReadResult:
    """Read exact selectors through a Marimo session's command queue."""
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
            "This Marimo connection cannot read live kernel values.",
            transient=False,
            status_code=403,
        )

    call_id = uuid4().hex
    waiter = _FunctionResultWaiter(call_id, asyncio.get_running_loop())
    try:
        with session.scoped(waiter):
            session.put_control_request(
                InvokeFunctionCommand(
                    function_call_id=RequestId(call_id),
                    namespace=NAMESPACE,
                    function_name=FUNCTION_NAME,
                    args={
                        "selectors": list(selectors),
                        "max_value_bytes": max_value_bytes,
                    },
                ),
                from_consumer_id=native_consumer_id,
            )
            return await asyncio.wait_for(waiter.future, timeout=timeout)
    except TimeoutError as error:
        raise ValueReadUnavailable(
            "read-timeout",
            "Timed out while reading values from the Marimo kernel.",
            transient=True,
        ) from error
