"""Compose notebook inspection with Studio workspace operations."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
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
from marimo_studio._workspace.views import delete_view as _delete_view
from marimo_studio.inspect import inspect_notebook


@dataclass(frozen=True)
class ViewRemovalResult:
    """Describe a removed view and the remaining workspace."""

    notebook: Path
    view: str
    default_view: str
    views: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": 1,
            "notebook": str(self.notebook),
            "view": self.view,
            "default_view": self.default_view,
            "views": list(self.views),
        }


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


def remove_view(studio: StudioWorkspace, name: str) -> ViewRemovalResult:
    """Remove one named view and return the remaining workspace identity."""
    updated = _delete_view(studio, name)
    return ViewRemovalResult(
        notebook=updated.notebook,
        view=name,
        default_view=updated.default_view,
        views=tuple(updated.views),
    )


__all__ = [
    "BindingResult",
    "ViewRemovalResult",
    "ViewSetupResult",
    "bind_cell",
    "ensure_view",
    "remove_view",
    "resolve_studio",
]
