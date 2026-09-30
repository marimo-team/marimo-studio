from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from marimo_studio._views.api import prepare_view
from marimo_studio.authoring import Workspace, open_workspace


def _project_configuration(notebook: Path) -> Path:
    path = notebook.parent / "pyproject.toml"
    path.write_text(
        f'''\
[tool.marimo-studio]
notebook = "{notebook.name}"
default = "dashboard"
''',
        encoding="utf-8",
    )
    return path


def _write_before_transaction(
    transaction: Any,
    path: Path,
    content: str,
):
    @contextmanager
    def wrapped(*args: Any, **kwargs: Any) -> Iterator[None]:
        path.write_text(content, encoding="utf-8")
        with transaction(*args, **kwargs):
            yield

    return wrapped


def _workspace_with_report(notebook: Path, *, project: bool = False) -> Workspace:
    if project:
        _project_configuration(notebook)
    prepare_view(notebook)
    prepare_view(notebook, "report")
    return open_workspace(notebook)
