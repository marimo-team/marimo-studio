"""Create notebook-local Studio view files."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

import tomlkit

from marimo_studio._workspace.config import (
    canonical_view_root,
    discover_studio_definition,
    editable_studio_config,
    load_studio,
    validate_view_name,
)
from marimo_studio._workspace.files import read_text
from marimo_studio._workspace.metadata import (
    configured_notebook_source,
    set_cell_bindings,
)
from marimo_studio._workspace.models import ViewSetupResult
from marimo_studio._workspace.scaffold import starter_aliases, starter_view_files
from marimo_studio._workspace.transactions import write_text_transaction
from marimo_studio.errors import ConfigurationError
from marimo_studio.inspect import inspect_notebook
from marimo_studio.types import CellRef


def _updated_project_config(path: Path, bindings: Mapping[str, CellRef]) -> str:
    document = tomlkit.parse(read_text(path))
    set_cell_bindings(editable_studio_config(document), bindings)
    return tomlkit.dumps(document)


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
    notebook_spec = inspect_notebook(notebook_path)
    studio = discover_studio_definition(notebook_path)
    selected = name or (studio.default_view if studio is not None else "dashboard")
    validate_view_name(selected)
    default_view = studio.default_view if studio is not None else selected
    view_root = canonical_view_root(notebook_path)
    view_names = tuple(dict.fromkeys((default_view, selected)))
    new_templates = tuple(
        view_name
        for view_name in view_names
        if not (view_root / view_name / "index.html").is_file()
    )
    aliases, bindings = starter_aliases(
        notebook_spec.cells,
        studio.cells if studio is not None else {},
    )
    new_bindings = bindings if new_templates else {}

    writes: dict[Path, str] = {}
    if studio is None or studio.uses_notebook_config:
        configured = configured_notebook_source(
            notebook_path,
            default_view,
            new_bindings,
        )
        if configured != read_text(notebook_path):
            writes[notebook_path] = configured
        config_path = notebook_path
        transaction_root = notebook_path.parent
    else:
        config_path = studio.config_path
        transaction_root = studio.root
        if new_bindings:
            configured = _updated_project_config(config_path, new_bindings)
            if configured != read_text(config_path):
                writes[config_path] = configured

    for view_name in view_names:
        for path, content in starter_view_files(
            view_root,
            view_name,
            notebook_path.stem,
            aliases,
        ).items():
            if not path.exists():
                writes[path] = content

    created = tuple(sorted(path for path in writes if not path.exists()))
    updated = tuple(sorted(path for path in writes if path.exists()))
    if not dry_run and writes:
        write_text_transaction(transaction_root, writes)
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
