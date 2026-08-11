"""Keep configured cell aliases aligned with live notebook source."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from marimo_studio._capabilities import (
    SaveCell,
    SourceTransformResult,
    SourceTransformSession,
)
from marimo_studio._cell_refs import (
    cell_refs,
    safe_cell_ref_matches,
    safe_cell_ref_updates,
)
from marimo_studio._workspace import discover_studio
from marimo_studio._workspace.bindings import _write_cell_bindings
from marimo_studio._workspace.metadata import (
    set_cell_bindings,
    updated_notebook_config_source,
)
from marimo_studio._workspace.models import StudioWorkspace
from marimo_studio.errors import MarimoStudioError
from marimo_studio.types import CellRef


@dataclass(frozen=True)
class _TrackedAlias:
    ref: CellRef
    runtime_id: str


def _live_refs(cells: tuple[SaveCell, ...]) -> tuple[tuple[CellRef, str], ...]:
    refs = cell_refs(cell.code for cell in cells)
    return tuple(
        (cell_ref, cell.runtime_id) for cell_ref, cell in zip(refs, cells, strict=True)
    )


class _CellAliasTransform(SourceTransformSession):
    def __init__(self, path: Path, cells: tuple[SaveCell, ...]) -> None:
        self._path = path
        self._aliases: dict[str, _TrackedAlias] = {}
        self._saved_live = _live_refs(cells)
        workspace = self._workspace()
        if workspace is not None:
            self._refresh_aliases(workspace, self._saved_live)

    def transform(
        self,
        path: Path,
        source: str,
        *,
        persist: bool,
        cells: tuple[SaveCell, ...],
    ) -> SourceTransformResult:
        self._path = path
        workspace, bindings, removed, changed, live = self._binding_update(cells)
        updated = source
        if changed and workspace is not None and workspace.uses_notebook_config:
            updated = updated_notebook_config_source(
                workspace.notebook,
                source,
                lambda config: set_cell_bindings(
                    config,
                    bindings,
                    remove=removed,
                ),
            )
        if not persist:
            return SourceTransformResult(updated)

        def commit() -> None:
            if changed and workspace is not None and not workspace.uses_notebook_config:
                _write_cell_bindings(workspace, bindings, remove=removed)
            if changed:
                for alias in removed:
                    self._aliases.pop(alias, None)
                self._aliases.update(
                    {
                        alias: _TrackedAlias(ref, self._aliases[alias].runtime_id)
                        for alias, ref in bindings.items()
                    }
                )
            self._saved_live = live

        return SourceTransformResult(updated, commit)

    def close(self) -> None:
        self._aliases.clear()
        self._saved_live = ()

    def _workspace(self) -> StudioWorkspace | None:
        try:
            return discover_studio(self._path)
        except MarimoStudioError:
            return None

    def _refresh_aliases(
        self,
        workspace: StudioWorkspace,
        live: tuple[tuple[CellRef, str], ...],
    ) -> None:
        resolved: dict[str, _TrackedAlias] = {}
        pending: dict[str, CellRef] = {}
        for alias, cell_ref in workspace.cells.items():
            tracked = self._aliases.get(alias)
            if tracked is not None and tracked.ref == cell_ref:
                resolved[alias] = tracked
            else:
                pending[alias] = cell_ref

        matched = safe_cell_ref_matches(pending, live)
        owners_by_id: dict[str, list[str]] = {}
        for alias, tracked in resolved.items():
            owners_by_id.setdefault(tracked.runtime_id, []).append(alias)
        for alias, runtime_id in matched.items():
            owners = owners_by_id.get(runtime_id, [])
            if any(workspace.cells[owner] != pending[alias] for owner in owners):
                continue
            resolved[alias] = _TrackedAlias(pending[alias], runtime_id)
            owners_by_id.setdefault(runtime_id, []).append(alias)
        self._aliases = resolved

    def _binding_update(
        self,
        cells: tuple[SaveCell, ...],
    ) -> tuple[
        StudioWorkspace | None,
        dict[str, CellRef],
        tuple[str, ...],
        bool,
        tuple[tuple[CellRef, str], ...],
    ]:
        workspace = self._workspace()
        if workspace is None:
            self._aliases.clear()
            return None, {}, (), False, ()
        live = _live_refs(cells)
        self._refresh_aliases(workspace, self._saved_live or live)
        refs_by_id = {runtime_id: cell_ref for cell_ref, runtime_id in live}
        removed = tuple(
            alias
            for alias, tracked in self._aliases.items()
            if alias in workspace.cells and tracked.runtime_id not in refs_by_id
        )
        bindings = {
            alias: current
            for alias, tracked in self._aliases.items()
            if workspace.cells.get(alias) == tracked.ref
            and (current := refs_by_id.get(tracked.runtime_id)) is not None
        }
        remaining = {
            alias: cell_ref
            for alias, cell_ref in workspace.cells.items()
            if alias not in removed
        }
        bindings = safe_cell_ref_updates(remaining, bindings)
        changed = bool(removed) or any(
            workspace.cells[alias] != cell_ref for alias, cell_ref in bindings.items()
        )
        return workspace, bindings, removed, changed, live


class CellAliasSourcePolicy:
    """Create alias transforms for configured Studio notebooks."""

    def open(
        self,
        path: Path,
        cells: tuple[SaveCell, ...],
    ) -> SourceTransformSession | None:
        try:
            workspace = discover_studio(path)
        except MarimoStudioError:
            return None
        return _CellAliasTransform(path, cells) if workspace is not None else None


__all__ = ["CellAliasSourcePolicy"]
