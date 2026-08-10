"""Data contracts for one notebook and its named views."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

from marimo_studio._cell_refs import cell_ref_candidates
from marimo_studio.errors import (
    ConfigurationError,
    RuntimeSyncError,
    WorkspaceInitializationError,
)
from marimo_studio.types import (
    CellRef,
    CellSpec,
    LiveCellSnapshot,
    NotebookSpec,
    ValueBinding,
)

PYPROJECT_NAME = "pyproject.toml"
MARIMO_DIRECTORY = "__marimo__"
STUDIO_DIRECTORY = "studio"
ALIAS_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*$")
VIEW_PATTERN = re.compile(r"^[a-z][a-z0-9-]*$")
RUNTIME_PATTERN = re.compile(r"^[a-z][a-z0-9-]*$")
RESERVED_VIEW_NAMES = frozenset(
    {
        "_marimo-studio",
        "api",
        "assets",
        "auth",
        "favicon.ico",
        "health",
        "healthz",
        "lsp",
        "mcp",
        "og",
        "public",
        "sse",
        "studio",
        "terminal",
        "ws",
    }
)
RESERVED_VIEW_ASSET_NAMES = frozenset(
    {"_marimo-studio", "@file", "public", "public-files-sw.js"}
)


@dataclass(frozen=True)
class NotebookEnvironment:
    requires_python: str
    dependencies: tuple[str, ...]


@dataclass(frozen=True)
class View:
    name: str
    root: Path

    @property
    def template(self) -> Path:
        return self.root / "index.html"


@dataclass(frozen=True)
class StudioDefinition:
    root: Path
    config_path: Path
    config_source: Literal["notebook", "pyproject"]
    notebook: Path
    view_root: Path
    default_view: str
    default_runtime: str
    runtimes: tuple[str, ...]
    preserve_session: bool
    cells: dict[str, CellRef]
    show_cell_logs: bool

    @property
    def uses_notebook_config(self) -> bool:
        return self.config_source == "notebook"


@dataclass(frozen=True)
class StudioWorkspace(StudioDefinition):
    views: dict[str, View]

    def __post_init__(self) -> None:
        if not self.views:
            raise WorkspaceInitializationError(self.default_view)
        if self.default_view not in self.views:
            raise ConfigurationError(
                f"Default view {self.default_view!r} does not exist in {self.view_root}"
            )

    def view(self, name: str | None = None) -> View:
        selected = name or self.default_view
        try:
            return self.views[selected]
        except KeyError as error:
            available = ", ".join(self.views) or "none"
            raise KeyError(
                f"Unknown view {selected!r}. Available views: {available}."
            ) from error


@dataclass(frozen=True)
class ResolvedView:
    view: View
    cell_aliases: tuple[str, ...]
    value_bindings: dict[str, ValueBinding]
    output_bindings: dict[str, ValueBinding]
    diagnostics: tuple[ProjectionDiagnostic, ...]

    def runtime_value_bindings(
        self,
        live_cells: LiveCellSnapshot | None,
    ) -> dict[str, dict[str, object]]:
        return {
            source: {
                "variable": binding.reference.variable,
                "cell": _runtime_cell_target(
                    binding.cell,
                    live_cells,
                    f"value selector {source!r}",
                ),
            }
            for source, binding in sorted(self.value_bindings.items())
        }

    def runtime_output_bindings(
        self,
        live_cells: LiveCellSnapshot | None,
    ) -> dict[str, dict[str, object]]:
        return {
            source: {
                "variable": binding.reference.variable,
                "cell": _runtime_cell_target(
                    binding.cell,
                    live_cells,
                    f"output selector {source!r}",
                ),
            }
            for source, binding in sorted(self.output_bindings.items())
        }


@dataclass(frozen=True)
class ResolvedStudio:
    workspace: StudioWorkspace
    notebook: NotebookSpec
    aliases: dict[str, CellSpec]
    views: dict[str, ResolvedView]

    def view(self, name: str | None = None) -> ResolvedView:
        return self.views[name or self.workspace.default_view]

    @property
    def diagnostics(self) -> tuple[ProjectionDiagnostic, ...]:
        return tuple(
            diagnostic
            for view in self.views.values()
            for diagnostic in view.diagnostics
        )

    def runtime_cell_bindings(
        self,
        live_cells: LiveCellSnapshot | None,
        *,
        required_aliases: tuple[str, ...] | None = None,
    ) -> dict[str, dict[str, str]]:
        required = (
            frozenset(self.aliases)
            if required_aliases is None
            else frozenset(required_aliases)
        )
        bindings: dict[str, dict[str, str]] = {}
        for alias, cell in sorted(self.aliases.items()):
            target = _runtime_cell_target(
                cell,
                live_cells,
                f"cell alias {alias!r}",
                required=alias in required,
            )
            if target is not None:
                bindings[alias] = target
        return bindings

    def runtime_control_cells(
        self,
        live_cells: LiveCellSnapshot | None,
    ) -> dict[str, str]:
        """Map semantic cell identities to IDs in one runtime."""
        if live_cells is None:
            return {str(cell.ref): cell.runtime_id for cell in self.notebook.cells}
        cells: dict[str, str] = {}
        for cell in self.notebook.cells:
            matches = cell_ref_candidates(cell.ref, live_cells.ids.items())
            if len(matches) == 1:
                cells[str(cell.ref)] = matches[0]
        return cells


def _runtime_cell_target(
    cell: CellSpec,
    live_cells: LiveCellSnapshot | None,
    label: str,
    *,
    required: bool = True,
) -> dict[str, str] | None:
    if cell.name is not None:
        if live_cells is None:
            return {"kind": "name", "value": cell.name}
        matches = cell_ref_candidates(
            cell.ref,
            (
                (identity.ref, identity)
                for identity in live_cells.names.get(cell.name, ())
            ),
        )
        if len(matches) == 1:
            return {"kind": "name", "value": cell.name}
        if not required:
            return None
        raise RuntimeSyncError(
            f"The active Marimo session has not synchronized {label}. "
            "Studio will retry after the notebook updates."
        )
    if live_cells is None:
        return {"kind": "id", "value": cell.runtime_id}
    matches = cell_ref_candidates(cell.ref, live_cells.ids.items())
    if len(matches) != 1:
        if not required:
            return None
        raise RuntimeSyncError(
            f"The active Marimo session has not synchronized {label}. "
            "Studio will retry after the notebook updates."
        )
    return {"kind": "id", "value": matches[0]}


ProjectionKind = Literal["cell", "value", "output"]
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

    def details(self) -> dict[str, object]:
        return {
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

    def to_dict(self) -> dict[str, object]:
        return {
            "code": self.code,
            "severity": self.severity,
            "message": self.message,
            **self.details(),
        }


@dataclass(frozen=True)
class ViewSetupResult:
    workspace: StudioWorkspace | None
    notebook: Path
    config_path: Path
    name: str
    root: Path
    created: tuple[Path, ...]
    updated: tuple[Path, ...]
    dry_run: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": 1,
            "notebook": str(self.notebook),
            "config": str(self.config_path),
            "view": self.name,
            "root": str(self.root),
            "created": [str(path) for path in self.created],
            "updated": [str(path) for path in self.updated],
            "dry_run": self.dry_run,
        }


@dataclass(frozen=True)
class BindingResult:
    alias: str
    cell: CellSpec
    config_path: Path
    previous_ref: CellRef | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": 1,
            "alias": self.alias,
            "cell": {
                "index": self.cell.index,
                "name": self.cell.name,
                "ref": str(self.cell.ref),
                "runtime_id": self.cell.runtime_id,
                "source": asdict(self.cell.source),
            },
            "config": str(self.config_path),
            "previous_ref": (
                str(self.previous_ref) if self.previous_ref is not None else None
            ),
            "changed": self.previous_ref != self.cell.ref,
        }
