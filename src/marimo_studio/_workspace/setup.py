"""Create notebook-local Studio view files."""

from __future__ import annotations

from contextlib import suppress
from html import escape
from pathlib import Path

from marimo_studio._compat.notebook import load_static_notebook
from marimo_studio._workspace.config import (
    canonical_view_root,
    discover_studio_definition,
    load_studio,
    validate_view_name,
)
from marimo_studio._workspace.files import (
    atomic_write_text,
    read_text,
    reject_mutable_symlinks,
)
from marimo_studio._workspace.metadata import (
    configured_notebook_source,
    notebook_config,
)
from marimo_studio._workspace.models import ViewSetupResult
from marimo_studio.errors import ConfigurationError


def _blank_template(name: str, title_text: str) -> str:
    title = escape(title_text)
    return f"""\
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{title}</title>
    <link rel="stylesheet" href="./_marimo-studio/views/{name}/static/app.css">
  </head>
  <body>
    <main id="app-shell"></main>
  </body>
</html>
"""


_BLANK_CSS = """\
:root {
  color-scheme: light dark;
}

* {
  box-sizing: border-box;
}

body {
  margin: 0;
}
"""


def _view_files(view_root: Path, name: str, title_text: str) -> dict[Path, str]:
    root = view_root / name
    return {
        root / "index.html": _blank_template(name, title_text),
        root / "app.css": _BLANK_CSS,
    }


def _write_transaction(root: Path, writes: dict[Path, str]) -> None:
    reject_mutable_symlinks(root, set(writes))
    snapshots = {path: read_text(path) if path.is_file() else None for path in writes}
    created_directories: set[Path] = set()
    for path in writes:
        current = path.parent
        while current != root and not current.exists():
            created_directories.add(current)
            parent = current.parent
            if parent == current:
                raise ConfigurationError(
                    f"Mutable view path is outside the notebook directory: {path}"
                )
            current = parent
    try:
        for path, content in writes.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_text(path, content)
    except Exception:
        for path, content in snapshots.items():
            if content is None:
                path.unlink(missing_ok=True)
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                atomic_write_text(path, content)
        for directory in sorted(
            created_directories,
            key=lambda path: len(path.parts),
            reverse=True,
        ):
            with suppress(OSError):
                directory.rmdir()
        raise


def ensure_view(
    notebook: str | Path,
    name: str | None = None,
    *,
    dry_run: bool = False,
) -> ViewSetupResult:
    """Configure a notebook when needed and create a named view."""
    notebook_path = Path(notebook).expanduser().resolve()
    if not notebook_path.is_file():
        raise ConfigurationError(f"Notebook does not exist: {notebook_path}")
    if notebook_path.suffix != ".py":
        raise ConfigurationError(f"Expected a Python Marimo notebook: {notebook_path}")
    load_static_notebook(notebook_path)

    inline = notebook_config(notebook_path)
    studio = None if inline is not None else discover_studio_definition(notebook_path)
    configured_default = inline.get("default") if inline is not None else None
    if configured_default is not None and not isinstance(configured_default, str):
        raise ConfigurationError("default must name a view")
    selected = (
        name
        or configured_default
        or (studio.default_view if studio is not None else "dashboard")
    )
    validate_view_name(selected)
    writes: dict[Path, str] = {}
    if studio is None:
        configured = configured_notebook_source(notebook_path, selected)
        if configured != read_text(notebook_path):
            writes[notebook_path] = configured
        config_path = notebook_path
        default_view = configured_default or selected
    else:
        config_path = studio.config_path
        default_view = studio.default_view

    view_root = canonical_view_root(notebook_path)
    for view_name in dict.fromkeys((default_view, selected)):
        for path, content in _view_files(
            view_root,
            view_name,
            notebook_path.stem,
        ).items():
            if not path.exists():
                writes[path] = content

    created = tuple(sorted(path for path in writes if not path.exists()))
    updated = tuple(sorted(path for path in writes if path.exists()))
    if not dry_run and writes:
        _write_transaction(notebook_path.parent, writes)
    loaded = load_studio(notebook_path) if not dry_run else None
    return ViewSetupResult(
        studio=loaded,
        notebook=notebook_path,
        config_path=config_path,
        name=selected,
        root=view_root / selected,
        created=created,
        updated=updated,
        dry_run=dry_run,
    )
