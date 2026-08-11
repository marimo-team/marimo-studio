"""Build a programmatic Marimo application with presentation middleware."""

from __future__ import annotations

from pathlib import Path
from typing import cast

import marimo

from marimo_studio._composition import programmatic_middleware
from marimo_studio._workspace.config import load_studio_definition
from marimo_studio.types import ASGIApp


def create_asgi_app(notebook: str | Path) -> ASGIApp:
    """Build a run-mode Marimo app for one configured notebook."""
    definition = load_studio_definition(notebook)
    return cast(
        ASGIApp,
        marimo.create_asgi_app(
            quiet=True,
            skew_protection=True,
        )
        .with_app(
            path="/",
            root=str(definition.notebook),
            middleware=[programmatic_middleware(definition.notebook)],
        )
        .build(),
    )
