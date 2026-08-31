"""Persist stable aliases for saved notebook cells."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, MutableMapping
from typing import Any

import tomlkit

from marimo_studio._filesystem.io import (
    atomic_write_text,
    read_text,
    reject_mutable_symlinks,
)
from marimo_studio._notebook.ports import NotebookInspector
from marimo_studio._notebook.records import CellRef, CellSelector, resolve_cell
from marimo_studio._workspace.config import editable_studio_config
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
from marimo_studio.errors import BindingError, ConfigurationError


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
    notebook = inspect_notebook(studio.notebook)
    cell = resolve_cell(
        notebook,
        cell_selector,
        error_code="invalid-binding-request",
        field="cell",
    )
    native = notebook.named_cells().get(alias)
    if native is not None and native.ref != cell.ref:
        raise BindingError(f"Alias {alias!r} conflicts with the named notebook cell")
    previous_ref = studio.cells.get(alias)
    if previous_ref is not None and previous_ref != cell.ref and not overwrite:
        raise BindingError(
            f"Alias {alias!r} already points to {previous_ref}. "
            "Set overwrite to replace it."
        )
    result = BindingResult(
        alias=alias,
        cell=cell,
        config_path=studio.config_path,
        dry_run=dry_run,
        previous_ref=previous_ref,
    )
    if dry_run:
        return result
    _write_cell_bindings(studio, {alias: cell.ref})
    return result


def _write_cell_bindings(
    studio: StudioWorkspace,
    bindings: Mapping[str, CellRef],
    *,
    remove: Iterable[str] = (),
) -> None:
    """Persist cell bindings through the workspace configuration owner."""
    source = cell_bindings_source(studio, bindings, remove=remove)
    if studio.uses_notebook_config:
        reject_mutable_symlinks(studio.notebook.parent, {studio.notebook})
        atomic_write_text(studio.notebook, source, root=studio.notebook.parent)
    else:
        reject_mutable_symlinks(studio.root, {studio.config_path})
        atomic_write_text(
            studio.config_path,
            source,
            root=studio.root,
        )


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
