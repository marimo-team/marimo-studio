"""Run a Marimo session inside an owned runtime worker."""

from __future__ import annotations

import asyncio
import sys
import threading
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from uuid import uuid4

import marimo

from marimo_studio._compat.browser_notebook import selector_specs
from marimo_studio._compat.kernel_values import (
    DEFAULT_MAX_VALUE_BYTES,
    probe_selector_lease,
    read_probe_values,
    render_probe_outputs,
)
from marimo_studio._compat.kernel_values.representations import inspection_value
from marimo_studio._compat.runtime_requests import instantiate_notebook_request
from marimo_studio._notebook.source_generation import NotebookSourceGeneration
from marimo_studio._processes.limits import DEFAULT_RUNTIME_TIMEOUT
from marimo_studio._projections.runtime_records import (
    OutputRenderResult,
    RenderedOutput,
    RuntimeCell,
    RuntimeOutput,
    RuntimeProbe,
    ValueReadError,
    ValueReadResult,
)
from marimo_studio._projections.values import parse_value_reference
from marimo_studio._server.presentation.ports import ProjectionUnavailable
from marimo_studio.errors import ProtocolError, RuntimeTimeoutError

_NOTEBOOK_CONFIG_LOCK = threading.RLock()
_POST_DEADLINE_SHUTDOWN_GRACE = 2.0


@contextmanager
def _notebook_config_context(path: Path) -> Generator[None, None, None]:
    """Bind Marimo's builder configuration lookup to the inspected notebook."""
    from marimo._config import manager

    with _NOTEBOOK_CONFIG_LOCK:
        original = manager.get_default_config_manager
        owner_thread = threading.get_ident()

        def from_notebook(*, current_path: str | None) -> Any:
            if current_path is None and threading.get_ident() == owner_thread:
                return original(current_path=str(path))
            return original(current_path=current_path)

        manager_module: Any = manager
        manager_module.get_default_config_manager = from_notebook
        try:
            yield
        finally:
            manager_module.get_default_config_manager = original


def _build_manager(path: Path, *, timeout: float, show_tracebacks: bool) -> Any:
    with _notebook_config_context(path):
        app: Any = (
            marimo.create_asgi_app(
                quiet=True,
                include_code=False,
                redirect_console_to_browser=True,
                skew_protection=True,
                session_ttl=max(30, int(timeout)),
                show_tracebacks=show_tracebacks,
            )
            .with_app(path="/", root=str(path))
            .build()
        )
    for route in app.routes:
        mounted = getattr(route, "app", None)
        state = getattr(mounted, "state", None)
        if state is not None and hasattr(state, "session_manager"):
            return state.session_manager
    raise ProtocolError("Could not locate Marimo's runtime inspection session")


