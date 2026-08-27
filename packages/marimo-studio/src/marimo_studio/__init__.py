"""Public Studio application, inspection, and integration contracts."""

from __future__ import annotations

from pathlib import Path

from marimo_studio._delivery.records import ASGIApp
from marimo_studio._notebook.records import (
    CellConfigSpec,
    CellRef,
    CellSpec,
    NotebookSpec,
    SourceSpan,
)

LENS_TARGET_SELECTOR = (
    ":is(marimo-cell, marimo-output, [mo-value])[data-runtime-cell-id]"
)


def create_asgi_app(notebook: str | Path) -> ASGIApp:
    """Build a run-mode Marimo app for one configured notebook."""
    from marimo_studio._delivery.app import create_asgi_app as create

    return create(notebook)


def inspect_notebook(
    path: str | Path,
    *,
    include_code: bool = False,
) -> NotebookSpec:
    """Return the static cell inventory for a Marimo notebook."""
    from marimo_studio._notebook.inspection import inspect_notebook as inspect

    return inspect(path, include_code=include_code)


__all__ = [
    "LENS_TARGET_SELECTOR",
    "ASGIApp",
    "CellConfigSpec",
    "CellRef",
    "CellSpec",
    "NotebookSpec",
    "SourceSpan",
    "create_asgi_app",
    "inspect_notebook",
]
