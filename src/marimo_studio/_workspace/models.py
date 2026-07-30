"""Data contracts for one notebook and its named views."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

from marimo_studio.types import CellRef, CellSpec, NotebookSpec, ValueBinding

PYPROJECT_NAME = "pyproject.toml"
MARIMO_DIRECTORY = "__marimo__"
STUDIO_DIRECTORY = "studio"
ALIAS_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*$")
VIEW_PATTERN = re.compile(r"^[a-z][a-z0-9-]*$")
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
class StudioConfig:
    root: Path
    config_path: Path
    config_source: Literal["notebook", "pyproject"]
    notebook: Path
    view_root: Path
    default_view: str
    preserve_session: bool
    views: dict[str, View]
    cells: dict[str, CellRef]

    @property
    def uses_notebook_config(self) -> bool:
        return self.config_source == "notebook"

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

    def runtime_value_bindings(self) -> dict[str, dict[str, object]]:
        return {
            source: binding.to_runtime_dict()
            for source, binding in sorted(self.value_bindings.items())
        }


@dataclass(frozen=True)
class ResolvedStudio:
    studio: StudioConfig
    notebook: NotebookSpec
    aliases: dict[str, CellSpec]
    views: dict[str, ResolvedView]

    def view(self, name: str | None = None) -> ResolvedView:
        return self.views[name or self.studio.default_view]

    def runtime_cells(self) -> dict[str, str]:
        return {alias: cell.runtime_id for alias, cell in sorted(self.aliases.items())}


@dataclass(frozen=True)
class ViewSetupResult:
    studio: StudioConfig | None
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
