"""Inspect captured notebook source through an isolated temporary path."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory

from marimo_studio._notebook.ports import NotebookInspector
from marimo_studio._notebook.records import NotebookSpec


def inspect_notebook_source(
    path: Path,
    source: str,
    inspect_notebook: NotebookInspector,
    *,
    include_code: bool = False,
) -> NotebookSpec:
    """Inspect immutable source while retaining its authored path identity."""
    with TemporaryDirectory(prefix="marimo-studio-notebook-") as directory:
        staged = Path(directory) / path.name
        staged.write_bytes(source.encode("utf-8"))
        notebook = inspect_notebook(staged, include_code=include_code)
    return replace(notebook, path=path)
