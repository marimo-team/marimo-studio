"""Register Studio's value reader inside a Marimo kernel."""

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
    QUERY_FUNCTION_NAME,
    ReadValuesArgs,
    SyncQueryArgs,
)
from marimo_studio._compat.kernel_values.selectors import (
    _read_values,
    _template_selectors,
)
from marimo_studio._urls import PRIVATE_QUERY_KEYS
from marimo_studio._workspace.config import discover_studio_definition
from marimo_studio.errors import ConfigurationError
from marimo_studio.types import ValueReadError, ValueReadResult

_INSPECTION_SELECTORS: dict[Path, tuple[str, ...]] = {}


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
        self._release_cached_ui: Callable[[], None] | None = None

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
                if discover_studio_definition(filename) is None:
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

        def sync_query(args: SyncQueryArgs) -> None:
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
        self._release_cached_ui = keep_cached_cells_compatible()

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
        if self._release_cached_ui is not None:
            self._release_cached_ui()
            self._release_cached_ui = None
        return False


def kernel_lifespan(_: None) -> _KernelValueLifespan:
    """Register the value function in kernels backed by Studio configuration."""
    return _KernelValueLifespan()
