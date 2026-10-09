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

from marimo_studio._compat.kernel_values import (
    probe_selector_lease,
    read_probe_values,
    render_probe_outputs,
)
from marimo_studio._compat.kernel_values.representations import inspection_value
from marimo_studio._compat.runtime_requests import instantiate_notebook_request
from marimo_studio._notebook.source_generation import NotebookSourceGeneration
from marimo_studio._processes.limits import DEFAULT_RUNTIME_TIMEOUT
from marimo_studio._projections.runtime_records import (
    OutputGroup,
    OutputRenderResult,
    RenderedOutput,
    RuntimeCell,
    RuntimeOutput,
    RuntimeProbe,
    ValueReadError,
    ValueReadResult,
)
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
    value_selector_groups: tuple[tuple[str, ...], ...] = (),
    output_groups: tuple[OutputGroup, ...] = (),
    timeout: float = DEFAULT_RUNTIME_TIMEOUT,
    show_tracebacks: bool = False,
    max_json_bytes: int | None = None,
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

    allowed_values = tuple(
        dict.fromkeys(selector for group in value_selector_groups for selector in group)
    )
    allowed_outputs = tuple(
        dict.fromkeys(selector for group in output_groups for selector in group)
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
        with probe_selector_lease(
            path, allowed_values, allowed_outputs
        ) as query_params:
            try:
                session = await asyncio.wait_for(
                    manager.create_session(
                        session_id,
                        consumer,
                        query_params=query_params,
                        file_key=str(path),
                        auto_instantiate=True,
                    ),
                    timeout=max(0, deadline - loop.time()),
                )
            except asyncio.TimeoutError as error:
                raise RuntimeTimeoutError(
                    f"Notebook runtime did not start within {timeout:g} seconds"
                ) from error
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
            # Each group is one value read, so per-read budgets match views.
            read_values: dict[str, object] = {}
            read_errors: dict[str, ValueReadError] = {}
            for value_group in value_selector_groups:
                read = await _read_values_within_deadline(
                    session,
                    value_group,
                    consumer_id=str(consumer.consumer_id),
                    max_json_bytes=max_json_bytes,
                    loop=loop,
                    deadline=deadline,
                    timeout=timeout,
                )
                response_error = read.errors.get("*")
                for selector in value_group:
                    error = read.errors.get(selector) or response_error
                    if error is not None:
                        read_values.pop(selector, None)
                        read_errors[selector] = error
                    elif selector in read.values:
                        read_errors.pop(selector, None)
                        # Drop inline Arrow bytes before the next read.
                        read_values[selector] = inspection_value(read.values[selector])
            outputs: dict[str, RenderedOutput] = {}
            output_errors: dict[str, ValueReadError] = {}
            for group in output_groups:
                for selector, accept in group.items():
                    rendered = await _render_output_within_deadline(
                        session,
                        {selector: accept},
                        group,
                        consumer_id=str(consumer.consumer_id),
                        loop=loop,
                        deadline=deadline,
                        timeout=timeout,
                    )
                    error = rendered.errors.get(selector) or rendered.errors.get("*")
                    output = rendered.outputs.get(selector)
                    # Views can read one target with different accept lists, so
                    # a failure in any view stands for the target.
                    if error is not None:
                        outputs.pop(selector, None)
                        output_errors.setdefault(selector, error)
                    elif output is not None and selector not in output_errors:
                        outputs[selector] = output
            output_result = OutputRenderResult(
                outputs=outputs,
                errors=output_errors,
            )
            return RuntimeProbe(
                cells=cells,
                values=ValueReadResult(values=read_values, errors=read_errors),
                outputs=output_result,
            )
    finally:
        try:
            # A startup timeout can leave a completed launch without its waiter.
            session = session or manager.get_session(session_id)
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
                await manager.shutdown()
            finally:
                # The in-process Marimo kernel installs its own main module
                # for notebook pickling. Return ownership to the caller after
                # the session and its kernel have stopped.
                sys.modules["__main__"] = main_module


async def _read_values_within_deadline(
    session: Any,
    selectors: tuple[str, ...],
    *,
    consumer_id: str,
    max_json_bytes: int | None,
    loop: asyncio.AbstractEventLoop,
    deadline: float,
    timeout: float,
) -> ValueReadResult:
    try:
        return await read_probe_values(
            session,
            selectors,
            consumer_id=consumer_id,
            timeout=_remaining_runtime_time(loop, deadline, timeout),
            max_json_bytes=max_json_bytes,
        )
    except ProjectionUnavailable as error:
        if error.code == "read-timeout":
            raise _projection_timeout(timeout) from error
        raise


async def _render_output_within_deadline(
    session: Any,
    outputs: OutputGroup,
    active_outputs: OutputGroup,
    *,
    consumer_id: str,
    loop: asyncio.AbstractEventLoop,
    deadline: float,
    timeout: float,
) -> OutputRenderResult:
    try:
        return await render_probe_outputs(
            session,
            outputs,
            active_outputs,
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
