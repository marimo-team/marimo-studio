"""Register Studio's projection bridge inside file-backed Marimo kernels."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
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
from marimo_studio._urls import PRIVATE_QUERY_KEYS
from marimo_studio._workspace.config import discover_studio_definition
from marimo_studio.errors import ConfigurationError
from marimo_studio.types import OutputRenderResult, ValueReadError, ValueReadResult
from marimo_studio.values import MAX_OUTPUT_SELECTORS

_INSPECTION_SELECTORS: dict[Path, tuple[str, ...]] = {}
_INSPECTION_OUTPUT_SELECTORS: dict[Path, tuple[str, ...]] = {}


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
        release_cached_ui = keep_cached_cells_compatible()
        self._output_renderer = output_renderer
        self._release_cached_ui = release_cached_ui
        return True

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
        inspection_outputs = _INSPECTION_OUTPUT_SELECTORS.get(filename)
        self._activate(context, filename, inspection)

        # Marimo enters the lifespan once. Keep the functions registered while
        # the renderer waits for a Studio definition created during the session.
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

        function = Function(FUNCTION_NAME, ReadValuesArgs, read)
        function.cell_id = CellId_t("__marimo_studio_values__")
        context.function_registry.register(NAMESPACE, function)

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
                return OutputRenderResult(
                    outputs={},
                    errors={
                        selector: ValueReadError(
                            "unknown-selector",
                            f"Selector {selector!r} is not present in a "
                            "configured view.",
                        )
                        for selector in dict.fromkeys(args.selectors)
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

        output_function = Function(
            OUTPUT_FUNCTION_NAME,
            RenderValuesArgs,
            render_outputs,
        )
        output_function.cell_id = CellId_t("__marimo_studio_outputs__")
        context.function_registry.register(NAMESPACE, output_function)

        def sync_query(args: SyncQueryArgs) -> None:
            if not self._activate(context, filename, inspection):
                return
            params = context.query_params
            current = dict(params.to_dict())
            for key in current.keys() - args.query.keys() - PRIVATE_QUERY_KEYS:
                params.remove(key)
            for key, value in args.query.items():
                if current.get(key) != value:
                    params.set(key, value)

        query_function = Function(
            QUERY_FUNCTION_NAME,
            SyncQueryArgs,
            sync_query,
        )
        query_function.cell_id = CellId_t("__marimo_studio_query__")
        context.function_registry.register(NAMESPACE, query_function)
        self._registry = context.function_registry

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool:
        del exc_type, exc_value, traceback
        if self._output_renderer is not None:
            self._output_renderer.close()
            self._output_renderer = None
        if self._registry is not None:
            self._registry.delete(NAMESPACE)
            self._registry = None
        if self._release_cached_ui is not None:
            self._release_cached_ui()
            self._release_cached_ui = None
        return False


def kernel_lifespan(_: None) -> _KernelBridgeLifespan:
    """Register projection functions and activate configured Studio kernels."""
    return _KernelBridgeLifespan()
