"""Shared setup for static export contract tests."""

from __future__ import annotations

from pathlib import Path

from marimo_studio._views.api import bind_cell, ensure_view
from marimo_studio._workspace import load_studio

from ..helpers import replace_app_shell


def configure_export_view(notebook: Path) -> Path:
    setup = ensure_view(notebook)
    bind_cell(load_studio(notebook), "cell-2", 1)
    document = setup.root / "index.html"
    document.write_text(
        replace_app_shell(
            document.read_text(encoding="utf-8"),
            """
            <marimo-cell name="cell-2"></marimo-cell>
            <output mo-value="doubled"></output>
            <marimo-output value="doubled"></marimo-output>
            """,
        ),
        encoding="utf-8",
    )
    return setup.root
