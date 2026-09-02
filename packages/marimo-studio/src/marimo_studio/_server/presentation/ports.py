"""Live kernel projection ports and failure contracts."""

from __future__ import annotations

from collections.abc import Awaitable, Mapping
from typing import TYPE_CHECKING, Protocol

from marimo_studio._projections.runtime_records import (
    OutputRenderResult,
    ValueReadResult,
)

if TYPE_CHECKING:
    from marimo_studio._notebook.records import CellRef
    from marimo_studio._projections.resolution import ResolvedProjection
    from marimo_studio._server.records import ServerContext


class ProjectionUnavailable(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        transient: bool,
        status_code: int | None = None,
        terminal: Awaitable[object] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.transient = transient
        self.status_code = status_code or (503 if transient else 500)
        self.terminal = terminal


STALE_PROJECTION_BINDING_CODE = "stale-projection-binding"


class QuerySyncUnavailable(Exception):
    """A live editor session cannot accept query state yet."""

    def __init__(
        self,
        message: str,
        *,
        terminal: Awaitable[object] | None = None,
    ) -> None:
        super().__init__(message)
        self.terminal = terminal


class KernelProjectionHost(Protocol):
    async def read_values(
        self,
        context: ServerContext,
        session_id: str,
        revision: str,
        projections: tuple[ResolvedProjection, ...],
        active_projections: tuple[ResolvedProjection, ...],
        *,
        consumer_id: str,
        runtime_cell_refs: Mapping[CellRef, str],
    ) -> ValueReadResult: ...

    async def render_outputs(
        self,
        context: ServerContext,
        session_id: str,
        revision: str,
        projections: tuple[ResolvedProjection, ...],
        active_projections: tuple[ResolvedProjection, ...],
        *,
        consumer_id: str,
        runtime_cell_refs: Mapping[CellRef, str],
    ) -> OutputRenderResult: ...

    async def sync_query(
        self,
        context: ServerContext,
        session_id: str,
        query: dict[str, str | list[str]],
        operation_id: str,
        *,
        binding_generation: int,
        query_generation: int,
        deadline: float,
    ) -> None: ...


SelectorSpec = tuple[str, tuple[tuple[str, str | int], ...]]
