"""Prepare notebook-aware provider context and durable cell bindings."""

from __future__ import annotations

from collections.abc import Iterable
from types import MappingProxyType

from marimo_studio._notebook.cell_refs import safe_cell_ref_matches
from marimo_studio._notebook.records import CellRef, NotebookSpec
from marimo_studio._workspace.models import (
    ALIAS_PATTERN,
    StudioDefinition,
)
from marimo_studio.errors import ConfigurationError
from marimo_studio.view_providers import (
    StarterCellTarget,
    StarterContext,
    StarterPlan,
)


def _resolved_aliases(
    notebook: NotebookSpec,
    studio: StudioDefinition | None,
) -> dict[CellRef, tuple[str, ...]]:
    if studio is None or not studio.cells:
        return {}
    cells_by_runtime_id = {cell.runtime_id: cell for cell in notebook.cells}
    matches = safe_cell_ref_matches(
        studio.cells,
        ((cell.ref, cell.runtime_id) for cell in notebook.cells),
    )
    aliases: dict[CellRef, list[str]] = {}
    for alias, runtime_id in sorted(matches.items()):
        aliases.setdefault(cells_by_runtime_id[runtime_id].ref, []).append(alias)
    return {ref: tuple(names) for ref, names in aliases.items()}


def _proposed_alias(index: int, occupied: set[str]) -> str:
    base = f"cell-{index + 1}"
    candidate = base
    suffix = 2
    while candidate in occupied:
        candidate = f"{base}-{suffix}"
        suffix += 1
    return candidate


def starter_context(
    notebook: NotebookSpec,
    studio: StudioDefinition | None,
    view_name: str,
) -> StarterContext:
    """Return one detached notebook snapshot with a target for each ordinary cell."""
    aliases = _resolved_aliases(notebook, studio)
    occupied = {
        cell.name
        for cell in notebook.cells
        if cell.kind == "cell" and cell.name is not None
    }
    if studio is not None:
        occupied.update(studio.cells)
    targets: dict[CellRef, StarterCellTarget] = {}
    for cell in notebook.cells:
        if cell.kind != "cell":
            continue
        if cell.name is not None:
            target = cell.name
        elif aliases.get(cell.ref):
            target = aliases[cell.ref][0]
        else:
            target = _proposed_alias(cell.index, occupied)
        occupied.add(target)
        targets[cell.ref] = StarterCellTarget(cell.ref, target)
    return StarterContext(
        view_name=view_name,
        notebook_name=notebook.path.stem,
        notebook=notebook,
        cell_targets=MappingProxyType(targets),
    )


def starter_bindings(
    notebook: NotebookSpec,
    studio: StudioDefinition | None,
    plans: Iterable[StarterPlan],
) -> dict[str, CellRef]:
    """Return the cell aliases required by generated starter source."""
    cells = notebook.by_ref()
    selected: dict[str, CellRef] = {}
    for plan in plans:
        for item in plan.cell_targets:
            current = selected.get(item.target)
            if current is not None and current != item.cell:
                raise ConfigurationError(
                    f"Starter cell target {item.target!r} names more than one cell. "
                    "Run the operation again."
                )
            selected[item.target] = item.cell

    native = {
        cell.name: cell.ref
        for cell in notebook.cells
        if cell.kind == "cell" and cell.name is not None
    }
    configured = studio.cells if studio is not None else {}
    matched = safe_cell_ref_matches(
        configured,
        ((cell.ref, cell.runtime_id) for cell in notebook.cells),
    )
    cells_by_runtime_id = {cell.runtime_id: cell for cell in notebook.cells}
    bindings: dict[str, CellRef] = {}
    for target, ref in selected.items():
        cell = cells.get(ref)
        if cell is None or cell.kind != "cell":
            raise ConfigurationError(
                "The notebook changed while starter files were prepared. "
                "Run the operation again."
            )
        native_ref = native.get(target)
        if native_ref is not None:
            if native_ref != ref:
                raise ConfigurationError(
                    f"Starter cell target {target!r} conflicts with a named cell. "
                    "Run the operation again."
                )
            continue
        configured_ref = configured.get(target)
        if configured_ref is not None:
            runtime_id = matched.get(target)
            if runtime_id is None or cells_by_runtime_id[runtime_id].ref != ref:
                raise ConfigurationError(
                    f"Starter cell target {target!r} changed while files were "
                    "prepared. "
                    "Run the operation again."
                )
        elif ALIAS_PATTERN.fullmatch(target) is None:
            raise ConfigurationError(f"Invalid generated cell target: {target}")
        bindings[target] = ref
    return bindings
