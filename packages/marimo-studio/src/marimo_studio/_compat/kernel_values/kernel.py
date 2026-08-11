"""Register Studio's projection bridge inside file-backed Marimo kernels."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import AbstractAsyncContextManager, contextmanager
from pathlib import Path
from types import TracebackType
from typing import Any

from marimo_studio._compat.cached_cells import keep_cached_cells_compatible
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
from marimo_studio._compat.kernel_values.selectors import (
    _read_values,
    _template_output_selectors,
    _template_selectors,
)
from marimo_studio._urls import PRIVATE_QUERY_KEYS, QUERY_OPERATION_QUERY_PARAM
from marimo_studio._workspace.config import discover_studio_definition
from marimo_studio.errors import ConfigurationError
from marimo_studio.types import OutputRenderResult, ValueReadError, ValueReadResult
from marimo_studio.values import MAX_OUTPUT_SELECTORS

_INSPECTION_SELECTORS: dict[Path, tuple[str, ...]] = {}
_INSPECTION_OUTPUT_SELECTORS: dict[Path, tuple[str, ...]] = {}


class _EnteredKernelLifespan:
    """Keep an entered Marimo lifespan available for its eventual teardown."""

    def __init__(self, lifespan: AbstractAsyncContextManager[None]) -> None:
        self._lifespan = lifespan
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
        return None

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None:
        if self._failure is not None or self._closed:
            return False
        self._closed = True
        try:
            return await self._lifespan.__aexit__(exc_type, exc_value, traceback)
        except BaseException as error:
            self.fail(error)
            raise


def _guard_entered_lifespan(context: Any) -> _EnteredKernelLifespan | None:
    kernel = context._kernel
    lifespan = getattr(kernel, "_lifespan", None)
    if lifespan is None:
        return None
    if isinstance(lifespan, _EnteredKernelLifespan):
        return lifespan

    # Marimo queues an instantiation request before each code-mode scratchpad
    # run. Its graph guard follows the lifespan entry, so an initialized kernel
    # otherwise tries to re-enter the same async context manager. Preserve the
    # entered manager for teardown while treating later entries as idempotent.
    guarded = _EnteredKernelLifespan(lifespan)
    kernel._lifespan = guarded
    return guarded


@contextmanager
def inspection_selectors(
    notebook: Path,
    selectors: tuple[str, ...],
    output_selectors: tuple[str, ...] = (),
) -> Iterator[None]:
    """Permit runtime inspection selectors for an in-process probe kernel."""
    path = notebook.resolve()
    _INSPECTION_SELECTORS[path] = selectors
    _INSPECTION_OUTPUT_SELECTORS[path] = output_selectors
    try:
        yield
    finally:
        _INSPECTION_SELECTORS.pop(path, None)
        _INSPECTION_OUTPUT_SELECTORS.pop(path, None)


class _KernelBridgeLifespan:
    def __init__(self) -> None:
        self._registry: Any | None = None
        self._output_renderer: KernelOutputRenderer | None = None
        self._release_cached_ui: Callable[[], None] | None = None
        self._entered_lifespan: _EnteredKernelLifespan | None = None

    def _activate(
        self,
        context: Any,
        filename: Path,
        inspection: tuple[str, ...] | None,
    ) -> bool:
        if self._output_renderer is not None:
            return True
        if inspection is None:
            try:
                if discover_studio_definition(filename) is None:
                    return False
            except (OSError, UnicodeError, ConfigurationError):
                return False
        output_renderer = KernelOutputRenderer(context)
        try:
            release_cached_ui = keep_cached_cells_compatible()
        except BaseException:
            output_renderer.close()
            raise
        self._output_renderer = output_renderer
        self._release_cached_ui = release_cached_ui
        return True

    async def __aenter__(self) -> None:
        from marimo._runtime.context import get_context
        from marimo._runtime.context.kernel_context import KernelRuntimeContext
        from marimo._runtime.functions import Function
        from marimo._types.ids import CellId_t

        context = get_context()
        if not isinstance(context, KernelRuntimeContext):
            return
        self._entered_lifespan = _guard_entered_lifespan(context)
        if context.filename is None:
            return
        try:
            self._enter(context, Function, CellId_t)
        except BaseException as error:
            if self._entered_lifespan is not None:
                self._entered_lifespan.fail(error)
            try:
                self._close()
            except BaseException as cleanup_error:
                raise error from cleanup_error
            raise

    def _enter(
        self,
        context: Any,
        function_type: Any,
        cell_id_type: Any,
    ) -> None:
        from marimo._messaging.notification import (
            QueryParamsDeleteNotification,
            QueryParamsSetNotification,
        )
        from marimo._messaging.notification_utils import broadcast_notification

        filename = Path(context.filename).resolve()
        inspection = _INSPECTION_SELECTORS.get(filename)
        inspection_outputs = _INSPECTION_OUTPUT_SELECTORS.get(filename)
        self._activate(context, filename, inspection)

        # Keep the functions registered while the renderer waits for a Studio
        # definition created during the session.
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
            if not self._activate(context, filename, inspection):
                return ValueReadResult(
                    values={},
                    errors={
                        selector: ValueReadError(
                            "unknown-selector",
                            f"Selector {selector!r} is not present in a "
                            "configured view.",
                        )
                        for selector in dict.fromkeys(args.selectors)
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

        function = function_type(FUNCTION_NAME, ReadValuesArgs, read)
        function.cell_id = cell_id_type("__marimo_studio_values__")
        context.function_registry.register(NAMESPACE, function)
        self._registry = context.function_registry

        def render_outputs(args: RenderValuesArgs) -> dict[str, object]:
            try:
                allowed = (
                    set(_template_output_selectors(filename) or ())
                    if inspection_outputs is None
                    else set(inspection_outputs)
                )
            except (OSError, UnicodeError, ConfigurationError) as error:
                requested = tuple(
                    dict.fromkeys((*args.selectors, *args.active_selectors))
                )
                return OutputRenderResult(
                    outputs={},
                    errors={
                        selector: ValueReadError(
                            "studio-unavailable",
                            f"Studio output selectors are unavailable: {error}",
                        )
                        for selector in requested
                    },
                ).to_dict()
            if not self._activate(context, filename, inspection):
                requested = tuple(
                    dict.fromkeys((*args.selectors, *args.active_selectors))
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
            selectors = tuple(dict.fromkeys(args.selectors))
            active_selectors = tuple(dict.fromkeys(args.active_selectors))
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
                return output_renderer.render(
                    kernel.globals,
                    selectors,
                    active_selectors,
                    allowed,
                    consumer_id=args.consumer_id,
                    max_output_bytes=limit,
                ).to_dict()

        output_function = function_type(
            OUTPUT_FUNCTION_NAME,
            RenderValuesArgs,
            render_outputs,
        )
        output_function.cell_id = cell_id_type("__marimo_studio_outputs__")
        context.function_registry.register(NAMESPACE, output_function)

        def sync_query(args: SyncQueryArgs) -> None:
            if not self._activate(context, filename, inspection):
                return
            params = context.query_params
            current = dict(params.to_dict())
            query = {
                key: value
                for key, value in args.query.items()
                if key not in PRIVATE_QUERY_KEYS
            }
            if args.operation_id:
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
            finally:
                if args.operation_id:
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
        if self._output_renderer is not None:
            self._output_renderer.close()
            self._output_renderer = None
        if self._registry is not None:
            self._registry.delete(NAMESPACE)
            self._registry = None
        if self._release_cached_ui is not None:
            self._release_cached_ui()
            self._release_cached_ui = None


def kernel_lifespan(_: None) -> _KernelBridgeLifespan:
    """Register projection functions and activate configured Studio kernels."""
    return _KernelBridgeLifespan()
