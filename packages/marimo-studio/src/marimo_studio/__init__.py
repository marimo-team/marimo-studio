"""Expose Studio's public Python API for notebooks and applications.

``inspect_notebook`` describes saved cells, names, dependencies, and source
locations without running the notebook. ``create_asgi_app`` builds a Marimo
ASGI application for a configured notebook, its named Studio views, and the
browser runtime that presents them.

The notebook remains the source of data, computation, controls, and reactive
behavior. Studio adds frontend view projects and browser delivery around that
model. ``STUDIO_RESULT_SELECTOR`` lets browser tools locate mounted cells,
outputs, and values inside a rendered view. ``marimo_studio.authoring`` opens a
saved notebook. ``marimo_studio.agent.current_workspace()`` adds operations
that use the current code-mode notebook and Studio tab.
"""

from __future__ import annotations

from pathlib import Path

from marimo_studio._delivery.records import ASGIApp
from marimo_studio._notebook.records import NotebookSpec
from marimo_studio._projections import (
    STUDIO_RESULT_SELECTOR as STUDIO_RESULT_SELECTOR,
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
    "STUDIO_RESULT_SELECTOR",
    "ASGIApp",
    "NotebookSpec",
    "create_asgi_app",
    "inspect_notebook",
]
