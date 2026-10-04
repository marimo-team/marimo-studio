"""Persist stable aliases for saved notebook cells."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, MutableMapping
from contextlib import AbstractContextManager, nullcontext
from typing import Any, TypeVar

from marimo_studio._notebook.ports import NotebookInspector, NotebookWriteLock
from marimo_studio._notebook.records import CellRef, CellSelector, resolve_cell
from marimo_studio._notebook.source_snapshot import inspect_notebook_source
from marimo_studio._workspace.config import (
    load_studio,
    load_studio_definition,
    updated_studio_config_source,
)
from marimo_studio._workspace.config_snapshot import (
    WorkspaceConfigSnapshot,
    snapshot_workspace_config,
)
from marimo_studio._workspace.metadata import (
    set_cell_bindings,
)
from marimo_studio._workspace.models import (
    ALIAS_PATTERN,
    BindingResult,
    StudioDefinition,
    StudioWorkspace,
)
from marimo_studio._workspace.mutation_lock import workspace_catalog_lock
from marimo_studio._workspace.transactions import workspace_transaction
from marimo_studio.errors import (
    BindingError,
    ConfigurationError,
    WorkspaceGenerationConflictError,
)

_TStudio = TypeVar("_TStudio", bound=StudioDefinition)


def _commit_cell_bindings(
    snapshot: WorkspaceConfigSnapshot[_TStudio],
    bindings: Mapping[str, CellRef],
    *,
    remove: Iterable[str] = (),
    lock_notebook: NotebookWriteLock | None,
) -> None:
    source = cell_bindings_source(
        snapshot.studio,
        bindings,
        remove=remove,
        source=snapshot.source,
    )
    path = snapshot.studio.config_path
    writes = {path: source} if source != snapshot.source else {}
    notebook_lock: AbstractContextManager[None] = nullcontext()
    if snapshot.studio.notebook in writes:
        if lock_notebook is None:
            raise RuntimeError("Notebook bindings need Marimo's notebook lock")
        notebook_lock = lock_notebook(snapshot.studio.notebook)
    with (
        notebook_lock,
        workspace_transaction(
            "Cell binding",
            snapshot.studio.root,
            writes,
            expected=snapshot.expected_identities,
        ),
    ):
        pass


def bind_cell(
    studio: StudioWorkspace,
    alias: str,
    cell_selector: CellSelector,
    *,
    inspect_notebook: NotebookInspector,
    lock_notebook: NotebookWriteLock,
    dry_run: bool = False,
    overwrite: bool = False,
) -> BindingResult:
    """Bind a stable alias to a notebook cell."""
    if not ALIAS_PATTERN.fullmatch(alias):
        raise ConfigurationError(f"Invalid cell alias: {alias}")
    with workspace_catalog_lock(studio.view_root):
        snapshot = snapshot_workspace_config(
            studio,
            reload_studio=load_studio,
            include_notebook=True,
            require_catalog_generation=True,
        )
        current = snapshot.studio
        assert snapshot.notebook_source is not None
        notebook = inspect_notebook_source(
            current.notebook,
            snapshot.notebook_source,
            inspect_notebook,
        )
        cell = resolve_cell(
            notebook,
            cell_selector,
            error_code="invalid-binding-request",
            field="cell",
        )
        native = notebook.named_cells().get(alias)
        if native is not None and native.ref != cell.ref:
            raise BindingError(
                f"Alias {alias!r} conflicts with the named notebook cell"
            )
        previous_ref = current.cells.get(alias)
        if previous_ref is not None and previous_ref != cell.ref and not overwrite:
            raise BindingError(
                f"Alias {alias!r} already points to {previous_ref}. "
                "Set overwrite to replace it."
            )
        result = BindingResult(
            alias=alias,
            cell=cell,
            config_path=current.config_path,
            catalog_generation=current.catalog_generation,
            dry_run=dry_run,
            previous_ref=previous_ref,
        )
        if dry_run:
            return result
        _commit_cell_bindings(snapshot, {alias: cell.ref}, lock_notebook=lock_notebook)
        updated = load_studio(current.config_path)
        return BindingResult(
            alias=result.alias,
            cell=result.cell,
            config_path=result.config_path,
            catalog_generation=updated.catalog_generation,
            dry_run=result.dry_run,
            previous_ref=result.previous_ref,
        )


def _write_cell_bindings(
    studio: StudioDefinition,
    bindings: Mapping[str, CellRef],
    *,
    remove: Iterable[str] = (),
    notebook_source: str,
    lock_notebook: NotebookWriteLock,
) -> None:
    """Persist live cell bindings into a project configuration file.

    A Marimo save calls this after it releases the notebook lock, with the
    source it saved. The bindings commit only while the notebook still holds
    that source, because a later save binds its own cells, and only while the
    configuration still matches ``studio``.
    """
    with workspace_catalog_lock(studio.view_root), lock_notebook(studio.notebook):
        snapshot = snapshot_workspace_config(
            studio,
            reload_studio=load_studio_definition,
            include_notebook=True,
        )
        # Marimo writes text with the platform's line endings.
        saved = snapshot.notebook_source
        if saved is None or saved.splitlines() != notebook_source.splitlines():
            return
        if snapshot.studio.config_generation != studio.config_generation:
            raise WorkspaceGenerationConflictError()
        _commit_cell_bindings(snapshot, bindings, remove=remove, lock_notebook=None)


def cell_bindings_source(
    studio: StudioDefinition,
    bindings: Mapping[str, CellRef],
    *,
    source: str,
    remove: Iterable[str] = (),
) -> str:
    """Return the configured source after applying cell bindings."""
    removed = tuple(remove)

    def update(config: MutableMapping[str, Any]) -> None:
        set_cell_bindings(config, bindings, remove=removed)

    return updated_studio_config_source(studio, source, update)
