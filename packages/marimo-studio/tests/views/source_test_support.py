"""Shared setup for source document contract tests."""

from pathlib import Path

from marimo_studio._views.api import ensure_view
from marimo_studio._workspace import load_studio
from marimo_studio._workspace.models import StudioWorkspace

SOURCE_PATH = "index.html"


def document(label: str) -> str:
    return (
        "<!doctype html><html><head></head><body>"
        f'<main id="app-shell">{label}</main></body></html>'
    )


def studio(notebook: Path) -> StudioWorkspace:
    ensure_view(notebook)
    return load_studio(notebook)
