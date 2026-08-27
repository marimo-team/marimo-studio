"""Resolved projection state and diagnostics."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from marimo_studio._notebook.cell_refs import safe_cell_ref_matches
from marimo_studio._notebook.records import CellSpec, LiveCellSnapshot, NotebookSpec
from marimo_studio._projections.resolution import ResolvedProjection
from marimo_studio._projections.symbol_graph import NotebookSymbolGraph
from marimo_studio._workspace.models import StudioWorkspace
from marimo_studio.errors import ViewNotFoundError
from marimo_studio.view_providers import (
    MountDeclaration,
    ProjectionKind,
    ViewProject,
)

ProjectionSeverity = Literal["warning", "error"]


@dataclass(frozen=True)
class ProjectionDiagnostic:
    """Describe one view projection that needs author attention."""

    code: str
    severity: ProjectionSeverity
    message: str
    hint: str
    view: str
    projection: ProjectionKind
    target: str
    source: Path
    line: int
    column: int
    site_id: str | None = None

    def details(self) -> dict[str, object]:
        details: dict[str, object] = {
            "view": self.view,
            "projection": self.projection,
            "target": self.target,
            "source": {
                "path": str(self.source),
                "line": self.line,
                "column": self.column,
            },
            "hint": self.hint,
        }
        if self.site_id is not None:
            details["siteId"] = self.site_id
        return details

    def to_dict(self) -> dict[str, object]:
        return {
            "code": self.code,
            "severity": self.severity,
            "message": self.message,
            **self.details(),
        }


@dataclass(frozen=True)
class ResolvedView:
    view: ViewProject
    mounts: tuple[MountDeclaration, ...]
    projections: tuple[ResolvedProjection, ...]
    diagnostics: tuple[ProjectionDiagnostic, ...]


@dataclass(frozen=True)
class ResolvedStudio:
    workspace: StudioWorkspace
    notebook: NotebookSpec
    symbols: NotebookSymbolGraph
    aliases: dict[str, CellSpec]
    views: dict[str, ResolvedView]

    def view(self, name: str | None = None) -> ResolvedView:
        selected = name or self.workspace.default_view
        try:
            return self.views[selected]
        except KeyError as error:
            raise ViewNotFoundError(
                selected,
                available=tuple(self.views),
            ) from error

    @property
    def diagnostics(self) -> tuple[ProjectionDiagnostic, ...]:
        return tuple(
            diagnostic
            for view in self.views.values()
            for diagnostic in view.diagnostics
        )

    def runtime_cell_refs(
        self,
        live_cells: LiveCellSnapshot | None,
    ) -> dict[str, str]:
        """Map semantic cell identities to IDs in one runtime."""
        if live_cells is None:
            return {str(cell.ref): cell.runtime_id for cell in self.notebook.cells}
        bindings = {str(cell.ref): cell.ref for cell in self.notebook.cells}
        return safe_cell_ref_matches(bindings, live_cells.ids.items())
