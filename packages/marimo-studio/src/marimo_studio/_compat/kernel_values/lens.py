"""Share one notebook Lens between the notebook and Studio's preview."""

from collections.abc import Callable, Mapping
from dataclasses import replace
from typing import Any


def lens_overlay(namespace: Mapping[str, object]) -> Mapping[str, object]:
    del namespace
    try:
        from marimo_lens import notebook_lens
    except ImportError:
        return {}

    lens = notebook_lens()
    return {} if lens is None else {"lens": lens}


def _imports_lens(graph: Any) -> bool:
    # A module import such as `import marimo_lens as ml` reaches `ml.Lens`.
    return any(
        imported.namespace == "marimo_lens"
        and (
            imported.imported_symbol is None
            or imported.imported_symbol.rpartition(".")[2] == "Lens"
        )
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