async def probe_runtime_in_worker(
    path: Path,
    *,
    cell_ids: tuple[str, ...],
    variables: tuple[str, ...],
    output_selector_groups: tuple[tuple[str, ...], ...] = (),
    timeout: float = DEFAULT_RUNTIME_TIMEOUT,
    show_tracebacks: bool = False,
    value_max_bytes: int | None = None,
    source_generation: NotebookSourceGeneration | None = None,
) -> RuntimeProbe:
    """Run a notebook session owned by the current isolated worker."""
    del source_generation
    from marimo._messaging.cell_output import CellChannel
    from marimo._messaging.notification import CompletedRunNotification
    from marimo._messaging.serde import deserialize_kernel_message
    from marimo._session.consumer import SessionConsumer
    from marimo._session.model import ConnectionState
    from marimo._session.types import KernelState
    from marimo._types.ids import ConsumerId, SessionId

    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout

    class ProbeConsumer(SessionConsumer):
        def __init__(self) -> None:
            self.complete = asyncio.Event()

        @property
        def consumer_id(self) -> Any:
            return ConsumerId("marimo-studio-check")

        def notify(self, notification: Any) -> None:
            decoded = deserialize_kernel_message(notification)
            if isinstance(decoded, CompletedRunNotification):
                loop.call_soon_threadsafe(self.complete.set)

        def connection_state(self) -> Any:
            return ConnectionState.OPEN

        def on_attach(self, session: Any, event_bus: Any) -> None:
            del session, event_bus

        def on_detach(self) -> None:
            return

    groups = output_selector_groups
    allowed_outputs = tuple(
        dict.fromkeys(selector for group in groups for selector in group)
    )
    main_module = sys.modules["__main__"]
    manager = _build_manager(
        path,
        timeout=timeout,
        show_tracebacks=show_tracebacks,
    )
    session_id = SessionId(f"marimo-studio-check-{uuid4().hex}")
    consumer = ProbeConsumer()
    session: Any | None = None
    try:
        with probe_selector_lease(path, variables, allowed_outputs) as query_params:
            session = manager.create_session(
                session_id,
                consumer,
                query_params=query_params,
                file_key=str(path),
                auto_instantiate=True,
            )
            if session is None:
                raise ProtocolError("Marimo session creation returned no session")
            session.instantiate(
                instantiate_notebook_request(auto_run=True),
                http_request=None,
            )
            try:
                await asyncio.wait_for(
                    consumer.complete.wait(),
                    timeout=max(0, deadline - loop.time()),
                )
            except asyncio.TimeoutError as error:
                raise RuntimeTimeoutError(
                    f"Notebook runtime did not finish within {timeout:g} seconds"
                ) from error

            view = session.session_view
            terminal_states = {"idle", "disabled-transitively"}
            while any(
                (notification := view.cell_notifications.get(cell_id)) is None
                or notification.status not in terminal_states
                for cell_id in cell_ids
            ):
                remaining = deadline - loop.time()
                if remaining <= 0:
                    raise RuntimeTimeoutError(
                        "Notebook runtime finished before its cell state settled"
                    )
                await asyncio.sleep(min(0.01, remaining))

            cells = {
                cell_id: _runtime_cell(
                    view.cell_notifications.get(cell_id),
                    CellChannel,
                )
                for cell_id in cell_ids
            }
            values = (
                await _read_values_within_deadline(
                    session,
                    selector_specs(
                        {
                            selector: parse_value_reference(selector)
                            for selector in variables
                        }
                    ),
                    consumer_id=str(consumer.consumer_id),
                    max_value_bytes=value_max_bytes or DEFAULT_MAX_VALUE_BYTES,
                    loop=loop,
                    deadline=deadline,
                    timeout=timeout,
                )
                if variables
                else ValueReadResult(values={}, errors={})
            )
            outputs: dict[str, RenderedOutput] = {}
            output_errors: dict[str, ValueReadError] = {}
            for group in groups:
                active = tuple(dict.fromkeys(group))
                for selector in active:
                    rendered = await _render_output_within_deadline(
                        session,
                        selector_specs({selector: parse_value_reference(selector)}),
                        selector_specs(
                            {
                                active_selector: parse_value_reference(active_selector)
                                for active_selector in active
                            }
                        ),
                        consumer_id=str(consumer.consumer_id),
                        loop=loop,
                        deadline=deadline,
                        timeout=timeout,
                    )
                    error = rendered.errors.get(selector) or rendered.errors.get("*")
                    output = rendered.outputs.get(selector)
                    if error is not None:
                        outputs.pop(selector, None)
                        output_errors[selector] = error
                    elif output is not None:
                        output_errors.pop(selector, None)
                        outputs[selector] = output
            output_result = OutputRenderResult(
                outputs=outputs,
                errors=output_errors,
            )
            inspection_values = ValueReadResult(
                values={
                    selector: inspection_value(value)
                    for selector, value in values.values.items()
                },
                errors=values.errors,
            )
            return RuntimeProbe(
                cells=cells,
                values=inspection_values,
                outputs=output_result,
            )
    finally:
        try:
            if session is not None:
                manager.close_session(session_id)
                shutdown_deadline = min(
                    loop.time() + 5,
                    deadline + _POST_DEADLINE_SHUTDOWN_GRACE,
                )
                while (
                    session.kernel_state() is not KernelState.STOPPED
                    and loop.time() < shutdown_deadline
                ):
                    await asyncio.sleep(0.01)
        finally:
            try:
                manager.shutdown()
            finally:
                # The in-process Marimo kernel installs its own main module
                # for notebook pickling. Return ownership to the caller after
                # the session and its kernel have stopped.
                sys.modules["__main__"] = main_module


