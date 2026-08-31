"""Notebook inspection, execution, and environment ports."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from marimo_studio._notebook.records import CellKind, NotebookSpec, SourceSpan
from marimo_studio._projections.runtime_records import RuntimeProbe


class LiveNotebookRunner(Protocol):
    async def __call__(
        self,
        path: Path,
        *,
        cell_ids: tuple[str, ...],
        variables: tuple[str, ...],
        output_selector_groups: tuple[tuple[str, ...], ...],
        show_tracebacks: bool,
        timeout: float,
        value_max_bytes: int | None = None,
    ) -> RuntimeProbe: ...


class NotebookInspector(Protocol):
    """Read the static graph for one saved Marimo notebook."""

    def __call__(
        self,
        path: str | Path,
        *,
        include_code: bool = False,
    ) -> NotebookSpec: ...


@dataclass(frozen=True)
class StaticCell:
    runtime_id: str
    code: str
    name: str
    kind: CellKind
    markdown: str | None
    has_output_expression: bool
    displays_output: bool
    definitions: tuple[str, ...]
    references: tuple[str, ...]
    parents: tuple[str, ...]
    children: tuple[str, ...]
    column: int | None
    disabled: bool
    hide_code: bool
    source: SourceSpan


@dataclass(frozen=True)
class StaticNotebook:
    cells: tuple[StaticCell, ...]
    app_config: dict[str, object]
    source_revision: str


class StaticNotebookLoader(Protocol):
    def __call__(self, path: Path) -> StaticNotebook: ...


class EnvironmentFlagBuilder(Protocol):
    def __call__(
        self,
        notebook: Path,
        package_requirement: str | None,
        *,
        compose_project: bool,
    ) -> list[str]: ...
