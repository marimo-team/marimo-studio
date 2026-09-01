from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any


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
