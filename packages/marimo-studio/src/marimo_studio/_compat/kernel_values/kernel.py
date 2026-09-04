"""Register Studio's projection bridge inside file-backed Marimo kernels."""

from __future__ import annotations

import math
import time
from collections.abc import Callable, Iterator
from contextlib import AbstractAsyncContextManager, contextmanager
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from types import TracebackType
from typing import Any
from uuid import uuid4

from marimo_export.integration import is_owned_session, keep_cached_cells_compatible
from marimo_export.observations import ObservationLedger, install_observation_ledger

from marimo_studio._compat.kernel_values.authorization import (
    STALE_PROJECTION_BINDING_MESSAGE,
    AuthorizedProjections,
    ProjectionAuthorizationError,
    RuntimeCellBinding,
    verify_output_arguments,
    verify_value_ownership_arguments,
)
from marimo_studio._compat.kernel_values.dependencies import (
    current_dependency_closure,
)
from marimo_studio._compat.kernel_values.models import (
    DEFAULT_MAX_VALUE_BYTES,
    FUNCTION_NAME,
    NAMESPACE,
    OUTPUT_FUNCTION_NAME,
    QUERY_FUNCTION_NAME,
    ReadValuesArgs,
    RenderValuesArgs,
    SyncQueryArgs,
)
from marimo_studio._compat.kernel_values.outputs import KernelOutputRenderer
from marimo_studio._compat.kernel_values.query_authorization import (
    verify_query_authorization,
)
from marimo_studio._compat.kernel_values.representations import ValueEncoder
from marimo_studio._compat.kernel_values.selectors import (
    _read_values,
)
from marimo_studio._delivery.urls import PRIVATE_QUERY_KEYS, QUERY_OPERATION_QUERY_PARAM
from marimo_studio._notebook.cell_refs import cell_refs
from marimo_studio._projections.runtime_records import (
    OutputRenderResult,
    ValueReadError,
    ValueReadResult,
)
from marimo_studio._projections.values import MAX_OUTPUT_SELECTORS
from marimo_studio._server.presentation.ports import STALE_PROJECTION_BINDING_CODE
from marimo_studio._server.presentation.query_state import (
    query_fingerprint,
    valid_query_operation_id,
)
from marimo_studio._workspace.config import discover_studio_definition
from marimo_studio.errors import ConfigurationError

_PROBE_LEASE_QUERY_PARAM = "_marimo_studio_probe_lease"
_MAX_QUERY_OPERATIONS = 256


def _current_projection_specs(
    context: Any,
    authorized: AuthorizedProjections,
) -> dict[str, tuple[str, tuple[tuple[str, str | int], ...]]]:
    graph = context._kernel.graph
    current_cells = tuple(
        RuntimeCellBinding(reference, str(cell_id))
        for (cell_id, cell), reference in zip(
            graph.cells.items(),
            cell_refs(cell.code for cell in graph.cells.values()),
            strict=True,
        )
    )
    current_by_runtime_id = {
        binding.runtime_cell_id: binding for binding in current_cells
    }
    for target, binding in authorized.bindings.items():
        # Marimo re-inserts an edited cell at the end of its graph mapping.
        # Restore notebook order from the signed runtime IDs before comparing
        # the live CellRefs and exact ancestor set.
        ordered_current = tuple(
            current
            for expected in binding.dependency_closure
            if (current := current_by_runtime_id.get(expected.runtime_cell_id))
            is not None
        )
        current_closure = current_dependency_closure(
            graph,
            ordered_current,
            binding.runtime_cell_id,
        )
        if tuple(item.runtime_cell_id for item in current_closure) != tuple(
            item.runtime_cell_id for item in binding.dependency_closure
        ):
            raise ProjectionAuthorizationError(STALE_PROJECTION_BINDING_MESSAGE)
        cell = next(
            (
                candidate
                for cell_id, candidate in graph.cells.items()
                if str(cell_id) == binding.runtime_cell_id
            ),
            None,
        )
        variable = authorized.specifications[target][0]
        if cell is None or variable not in cell.defs:
            raise ProjectionAuthorizationError(STALE_PROJECTION_BINDING_MESSAGE)
    return authorized.specifications


@dataclass(frozen=True)
class _ProbeSelectorLease:
    token: str
    notebook: Path
    selectors: tuple[str, ...]
    output_selectors: tuple[str, ...]


_PROBE_SELECTOR_LEASES: dict[str, _ProbeSelectorLease] = {}
_PROBE_SELECTOR_LEASE_LOCK = Lock()


