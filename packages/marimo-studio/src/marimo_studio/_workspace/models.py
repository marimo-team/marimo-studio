"""Data contracts for one notebook and its named views."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

from marimo_studio._notebook.records import (
    CellRef,
    CellSpec,
)
from marimo_studio.errors import ConfigurationError, ViewNotFoundError
from marimo_studio.errors._internal import WorkspaceInitializationError
from marimo_studio.view_providers import ViewProject

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
    views: dict[str, ViewProject]

    def __post_init__(self) -> None:
        if not self.views:
            raise WorkspaceInitializationError(self.default_view)
        if self.default_view not in self.views:
            raise ConfigurationError(
                f"Default view {self.default_view!r} does not exist in {self.view_root}"
            )

    def view(self, name: str | None = None) -> ViewProject:
        selected = name or self.default_view
        try:
            return self.views[selected]
        except KeyError as error:
            raise ViewNotFoundError(
                selected,
                available=tuple(self.views),
            ) from error


@dataclass(frozen=True)
class BindingResult:
    alias: str
    cell: CellSpec
    config_path: Path
    dry_run: bool
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
            "dry_run": self.dry_run,
            "previous_ref": (
                str(self.previous_ref) if self.previous_ref is not None else None
            ),
            "changed": self.previous_ref != self.cell.ref,
        }
