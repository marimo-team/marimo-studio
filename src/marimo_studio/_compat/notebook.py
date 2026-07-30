"""Compile notebook graph metadata through Marimo's loader."""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from marimo_studio._compat.server import assert_supported_version
from marimo_studio.errors import (
    ConfigurationError,
    NotebookSourceError,
    ProtocolError,
)


@dataclass(frozen=True)
class StaticCell:
    runtime_id: str
    code: str
    name: str
    definitions: tuple[str, ...]
    references: tuple[str, ...]
    parents: tuple[str, ...]
    children: tuple[str, ...]
    column: int | None
    disabled: bool
    hide_code: bool
    source_line: int


@dataclass(frozen=True)
class StaticNotebook:
    cells: tuple[StaticCell, ...]
    app_config: dict[str, Any]


def _is_canonical_empty_notebook(path: Path) -> bool:
    try:
        body = ast.parse(path.read_text(encoding="utf-8"), filename=str(path)).body
    except (OSError, UnicodeError, SyntaxError):
        return False
    if len(body) != 4:
        return False
    import_node, version_node, app_node, guard_node = body
    marimo_import = (
        isinstance(import_node, ast.Import)
        and len(import_node.names) == 1
        and import_node.names[0].name == "marimo"
        and import_node.names[0].asname is None
    )
    generated_version = (
        isinstance(version_node, ast.Assign)
        and len(version_node.targets) == 1
        and isinstance(version_node.targets[0], ast.Name)
        and version_node.targets[0].id == "__generated_with"
        and isinstance(version_node.value, ast.Constant)
        and isinstance(version_node.value.value, str)
    )
    app_constructor = (
        isinstance(app_node, ast.Assign)
        and len(app_node.targets) == 1
        and isinstance(app_node.targets[0], ast.Name)
        and app_node.targets[0].id == "app"
        and isinstance(app_node.value, ast.Call)
        and isinstance(app_node.value.func, ast.Attribute)
        and isinstance(app_node.value.func.value, ast.Name)
        and app_node.value.func.value.id == "marimo"
        and app_node.value.func.attr == "App"
        and not app_node.value.args
    )
    run_guard = (
        isinstance(guard_node, ast.If)
        and isinstance(guard_node.test, ast.Compare)
        and isinstance(guard_node.test.left, ast.Name)
        and guard_node.test.left.id == "__name__"
        and len(guard_node.test.ops) == 1
        and isinstance(guard_node.test.ops[0], ast.Eq)
        and len(guard_node.test.comparators) == 1
        and isinstance(guard_node.test.comparators[0], ast.Constant)
        and guard_node.test.comparators[0].value == "__main__"
        and len(guard_node.body) == 1
        and isinstance(guard_node.body[0], ast.Expr)
        and isinstance(guard_node.body[0].value, ast.Call)
        and isinstance(guard_node.body[0].value.func, ast.Attribute)
        and isinstance(guard_node.body[0].value.func.value, ast.Name)
        and guard_node.body[0].value.func.value.id == "app"
        and guard_node.body[0].value.func.attr == "run"
        and not guard_node.body[0].value.args
        and not guard_node.body[0].value.keywords
        and not guard_node.orelse
    )
    return marimo_import and generated_version and app_constructor and run_guard


def load_static_notebook(path: Path) -> StaticNotebook:
    """Compile notebook metadata without running cell bodies."""
    assert_supported_version()
    try:
        from marimo._ast.load import get_notebook_status, load_app

        status = get_notebook_status(str(path))
        if status.notebook is None:
            raise NotebookSourceError(f"marimo could not parse notebook: {path}")
        app = load_app(path)
        if app is None:
            raise NotebookSourceError(f"File does not define a marimo app: {path}")
        app._maybe_initialize()
    except ConfigurationError:
        raise
    except Exception as error:
        raise NotebookSourceError(
            f"Could not inspect notebook {path}: {error}"
        ) from error

    serialized_cells = status.notebook.cells
    rows = list(app._cell_manager.cell_data())
    empty_placeholder = (
        not serialized_cells
        and len(rows) == 1
        and rows[0].cell is None
        and rows[0].code == ""
        and rows[0].name == "_"
        and _is_canonical_empty_notebook(path)
    )
    if empty_placeholder:
        return StaticNotebook(cells=(), app_config=app._config.asdict())
    if status.status not in {"valid", "has_warnings"}:
        raise NotebookSourceError(f"marimo could not parse notebook: {path}")

    source_lines = [cell.lineno for cell in serialized_cells]
    if len(rows) != len(source_lines):
        raise ProtocolError("marimo returned inconsistent notebook cell metadata")

    cells: list[StaticCell] = []
    for index, row in enumerate(rows):
        if row.cell is None:
            raise ProtocolError(f"marimo did not compile cell {row.cell_id}")
        cells.append(
            StaticCell(
                runtime_id=row.cell_id,
                code=row.code,
                name=row.name,
                definitions=tuple(sorted(row.cell.defs)),
                references=tuple(sorted(row.cell.refs)),
                parents=tuple(sorted(app._graph.parents[row.cell_id])),
                children=tuple(sorted(app._graph.children[row.cell_id])),
                column=row.config.column,
                disabled=row.config.disabled,
                hide_code=row.config.hide_code,
                source_line=source_lines[index],
            )
        )
    return StaticNotebook(cells=tuple(cells), app_config=app._config.asdict())
