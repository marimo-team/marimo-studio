"""Compile notebook graph metadata through Marimo's loader."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from marimo_studio._compat.server import assert_supported_version
from marimo_studio.errors import ConfigurationError, ProtocolError


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


def load_static_notebook(path: Path) -> StaticNotebook:
    """Compile notebook metadata without running cell bodies."""
    assert_supported_version()
    try:
        from marimo._ast.load import get_notebook_status, load_app

        status = get_notebook_status(str(path))
        if status.status not in {"valid", "has_warnings"} or status.notebook is None:
            raise ConfigurationError(f"marimo could not parse notebook: {path}")
        app = load_app(path)
        if app is None:
            raise ConfigurationError(f"File does not define a marimo app: {path}")
        app._maybe_initialize()
    except ConfigurationError:
        raise
    except Exception as error:
        raise ConfigurationError(
            f"Could not inspect notebook {path}: {error}"
        ) from error

    source_lines = [cell.lineno for cell in status.notebook.cells]
    rows = list(app._cell_manager.cell_data())
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
