"""Compose notebook inspection with Studio workspace operations."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from marimo_studio._notebook.inspection import inspect_notebook
from marimo_studio._notebook.records import CellSelector
from marimo_studio._views.create import prepare_view as _prepare_view
from marimo_studio._views.default_view import set_default_view as _set_default_view
from marimo_studio._views.records import Starter, ViewSetupResult
from marimo_studio._views.remove import delete_view as _delete_view
from marimo_studio._views.rename import rename_view as _rename_view
from marimo_studio._views.resolve import resolve_studio as resolve_studio
from marimo_studio._workspace.bindings import (
    bind_cell as _bind_cell,
)
from marimo_studio._workspace.models import (
    BindingResult,
    StudioWorkspace,
)


@dataclass(frozen=True)
class ViewCatalog:
    """The named views of a notebook after a catalog change."""

    notebook: Path
    default_view: str
    views: Mapping[str, str]
    catalog_generation: str

    @classmethod
    def of(cls, studio: StudioWorkspace) -> ViewCatalog:
        """Capture the committed catalog of one loaded workspace."""
        return cls(
            notebook=studio.notebook,
            default_view=studio.default_view,
            views=dict(studio.view_generations),
            catalog_generation=studio.catalog_generation,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": 1,
            "notebook": str(self.notebook),
            "default_view": self.default_view,
            "views": [
                {"name": name, "generation": generation}
                for name, generation in self.views.items()
            ],
            "catalog_generation": self.catalog_generation,
        }


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


def remove_view(
    studio: StudioWorkspace,
    name: str,
    *,
    expected_catalog_generation: str | None = None,
    expected_generation: str | None = None,
) -> ViewCatalog:
    """Remove one named view and return the remaining catalog."""
    return ViewCatalog.of(
        _delete_view(
            studio,
            name,
            expected_catalog_generation=expected_catalog_generation,
            expected_generation=expected_generation,
        )
    )


def make_default_view(
    studio: StudioWorkspace,
    name: str,
    *,
    expected_catalog_generation: str | None = None,
    expected_generation: str | None = None,
) -> ViewCatalog:
    """Serve one named view at the main route and return the catalog."""
    return ViewCatalog.of(
        _set_default_view(
            studio,
            name,
            expected_catalog_generation=expected_catalog_generation,
            expected_generation=expected_generation,
        )
    )


def rename_view(
    studio: StudioWorkspace,
    name: str,
    new_name: str,
    *,
    expected_catalog_generation: str | None = None,
    expected_generation: str | None = None,
) -> ViewCatalog:
    """Rename one view and return the catalog."""
    return ViewCatalog.of(
        _rename_view(
            studio,
            name,
            new_name,
            expected_catalog_generation=expected_catalog_generation,
            expected_generation=expected_generation,
        )
    )
