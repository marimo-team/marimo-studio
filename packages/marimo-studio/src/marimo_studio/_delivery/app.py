"""Build a programmatic Marimo application with presentation middleware."""

from __future__ import annotations

from pathlib import Path
from typing import cast

import marimo

from marimo_studio._composition import (
    own_programmatic_lifespans,
    programmatic_middleware,
)
from marimo_studio._delivery.records import ASGIApp
from marimo_studio._workspace.config import load_studio_definition


def create_asgi_app(notebook: str | Path) -> ASGIApp:
    """Build a run-mode Marimo app for one configured notebook."""
    definition = load_studio_definition(notebook)
    app = cast(
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
    return cast(ASGIApp, own_programmatic_lifespans(app))
