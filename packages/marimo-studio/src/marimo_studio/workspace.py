"""Compose notebook inspection with Studio workspace operations."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from marimo_studio._workspace.bindings import (
    bind_cell as _bind_cell,
)
from marimo_studio._workspace.bindings import (
    resolve_studio as _resolve_studio,
)
from marimo_studio._workspace.models import (
    BindingResult,
    ResolvedStudio,
    StudioWorkspace,
    ViewSetupResult,
)
from marimo_studio._workspace.setup import ensure_view as _ensure_view
from marimo_studio.inspect import inspect_notebook


def resolve_studio(
    studio: StudioWorkspace,
    *,
    include_code: bool = False,
    view_name: str | None = None,
    view_documents: Mapping[str, str] | None = None,
) -> ResolvedStudio:
    """Resolve configured views against the current notebook graph."""
    return _resolve_studio(
        studio,
        inspect_notebook=inspect_notebook,
        include_code=include_code,
        view_name=view_name,
        view_documents=view_documents,
    )


def bind_cell(
    studio: StudioWorkspace,
    alias: str,
    cell_index: int,
    *,
    dry_run: bool = False,
    overwrite: bool = False,
) -> BindingResult:
    """Bind a stable alias to a notebook cell."""
    return _bind_cell(
        studio,
        alias,
        cell_index,
        inspect_notebook=inspect_notebook,
        dry_run=dry_run,
        overwrite=overwrite,
    )


def ensure_view(
    notebook: str | Path,
    name: str | None = None,
    *,
    dry_run: bool = False,
) -> ViewSetupResult:
    """Configure a notebook when needed and create a named view."""
    return _ensure_view(
        notebook,
        name,
        inspect_notebook=inspect_notebook,
        dry_run=dry_run,
    )


__all__ = ["bind_cell", "ensure_view", "resolve_studio"]
