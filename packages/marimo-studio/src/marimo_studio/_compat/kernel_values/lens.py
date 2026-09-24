"""Share one notebook Lens between the notebook and Studio's preview."""

from collections.abc import Callable, Mapping
from dataclasses import replace
from importlib import import_module
from importlib.util import find_spec
from typing import Any

from marimo_studio._projections import STUDIO_RESULT_SELECTOR

_OWNER = "__marimo_studio_lens__"


class LensOverlay:
    def __init__(self, context: Any) -> None:
        self._context = context
        self._owned: Any = None

    def __call__(self, namespace: Mapping[str, object]) -> Mapping[str, object]:
        from marimo._plugins.ui._impl.from_anywidget import anywidget
        from marimo._types.ids import CellId_t

        if find_spec("marimo_lens") is None:
            return {}
        lens_type = import_module("marimo_lens").Lens
        values = (
            *namespace.values(),
            *(
                element.widget
                for ref in tuple(self._context.ui_element_registry._objects.values())
                if isinstance(element := ref(), anywidget)
            ),
        )
        for value in values:
            if (
                isinstance(value, lens_type)
                and value is not self._owned
                and getattr(value, "comm", None) is not None
            ):
                self.close()
                return {"lens": value}
        if self._owned is None or self._owned.comm is None:
            with self._context.with_cell_id(CellId_t(_OWNER)):
                self._owned = lens_type(dom_selector=STUDIO_RESULT_SELECTOR)
        return {"lens": self._owned}

    def close(self) -> None:
        if self._owned is not None:
            self._owned.close()
            self._owned = None
            self._context.cell_lifecycle_registry.dispose(_OWNER, deletion=True)


def _imports_lens(graph: Any) -> bool:
    return any(
        imported.namespace == "marimo_lens"
        and (imported.imported_symbol or "").rpartition(".")[2] == "Lens"
        for cell in graph.cells.values()
        for imported in cell.imports
    )


class LensMountPolicy:
    """Keep Marimo's automatic Lens out of Studio notebooks that author one.

    Marimo mounts a default Lens after the cell that imports marimo runs unless
    an earlier cell output already holds one. That cell usually runs before the
    cell that constructs an authored Lens, so the notebook would hold two.
    """

    def __init__(self, context: Any, hosts_lens: Callable[[], bool]) -> None:
        self._context = context
        self._hosts_lens = hosts_lens
        self._release: Callable[[], None] | None = None

    def open(self) -> None:
        from marimo._runtime.runner.hooks import HookPhase, NotebookCellHooks
        from marimo._runtime.runner.hooks_lens import mount_lens

        cell_hooks = getattr(getattr(self._context, "_kernel", None), "_hooks", None)
        if not isinstance(cell_hooks, NotebookCellHooks):
            return
        hooks = cell_hooks._lists[HookPhase.POST_EXECUTION]
        index = next(
            (
                position
                for position, entry in enumerate(hooks._entries)
                if entry.hook is mount_lens
            ),
            None,
        )
        if index is None:
            return

        def mount_unless_authored(cell: Any, hook_context: Any, result: Any) -> None:
            if (
                cell.namespace_to_variable("marimo") is not None
                and _imports_lens(hook_context.graph)
                and self._hosts_lens()
            ):
                return
            mount_lens(cell, hook_context, result)

        hooks._entries[index] = replace(
            hooks._entries[index], hook=mount_unless_authored
        )
        hooks._sorted = None

        def release() -> None:
            for position, entry in enumerate(hooks._entries):
                if entry.hook is mount_unless_authored:
                    hooks._entries[position] = replace(entry, hook=mount_lens)
                    hooks._sorted = None
                    return

        self._release = release

    def close(self) -> None:
        release, self._release = self._release, None
        if release is not None:
            release()
