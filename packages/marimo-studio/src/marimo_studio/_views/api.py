"""Compose notebook inspection with Studio workspace operations."""

from __future__ import annotations

from pathlib import Path

from marimo_studio._composition import create_notebook_write_lock
from marimo_studio._notebook.inspection import inspect_notebook
from marimo_studio._notebook.records import CellSelector
from marimo_studio._views.create import prepare_view as _prepare_view
from marimo_studio._views.records import Starter, ViewSetupResult
from marimo_studio._views.resolve import resolve_studio as resolve_studio
from marimo_studio._workspace.bindings import (
    bind_cell as _bind_cell,
)
from marimo_studio._workspace.models import (
    BindingResult,
    StudioWorkspace,
)


def bind_cell(
    studio: StudioWorkspace,
    alias: str,
    cell_selector: CellSelector,
    *,
    dry_run: bool = False,
    overwrite: bool = False,
) -> BindingResult:
    """Bind a stable alias to a notebook cell."""
    return _bind_cell(
        studio,
        alias,
        cell_selector,
        inspect_notebook=inspect_notebook,
        lock_notebook=create_notebook_write_lock(),
        dry_run=dry_run,
        overwrite=overwrite,
    )


def prepare_view(
    notebook: str | Path,
    name: str | None = None,
    *,
    starter: str | Starter | None = None,
    dry_run: bool = False,
    expected_catalog_generation: str | None = None,
) -> ViewSetupResult:
    """Configure a notebook and create a named view."""
    return _prepare_view(
        notebook,
        name,
        starter=starter,
        inspect_notebook=inspect_notebook,
        dry_run=dry_run,
        expected_catalog_generation=expected_catalog_generation,
    )


def create_view(
    notebook: str | Path,
    name: str | None = None,
    *,
    starter: str | Starter | None = None,
    dry_run: bool = False,
    expected_catalog_generation: str | None = None,
) -> ViewSetupResult:
    """Create one new view and reject an existing name."""
    return _prepare_view(
        notebook,
        name,
        starter=starter,
        inspect_notebook=inspect_notebook,
        dry_run=dry_run,
        fail_if_exists=True,
        expected_catalog_generation=expected_catalog_generation,
    )