class _CachedCellCompatibility:
    def __init__(self) -> None:
        self._release: Callable[[], None] | None = None

    def activate(self) -> None:
        if self._release is None and not is_owned_session():
            self._release = keep_cached_cells_compatible()

    def close(self) -> None:
        if self._release is None:
            return
        self._release()
        self._release = None


class _EnteredKernelLifespan:
    """Keep an entered Marimo lifespan available for its eventual teardown."""

    def __init__(
        self,
        lifespan: AbstractAsyncContextManager[None],
        resume: Callable[[], None] | None = None,
    ) -> None:
        self._lifespan = lifespan
        self._resume = resume
        self._failure: BaseException | None = None
        self._closed = False

    def fail(self, error: BaseException) -> None:
        if self._failure is None:
            self._failure = error

    async def __aenter__(self) -> None:
        if self._failure is not None:
            raise RuntimeError(
                "The Marimo kernel lifespan setup failed. Restart the kernel "
                "before running notebook code."
            ) from self._failure
        if self._closed:
            raise RuntimeError("The Marimo kernel lifespan has already exited.")
        if self._resume is not None:
            self._resume()
        return None

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None:
        if self._failure is not None or self._closed:
            return False
        return await self._close(exc_type, exc_value, traceback)

    async def _close(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None:
        self._closed = True
        try:
            return await self._lifespan.__aexit__(exc_type, exc_value, traceback)
        except BaseException as error:
            self.fail(error)
            raise


def _guard_entered_lifespan(
    context: Any,
    resume: Callable[[], None] | None = None,
) -> _EnteredKernelLifespan | None:
    kernel = context._kernel
    lifespan = getattr(kernel, "_lifespan", None)
    if lifespan is None:
        return None
    if isinstance(lifespan, _EnteredKernelLifespan):
        return lifespan

    # Marimo queues an instantiation request before each code-mode scratchpad
    # run. Its graph guard follows the lifespan entry, so an initialized kernel
    # otherwise tries to re-enter the same async context manager. Preserve the
    # entered manager for teardown while letting Studio retry after a first save.
    guarded = _EnteredKernelLifespan(lifespan, resume)
    kernel._lifespan = guarded
    return guarded


@contextmanager
def probe_selector_lease(
    notebook: Path,
    selectors: tuple[str, ...],
    output_selectors: tuple[str, ...] = (),
) -> Iterator[dict[str, str | list[str]]]:
    """Permit runtime inspection selectors for an in-process probe kernel."""
    lease = _ProbeSelectorLease(
        token=uuid4().hex,
        notebook=notebook.resolve(),
        selectors=selectors,
        output_selectors=output_selectors,
    )
    with _PROBE_SELECTOR_LEASE_LOCK:
        _PROBE_SELECTOR_LEASES[lease.token] = lease
    try:
        yield {_PROBE_LEASE_QUERY_PARAM: lease.token}
    finally:
        with _PROBE_SELECTOR_LEASE_LOCK:
            _PROBE_SELECTOR_LEASES.pop(lease.token, None)


def _claim_probe_selector_lease(
    context: Any,
    notebook: Path,
) -> _ProbeSelectorLease | None:
    token = context.query_params.get(_PROBE_LEASE_QUERY_PARAM)
    if not isinstance(token, str):
        return None
    context.query_params.remove(_PROBE_LEASE_QUERY_PARAM)
    with _PROBE_SELECTOR_LEASE_LOCK:
        lease = _PROBE_SELECTOR_LEASES.get(token)
        if lease is None or lease.notebook != notebook:
            return None
        return _PROBE_SELECTOR_LEASES.pop(token)


class _KernelBridgeLifespan:
    def __init__(self) -> None:
        self._registry: Any | None = None
        self._output_renderer: KernelOutputRenderer | None = None
        self._value_encoder: ValueEncoder | None = None
        self._query_generation = (-1, -1)
        self._query_operations: dict[str, tuple[str, tuple[int, int]]] = {}
        self._cached_cells = _CachedCellCompatibility()
        self._entered_lifespan: _EnteredKernelLifespan | None = None
        self._observation_ledger: ObservationLedger | None = None
        self._observation_ledger_release: Callable[[], None] | None = None

    def _activate(
        self,
        context: Any,
        filename: Path,
        inspection: _ProbeSelectorLease | None,
    ) -> bool:
        if self._output_renderer is not None:
            return True
        if is_owned_session():
            return False
        try:
            configured = discover_studio_definition(filename) is not None
        except (OSError, UnicodeError, ConfigurationError):
            configured = False
        if inspection is None and not configured:
            return False
        output_renderer = KernelOutputRenderer(context)
        observation_ledger: ObservationLedger | None = None
        observation_ledger_release: Callable[[], None] | None = None
        try:
            from marimo._session.model import SessionMode

            records_observations = (
                configured
                and inspection is None
                and getattr(context, "session_mode", None) == SessionMode.EDIT
                and not is_owned_session()
            )
            if records_observations:
                observation_ledger = ObservationLedger(filename)
            self._cached_cells.activate()
            if observation_ledger is not None:
                observation_ledger_release = install_observation_ledger(
                    context,
                    observation_ledger,
                )
        except BaseException as error:
            cleanup_error: BaseException | None = None
            if observation_ledger_release is not None:
                try:
                    observation_ledger_release()
                except BaseException as cleanup:
                    cleanup_error = cleanup
            if observation_ledger is not None:
                try:
                    observation_ledger.close()
                except BaseException as cleanup:
                    if cleanup_error is None:
                        cleanup_error = cleanup
            try:
                self._cached_cells.close()
            except BaseException as cleanup:
                if cleanup_error is None:
                    cleanup_error = cleanup
            try:
                output_renderer.close()
            except BaseException as cleanup:
                if cleanup_error is None:
                    cleanup_error = cleanup
            if cleanup_error is not None:
                raise error from cleanup_error
            raise
        self._observation_ledger = observation_ledger
        self._observation_ledger_release = observation_ledger_release
        self._output_renderer = output_renderer
        self._value_encoder = ValueEncoder(context)
        return True

    async def __aenter__(self) -> None:
        self._resume()

    def _resume(self) -> None:
        from marimo._runtime.context import get_context
        from marimo._runtime.context.kernel_context import KernelRuntimeContext
        from marimo._runtime.functions import Function
        from marimo._types.ids import CellId_t

        context = get_context()
        if not isinstance(context, KernelRuntimeContext):
            return
        self._entered_lifespan = _guard_entered_lifespan(context, self._resume)
        raw_filename = context.filename or getattr(
            getattr(context._kernel, "app_metadata", None),
            "filename",
            None,
        )
        if raw_filename is None:
            return
        try:
            self._enter(
                context,
                Function,
                CellId_t,
                filename=Path(raw_filename).resolve(),
            )
        except BaseException as error:
            if self._entered_lifespan is not None:
                self._entered_lifespan.fail(error)
            try:
                self._close()
            except BaseException as cleanup_error:
                raise error from cleanup_error
            raise

    def _enter_after_filename(
        self,
        context: Any,
        function_type: Any,
        cell_id_type: Any,
    ) -> bool:
        if context.filename is None:
            return False
        try:
            self._enter(context, function_type, cell_id_type)
        except BaseException as error:
            try:
                self._close()
            except BaseException as cleanup_error:
                raise error from cleanup_error
            raise
        return True

    def _enter(
        self,
        context: Any,
        function_type: Any,
        cell_id_type: Any,
        *,
        filename: Path | None = None,
    ) -> None:
        from marimo._messaging.notification import (
            QueryParamsDeleteNotification,
            QueryParamsSetNotification,
        )
        from marimo._messaging.notification_utils import broadcast_notification

        filename = filename or Path(context.filename).resolve()
        inspection = _claim_probe_selector_lease(context, filename)
        if self._registry is not None:
            self._activate(context, filename, inspection)
            return
        self._activate(context, filename, inspection)

        # Keep the functions registered while the renderer waits for a Studio
        # definition created during the session.
        def read(args: ReadValuesArgs) -> dict[str, object]:
            try:
                authorized, active_authorized = verify_value_ownership_arguments(
                    revision=args.revision,
                    projections=args.projections,
                    active_projections=args.active_projections,
                    consumer_id=args.consumer_id,
                    authorization=args.authorization,
                    probe_targets=(
                        inspection.selectors if inspection is not None else None
                    ),
                )
                if inspection is not None:
                    specifications = authorized.specifications
                    active_specifications = active_authorized.specifications
                else:
                    specifications = _current_projection_specs(context, authorized)
                    active_specifications = _current_projection_specs(
                        context, active_authorized
                    )
            except ProjectionAuthorizationError as error:
                stale_binding = str(error) == STALE_PROJECTION_BINDING_MESSAGE
                return ValueReadResult(
                    values={},
                    errors={
                        "*": ValueReadError(
                            (
                                STALE_PROJECTION_BINDING_CODE
                                if stale_binding
                                else "projection-authorization-invalid"
                            ),
                            str(error),
                        )
                    },
                ).to_dict()
            if not self._activate(context, filename, inspection):
                if self._value_encoder is not None:
                    self._value_encoder.release_consumer(args.consumer_id)
                return ValueReadResult(
                    values={},
                    errors={
                        selector: ValueReadError(
                            "unknown-selector",
                            f"Selector {selector!r} is not present in a "
                            "configured view.",
                        )
                        for selector in dict.fromkeys(
                            (*specifications, *active_specifications)
                        )
                    },
                ).to_dict()
            limit = max(1, min(args.max_value_bytes, DEFAULT_MAX_VALUE_BYTES))
            value_encoder = self._value_encoder
            assert value_encoder is not None
            if not specifications and not active_specifications:
                value_encoder.release_consumer(args.consumer_id)
                return ValueReadResult(values={}, errors={}).to_dict()
            kernel = context._kernel
            with kernel.lock_globals():
                result = _read_values(
                    kernel.globals,
                    specifications,
                    active_specifications,
                    max_value_bytes=limit,
                    consumer_id=args.consumer_id,
                    revision=args.revision,
                    encoder=value_encoder,
                )
            return ValueReadResult(
                result.values,
                result.errors,
            ).to_dict()

        function = function_type(FUNCTION_NAME, ReadValuesArgs, read)
        function.cell_id = cell_id_type("__marimo_studio_values__")
        context.function_registry.register(NAMESPACE, function)
        self._registry = context.function_registry

        def render_outputs(args: RenderValuesArgs) -> dict[str, object]:
            try:
                authorized, active_authorized = verify_output_arguments(
                    revision=args.revision,
                    projections=args.projections,
                    active_projections=args.active_projections,
                    consumer_id=args.consumer_id,
                    authorization=args.authorization,
                    probe_targets=(
                        inspection.output_selectors if inspection is not None else None
                    ),
                )
                if inspection is not None:
                    specifications = authorized.specifications
                    active_specifications = active_authorized.specifications
                else:
                    specifications = _current_projection_specs(context, authorized)
                    active_specifications = _current_projection_specs(
                        context, active_authorized
                    )
            except ProjectionAuthorizationError as error:
                stale_binding = str(error) == STALE_PROJECTION_BINDING_MESSAGE
                return OutputRenderResult(
                    outputs={},
                    errors={
                        "*": ValueReadError(
                            (
                                STALE_PROJECTION_BINDING_CODE
                                if stale_binding
                                else "projection-authorization-invalid"
                            ),
                            str(error),
                        )
                    },
                ).to_dict()
            if not self._activate(context, filename, inspection):
                requested = tuple(
                    dict.fromkeys((*specifications, *active_specifications))
                )
                return OutputRenderResult(
                    outputs={},
                    errors={
                        selector: ValueReadError(
                            "unknown-selector",
                            f"Selector {selector!r} is not present in a "
                            "configured view.",
                        )
                        for selector in requested
                    },
                ).to_dict()
            selectors = tuple(specifications)
            active_selectors = tuple(active_specifications)
            if (
                len(selectors) > MAX_OUTPUT_SELECTORS
                or len(active_selectors) > MAX_OUTPUT_SELECTORS
            ):
                return OutputRenderResult(
                    outputs={},
                    errors={
                        "*": ValueReadError(
                            "too-many-selectors",
                            "An output request may contain at most "
                            f"{MAX_OUTPUT_SELECTORS} selectors.",
                        )
                    },
                ).to_dict()
            limit = max(1, min(args.max_output_bytes, DEFAULT_MAX_VALUE_BYTES))
            kernel = context._kernel
            output_renderer = self._output_renderer
            assert output_renderer is not None
            with kernel.lock_globals():
                result = output_renderer.render(
                    kernel.globals,
                    selectors,
                    active_selectors,
                    set(active_specifications),
                    consumer_id=args.consumer_id,
                    max_output_bytes=limit,
                )
            return OutputRenderResult(
                result.outputs,
                result.errors,
            ).to_dict()

        output_function = function_type(
            OUTPUT_FUNCTION_NAME,
            RenderValuesArgs,
            render_outputs,
        )
        output_function.cell_id = cell_id_type("__marimo_studio_outputs__")
        context.function_registry.register(NAMESPACE, output_function)

        def sync_query(args: SyncQueryArgs) -> dict[str, object]:
            query = {
                key: value
                for key, value in args.query.items()
                if key not in PRIVATE_QUERY_KEYS
            }
            fingerprint = query_fingerprint(query)
            if (
                not verify_query_authorization(args, filename)
                or not valid_query_operation_id(args.operation_id)
                or args.fingerprint != fingerprint
                or isinstance(args.binding_generation, bool)
                or not isinstance(args.binding_generation, int)
                or args.binding_generation < 0
                or isinstance(args.query_generation, bool)
                or not isinstance(args.query_generation, int)
                or args.query_generation < 0
                or isinstance(args.deadline, bool)
                or not isinstance(args.deadline, (int, float))
                or not math.isfinite(args.deadline)
            ):
                raise ValueError("The query operation identity is invalid.")
            generation = (args.binding_generation, args.query_generation)
            previous = self._query_operations.get(args.operation_id)
            if previous is not None and previous != (fingerprint, generation):
                raise ValueError(
                    "The query operation ID was already used for a different query."
                )
            result = {
                "operation_id": args.operation_id,
                "fingerprint": fingerprint,
                "binding_generation": args.binding_generation,
                "query_generation": args.query_generation,
                "deadline": args.deadline,
            }
            if generation < self._query_generation:
                return {**result, "status": "superseded"}
            if generation == self._query_generation:
                if previous is None:
                    raise ValueError("The query generation identity is invalid.")
                broadcast_notification(
                    QueryParamsSetNotification(
                        QUERY_OPERATION_QUERY_PARAM,
                        args.operation_id,
                    ),
                    context.stream,
                )
                broadcast_notification(
                    QueryParamsDeleteNotification(
                        QUERY_OPERATION_QUERY_PARAM,
                        None,
                    ),
                    context.stream,
                )
                return {**result, "status": "applied"}
            if time.monotonic() >= args.deadline:
                return {**result, "status": "expired"}
            if not self._activate(context, filename, inspection):
                raise RuntimeError("The Studio query bridge is still starting.")
            if time.monotonic() >= args.deadline:
                return {**result, "status": "expired"}
            params = context.query_params
            current = dict(params.to_dict())
            broadcast_notification(
                QueryParamsSetNotification(
                    QUERY_OPERATION_QUERY_PARAM,
                    args.operation_id,
                ),
                context.stream,
            )
            try:
                for key in current.keys() - query.keys() - PRIVATE_QUERY_KEYS:
                    params.remove(key)
                for key, value in query.items():
                    if current.get(key) != value:
                        params.set(key, value)
                self._query_generation = generation
                self._query_operations[args.operation_id] = (fingerprint, generation)
                if len(self._query_operations) > _MAX_QUERY_OPERATIONS:
                    oldest = next(iter(self._query_operations))
                    self._query_operations.pop(oldest)
                return {**result, "status": "applied"}
            finally:
                broadcast_notification(
                    QueryParamsDeleteNotification(
                        QUERY_OPERATION_QUERY_PARAM,
                        None,
                    ),
                    context.stream,
                )

        query_function = function_type(
            QUERY_FUNCTION_NAME,
            SyncQueryArgs,
            sync_query,
        )
        query_function.cell_id = cell_id_type("__marimo_studio_query__")
        context.function_registry.register(NAMESPACE, query_function)

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool:
        del traceback
        if exc_type is not None and self._entered_lifespan is not None:
            self._entered_lifespan.fail(
                exc_value
                if exc_value is not None
                else RuntimeError("The Marimo kernel lifespan setup failed.")
            )
        self._close()
        return False

    def _close(self) -> None:
        failure: BaseException | None = None
        if self._value_encoder is not None:
            try:
                self._value_encoder.close()
            except BaseException as error:
                failure = error
            else:
                self._value_encoder = None
        if self._output_renderer is not None:
            try:
                self._output_renderer.close()
            except BaseException as error:
                if failure is None:
                    failure = error
            else:
                self._output_renderer = None
        if self._registry is not None:
            try:
                self._registry.delete(NAMESPACE)
            except BaseException as error:
                if failure is None:
                    failure = error
            else:
                self._registry = None
        try:
            self._cached_cells.close()
        except BaseException as error:
            if failure is None:
                failure = error
        if failure is not None:
            raise failure


def kernel_lifespan(_: None) -> _KernelBridgeLifespan:
    """Register projection functions and activate configured Studio kernels."""
    return _KernelBridgeLifespan()