async def _read_values_within_deadline(
    session: Any,
    specifications: dict[str, tuple[str, tuple[tuple[str, str | int], ...]]],
    *,
    consumer_id: str,
    max_value_bytes: int,
    loop: asyncio.AbstractEventLoop,
    deadline: float,
    timeout: float,
) -> ValueReadResult:
    try:
        return await read_probe_values(
            session,
            specifications,
            consumer_id=consumer_id,
            timeout=_remaining_runtime_time(loop, deadline, timeout),
            max_value_bytes=max_value_bytes,
        )
    except ProjectionUnavailable as error:
        if error.code == "read-timeout":
            raise _projection_timeout(timeout) from error
        raise


async def _render_output_within_deadline(
    session: Any,
    specifications: dict[str, tuple[str, tuple[tuple[str, str | int], ...]]],
    active_specifications: dict[str, tuple[str, tuple[tuple[str, str | int], ...]]],
    *,
    consumer_id: str,
    loop: asyncio.AbstractEventLoop,
    deadline: float,
    timeout: float,
) -> OutputRenderResult:
    try:
        return await render_probe_outputs(
            session,
            specifications,
            active_specifications,
            consumer_id=consumer_id,
            timeout=_remaining_runtime_time(loop, deadline, timeout),
        )
    except ProjectionUnavailable as error:
        if error.code == "output-read-timeout":
            raise _projection_timeout(timeout) from error
        raise


def _remaining_runtime_time(
    loop: asyncio.AbstractEventLoop,
    deadline: float,
    timeout: float,
) -> float:
    remaining = deadline - loop.time()
    if remaining <= 0:
        raise _projection_timeout(timeout)
    return remaining


def _projection_timeout(timeout: float) -> RuntimeTimeoutError:
    return RuntimeTimeoutError(
        f"Notebook runtime inspection exceeded {timeout:g} seconds while "
        "reading projected values and outputs"
    )


def _runtime_cell(notification: Any, cell_channel: Any) -> RuntimeCell:
    raw_outputs: list[Any] = []
    if notification is not None:
        if isinstance(notification.console, list):
            raw_outputs.extend(notification.console)
        elif notification.console is not None:
            raw_outputs.append(notification.console)
        if notification.output is not None:
            raw_outputs.append(notification.output)

    outputs: list[RuntimeOutput] = []
    errors: list[str] = []
    for output in raw_outputs:
        channel = str(getattr(output.channel, "value", output.channel))
        data = output.data
        outputs.append(
            RuntimeOutput(
                channel=channel,
                mimetype=str(output.mimetype),
                empty=data in ("", None) or data == {},
            )
        )
        if (
            output.channel == cell_channel.MARIMO_ERROR
            or output.mimetype == "application/vnd.marimo+error"
        ):
            for item in data if isinstance(data, list) else [data]:
                describe = getattr(item, "describe", None)
                message = str(describe()) if callable(describe) else str(item)
                kind = getattr(item, "exception_type", None)
                errors.append(f"{kind}: {message}" if kind else message)
    return RuntimeCell(
        status=notification.status if notification is not None else None,
        outputs=tuple(outputs),
        errors=tuple(errors),
    )
