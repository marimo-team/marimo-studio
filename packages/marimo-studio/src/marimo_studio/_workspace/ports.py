"""Ports used by workspace rules that need notebook runtime data."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from marimo_studio.types import NotebookSpec, RuntimeProbe


class NotebookInspector(Protocol):
    """Read the static graph for one Marimo notebook."""

    def __call__(
        self,
        path: str | Path,
        *,
        include_code: bool = False,
    ) -> NotebookSpec: ...


class RuntimeProber(Protocol):
    """Execute selected notebook projections and return their runtime state."""

    async def __call__(
        self,
        path: Path,
        *,
        cell_ids: tuple[str, ...],
        variables: tuple[str, ...],
        show_tracebacks: bool,
    ) -> RuntimeProbe: ...


__all__ = ["NotebookInspector", "RuntimeProber"]
