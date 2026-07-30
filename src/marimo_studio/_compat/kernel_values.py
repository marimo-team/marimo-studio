"""Read permitted view selectors through Marimo's function RPC."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from typing import Any
from uuid import uuid4

from marimo._session.extensions.types import EventAwareExtension

from marimo_studio._workspace.config import TemplateParser, discover_studio
from marimo_studio.errors import ConfigurationError, ProtocolError
from marimo_studio.values import parse_value_reference, resolve_value_reference

NAMESPACE = "_marimo_studio"
FUNCTION_NAME = "read_values"
DEFAULT_MAX_VALUE_BYTES = 1_000_000
_INSPECTION_SELECTORS: dict[Path, tuple[str, ...]] = {}


class ValueReadUnavailable(ProtocolError):
    """A transient or terminal failure at the kernel RPC boundary."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        transient: bool,
        status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.transient = transient
        self.status_code = status_code or (503 if transient else 500)


@dataclass
class ReadValuesArgs:
    selectors: list[str]
    max_value_bytes: int = DEFAULT_MAX_VALUE_BYTES


@dataclass(frozen=True)
class ValueReadError:
    code: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message}


@dataclass(frozen=True)
class ValueReadResult:
    values: dict[str, object]
    errors: dict[str, ValueReadError]

    def to_dict(self) -> dict[str, object]:
        return {
            "values": self.values,
            "errors": {
                selector: error.to_dict() for selector, error in self.errors.items()
            },
        }


def _template_selectors(notebook: Path) -> tuple[str, ...] | None:
    studio = discover_studio(notebook)
    if studio is None:
        return None
    selectors: list[str] = []
    for view in studio.views.values():
        parser = TemplateParser()
        try:
            parser.feed(view.template.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ConfigurationError):
            # The HTTP boundary validates selectors against the selected view.
            # A template under active development cannot block another view.
            continue
        selectors.extend(ref.source for ref in parser.value_references)
    return tuple(dict.fromkeys(selectors))


def _encode_value(
    selector: str,
    value: object,
    *,
    max_value_bytes: int,
) -> tuple[object | None, ValueReadError | None]:
    try:
        encoded = json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
        )
    except (TypeError, ValueError, OverflowError, RecursionError) as error:
        return None, ValueReadError(
            "not-json-serializable",
            (
                f"Selector {selector!r} resolved to {type(value).__name__}, "
                f"which cannot be serialized as JSON: {error}"
            ),
        )
    if len(encoded.encode("utf-8")) > max_value_bytes:
        return None, ValueReadError(
            "value-too-large",
            f"Selector {selector!r} exceeds the {max_value_bytes}-byte limit.",
        )
    return json.loads(encoded), None


def _read_values(
    namespace: Mapping[str, object],
    selectors: tuple[str, ...],
    allowed: set[str],
    *,
    max_value_bytes: int,
) -> ValueReadResult:
    values: dict[str, object] = {}
    errors: dict[str, ValueReadError] = {}
    for selector in selectors:
        if selector not in allowed:
            errors[selector] = ValueReadError(
                "unknown-selector",
                f"Selector {selector!r} is not present in a configured view.",
            )
            continue
        try:
            reference = parse_value_reference(selector)
        except ValueError as error:
            errors[selector] = ValueReadError("invalid-selector", str(error))
            continue
        if reference.variable not in namespace:
            errors[selector] = ValueReadError(
                "missing-variable",
                f"Variable {reference.variable!r} is not defined",
            )
            continue
        try:
            value = resolve_value_reference(namespace, reference)
        except Exception as error:
            errors[selector] = ValueReadError(
                "value-path-unavailable",
                f"Selector {selector!r} could not be resolved: {error}",
            )
            continue
        encoded, error = _encode_value(
            selector,
            value,
            max_value_bytes=max_value_bytes,
        )
        if error is not None:
            errors[selector] = error
        else:
            values[selector] = encoded
    return ValueReadResult(values, errors)


@contextmanager
def inspection_selectors(
    notebook: Path,
    selectors: tuple[str, ...],
) -> Iterator[None]:
    """Permit runtime inspection selectors for an in-process probe kernel."""
    path = notebook.resolve()
    _INSPECTION_SELECTORS[path] = selectors
    try:
        yield
    finally:
        _INSPECTION_SELECTORS.pop(path, None)


class _KernelValueLifespan:
    def __init__(self) -> None:
        self._registry: Any | None = None

    async def __aenter__(self) -> None:
        from marimo._runtime.context import get_context
        from marimo._runtime.context.kernel_context import KernelRuntimeContext
        from marimo._runtime.functions import Function
        from marimo._types.ids import CellId_t

        context = get_context()
        if not isinstance(context, KernelRuntimeContext) or context.filename is None:
            return
        filename = Path(context.filename).resolve()
        inspection = _INSPECTION_SELECTORS.get(filename)
        if inspection is None:
            try:
                if discover_studio(filename) is None:
                    return
            except (OSError, UnicodeError, ConfigurationError):
                return

        def read(args: ReadValuesArgs) -> dict[str, object]:
            try:
                allowed = (
                    set(_template_selectors(filename) or ())
                    if inspection is None
                    else set(inspection)
                )
            except (OSError, UnicodeError, ConfigurationError) as error:
                return ValueReadResult(
                    values={},
                    errors={
                        selector: ValueReadError(
                            "studio-unavailable",
                            f"Studio selectors are unavailable: {error}",
                        )
                        for selector in args.selectors
                    },
                ).to_dict()
            limit = max(1, min(args.max_value_bytes, DEFAULT_MAX_VALUE_BYTES))
            kernel = context._kernel
            with kernel.lock_globals():
                return _read_values(
                    kernel.globals,
                    tuple(dict.fromkeys(args.selectors)),
                    allowed,
                    max_value_bytes=limit,
                ).to_dict()

        function = Function(FUNCTION_NAME, ReadValuesArgs, read)
        function.cell_id = CellId_t("__marimo_studio_values__")
        context.function_registry.register(NAMESPACE, function)
        self._registry = context.function_registry

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool:
        del exc_type, exc_value, traceback
        if self._registry is not None:
            self._registry.delete(NAMESPACE)
            self._registry = None
        return False


def kernel_lifespan(_: None) -> _KernelValueLifespan:
    """Register the value function in kernels backed by Studio configuration."""
    return _KernelValueLifespan()


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
        from marimo._messaging.notification import (
            FunctionCallResultNotification,
        )
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
