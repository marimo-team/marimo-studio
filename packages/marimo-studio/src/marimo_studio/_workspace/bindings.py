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
from marimo_studio._notebook.records import CellRef
from marimo_studio._workspace.config import editable_studio_config
from marimo_studio._workspace.metadata import (
    set_cell_bindings,
    update_notebook_config,
)
from marimo_studio._workspace.models import (
    ALIAS_PATTERN,
    BindingResult,
    StudioWorkspace,
)
from marimo_studio.errors import BindingError, CapabilityInputError, ConfigurationError


def bind_cell(
    studio: StudioWorkspace,
    alias: str,
    cell_index: int,
    *,
    inspect_notebook: NotebookInspector,
    dry_run: bool = False,
    overwrite: bool = False,
) -> BindingResult:
    """Bind a stable alias to a notebook cell."""
    if (
        not isinstance(cell_index, int)
        or isinstance(cell_index, bool)
        or cell_index < 0
    ):
        raise CapabilityInputError(
            "invalid-binding-request",
            "cell_index",
            "cell_index must be a nonnegative integer",
        )
    if not ALIAS_PATTERN.fullmatch(alias):
        raise ConfigurationError(f"Invalid cell alias: {alias}")
    notebook = inspect_notebook(studio.notebook)
    try:
        cell = notebook.cells[cell_index]
    except IndexError as error:
        raise BindingError(
            f"Cell index {cell_index} is outside 0-{len(notebook.cells) - 1}"
        ) from error
    native = notebook.named_cells().get(alias)
    if native is not None and native.ref != cell.ref:
        raise BindingError(f"Alias {alias!r} conflicts with the named notebook cell")
    previous_ref = studio.cells.get(alias)
    if previous_ref is not None and previous_ref != cell.ref and not overwrite:
        raise BindingError(
            f"Alias {alias!r} already points to {previous_ref}. "
            "Pass --overwrite to replace it."
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
    removed = tuple(remove)
    if studio.uses_notebook_config:
        reject_mutable_symlinks(studio.notebook.parent, {studio.notebook})

        def update(config: MutableMapping[str, Any]) -> None:
            set_cell_bindings(config, bindings, remove=removed)

        update_notebook_config(studio.notebook, update)
    else:
        reject_mutable_symlinks(studio.root, {studio.config_path})
        document = tomlkit.parse(read_text(studio.config_path, root=studio.root))
        config = editable_studio_config(document)
        set_cell_bindings(config, bindings, remove=removed)
        atomic_write_text(
            studio.config_path,
            tomlkit.dumps(document),
            root=studio.root,
        )
