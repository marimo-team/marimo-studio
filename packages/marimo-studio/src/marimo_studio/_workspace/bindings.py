"""Persist stable aliases for saved notebook cells."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, MutableMapping
from typing import Any

import tomlkit

from marimo_studio._filesystem._secure_types import ConditionalWriteError
from marimo_studio._filesystem.io import read_text
from marimo_studio._notebook.ports import NotebookInspector
from marimo_studio._notebook.records import CellRef, CellSelector, resolve_cell
from marimo_studio._notebook.source_snapshot import inspect_notebook_source
from marimo_studio._workspace.config import editable_studio_config, load_studio
from marimo_studio._workspace.config_snapshot import (
    WorkspaceConfigSnapshot,
    snapshot_workspace_config,
)
from marimo_studio._workspace.metadata import (
    set_cell_bindings,
    updated_notebook_config_source,
)
from marimo_studio._workspace.models import (
    ALIAS_PATTERN,
    BindingResult,
    StudioDefinition,
    StudioWorkspace,
)
from marimo_studio._workspace.mutation_lock import workspace_catalog_lock
from marimo_studio._workspace.transactions import write_file_transaction
from marimo_studio.errors import (
    BindingError,
    ConfigurationError,
    WorkspaceMutationError,
)


def _commit_cell_bindings(
    snapshot: WorkspaceConfigSnapshot[StudioWorkspace],
    bindings: Mapping[str, CellRef],
    *,
    remove: Iterable[str] = (),
) -> None:
    source = cell_bindings_source(
        snapshot.studio,
        bindings,
        remove=remove,
        source=snapshot.source,
    )
    path = snapshot.studio.config_path
    writes = {path: source} if source != snapshot.source else {}
    try:
        with write_file_transaction(
            snapshot.studio.root,
            writes,
            expected=snapshot.expected_identities,
        ):
            pass
    except ConditionalWriteError as error:
        raise WorkspaceMutationError(
            "Cell binding",
            recovery=error.recovery,
            write_committed=error.committed is not None,
        ) from error


def bind_cell(
    studio: StudioWorkspace,
    alias: str,
    cell_selector: CellSelector,
    *,
    inspect_notebook: NotebookInspector,
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
        _commit_cell_bindings(snapshot, {alias: cell.ref})
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
    studio: StudioWorkspace,
    bindings: Mapping[str, CellRef],
    *,
    remove: Iterable[str] = (),
) -> None:
    """Persist cell bindings through the workspace configuration owner."""
    removed = tuple(remove)
    with workspace_catalog_lock(studio.view_root):
        snapshot = snapshot_workspace_config(
            studio,
            reload_studio=load_studio,
            include_notebook=True,
            require_catalog_generation=True,
        )
        desired: dict[str, CellRef | None] = {alias: None for alias in removed}
        desired.update(bindings)
        if any(
            snapshot.studio.cells.get(alias) not in {studio.cells.get(alias), value}
            for alias, value in desired.items()
        ):
            raise ConfigurationError(
                "Cell bindings changed before the update committed. "
                "Run the operation again."
            )
        _commit_cell_bindings(snapshot, bindings, remove=removed)


def cell_bindings_source(
    studio: StudioDefinition,
    bindings: Mapping[str, CellRef],
    *,
    remove: Iterable[str] = (),
    source: str | None = None,
) -> str:
    """Return the configured source after applying cell bindings."""
    removed = tuple(remove)

    def update(config: MutableMapping[str, Any]) -> None:
        set_cell_bindings(config, bindings, remove=removed)

    if studio.uses_notebook_config:
        current = read_text(studio.notebook) if source is None else source
        return updated_notebook_config_source(studio.notebook, current, update)
    current = (
        read_text(studio.config_path, root=studio.root) if source is None else source
    )
    document = tomlkit.parse(current)
    update(editable_studio_config(document))
    return tomlkit.dumps(document)
