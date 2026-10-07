"""Compile notebook graph metadata through Marimo's loader."""

from __future__ import annotations

import ast
from contextlib import AbstractContextManager
from hashlib import sha256
from pathlib import Path
from typing import TYPE_CHECKING

from marimo_studio._notebook.output_prediction import may_display_output
from marimo_studio._notebook.ports import StaticCell, StaticNotebook
from marimo_studio._notebook.records import CellKind, SourceSpan
from marimo_studio.errors import NotebookSourceError, ProtocolError

if TYPE_CHECKING:
    from marimo._ast.app import App
    from marimo._schemas.serialization import NotebookSerializationV1


def notebook_write_lock(path: Path) -> AbstractContextManager[None]:
    """Return Marimo's cross-process lock for one saved notebook."""
    from marimo._environments.script_metadata import notebook_file_lock

    return notebook_file_lock(str(path))


def run_guard_line(source: str) -> int | None:
    """Return the standard Marimo run guard line for notebook source."""
    from marimo._ast.scanner import scan_notebook

    return scan_notebook(source).run_guard_line


def _is_canonical_empty_notebook(source: str) -> bool:
    try:
        body = ast.parse(source).body
    except SyntaxError:
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


def _check_hint(path: Path) -> str:
    return (
        f"Run `marimo check {path.name}` to see the problem, fix it, then save "
        "the notebook again."
    )


def _compile(
    path: Path,
    source: str,
    *,
    canonical_empty: bool,
    leading_lines: int,
) -> tuple[NotebookSerializationV1, App]:
    from marimo._ast.errors import (
        CycleError,
        MultipleDefinitionError,
        UnparsableError,
    )
    from marimo._ast.load import (
        all_violations_soft,
        get_notebook_serializer,
        is_non_marimo_markdown,
        is_non_marimo_python_script,
        load_notebook_ir,
    )
    from marimo._schemas.serialization import UnparsableCell

    try:
        serialized = get_notebook_serializer(path).deserialize(
            source,
            filepath=str(path),
        )
    except Exception as error:
        raise NotebookSourceError(
            f"marimo could not parse notebook {path}: {error}",
            summary=f"Marimo cannot parse {path.name}.",
            hint=_check_hint(path),
        ) from error
    if (
        serialized is None
        or is_non_marimo_python_script(serialized)
        or is_non_marimo_markdown(serialized)
    ):
        raise NotebookSourceError(
            f"{path} is not a marimo notebook",
            summary=f"{path.name} is not a Marimo notebook.",
            hint=(
                f"Convert it with `marimo convert {path.name} -o "
                f"{path.stem}_marimo.py`, then open the converted notebook."
            ),
        )
    if not serialized.cells and not canonical_empty:
        raise NotebookSourceError(
            f"{path} has no marimo cells",
            summary=f"{path.name} has no Marimo cells.",
            hint="Add a cell in Marimo, then save the notebook again.",
        )
    hard = [
        violation
        for violation in serialized.violations
        if not all_violations_soft([violation])
    ]
    if not serialized.valid or (hard and not canonical_empty):
        if not hard:
            raise NotebookSourceError(
                f"marimo could not parse notebook {path}",
                summary=f"Marimo cannot parse {path.name}.",
                hint=_check_hint(path),
            )
        line = hard[0].lineno + leading_lines
        raise NotebookSourceError(
            f"marimo could not parse notebook {path} at line {line}: "
            f"{hard[0].description}",
            summary=f"Marimo cannot parse {path.name} near line {line}.",
            hint=_check_hint(path),
        )
    try:
        app = load_notebook_ir(serialized, filepath=str(path))
        app._cell_manager.ensure_one_cell()
        app._maybe_initialize()
    except UnparsableError as error:
        line = next(
            (
                cell.lineno + leading_lines
                for cell in serialized.cells
                if isinstance(cell, UnparsableCell)
            ),
            None,
        )
        raise NotebookSourceError(
            f"Could not inspect notebook {path}: {error}",
            summary=(
                f"The notebook cell at line {line} contains invalid code."
                if line is not None
                else "A notebook cell contains invalid code."
            ),
            hint="Fix the cell in Marimo, then save the notebook again.",
        ) from error
    except MultipleDefinitionError as error:
        raise NotebookSourceError(
            f"Could not inspect notebook {path}: {error}",
            summary="More than one notebook cell defines the same name.",
            hint=(
                "Rename or remove the duplicate definition in Marimo, then save "
                "the notebook again."
            ),
        ) from error
    except CycleError as error:
        raise NotebookSourceError(
            f"Could not inspect notebook {path}: {error}",
            summary="Notebook cells depend on each other in a cycle.",
            hint=(
                "Remove one reference from the cycle in Marimo, then save the "
                "notebook again."
            ),
        ) from error
    except Exception as error:
        raise NotebookSourceError(
            f"Could not inspect notebook {path}: {error}",
            summary=f"Marimo cannot inspect {path.name}.",
            hint=_check_hint(path),
        ) from error
    return serialized, app


def load_static_notebook(path: Path, source: str) -> StaticNotebook:
    """Compile notebook metadata from ``source`` without running cell bodies.

    ``path`` selects Marimo's notebook format and names the app.
    """
    from marimo._ast.compiler import ends_with_semicolon
    from marimo._ast.scanner import scan_notebook
    from marimo._convert.common import get_markdown_from_cell
    from marimo._schemas.serialization import (
        ClassCell,
        FunctionCell,
        SetupCell,
        UnparsableCell,
    )

    source_revision = sha256(source.encode("utf-8")).hexdigest()
    canonical_empty = _is_canonical_empty_notebook(source)
    leading_whitespace = len(source) - len(source.lstrip())
    leading_lines = source[:leading_whitespace].count("\n")
    serialized, app = _compile(
        path,
        source,
        canonical_empty=canonical_empty,
        leading_lines=leading_lines,
    )

    serialized_cells = serialized.cells
    rows = list(app._cell_manager.cell_data())
    empty_placeholder = (
        not serialized_cells
        and len(rows) == 1
        and rows[0].cell is None
        and rows[0].code == ""
        and rows[0].name == "_"
        and canonical_empty
    )
    if empty_placeholder:
        return StaticNotebook(
            cells=(),
            app_config=app._config.asdict(),
            source_revision=source_revision,
        )
    source_lines = [cell.lineno + leading_lines for cell in serialized_cells]
    scanned_cells = scan_notebook(source).cells
    if len(rows) != len(source_lines) or len(rows) != len(scanned_cells):
        raise ProtocolError("marimo returned inconsistent notebook cell metadata")

    lines = source.splitlines()
    cells: list[StaticCell] = []

    def cell_kind(cell: object) -> CellKind:
        if isinstance(cell, SetupCell):
            return "setup"
        if isinstance(cell, FunctionCell):
            return "function"
        if isinstance(cell, ClassCell):
            return "class"
        if isinstance(cell, UnparsableCell):
            return "unparsable"
        return "cell"

    for index, row in enumerate(rows):
        scanned = scanned_cells[index]
        source_line = source_lines[index]
        if row.cell is None:
            raise ProtocolError(
                f"marimo did not compile the cell at line {source_line}"
            )
        if not scanned.start_line <= source_line <= scanned.end_line:
            raise ProtocolError(
                "marimo returned an inconsistent source location for the cell at "
                f"line {source_line}"
            )
        end_column = len(lines[scanned.end_line - 1])
        compiled = row.cell._cell
        final = compiled.mod.body[-1] if compiled.mod.body else None
        has_output_expression = isinstance(final, ast.Expr) and not ends_with_semicolon(
            compiled.code
        )
        cells.append(
            StaticCell(
                runtime_id=row.cell_id,
                code=row.code,
                name=row.name,
                kind=cell_kind(serialized_cells[index]),
                markdown=get_markdown_from_cell(row.cell, row.code),
                has_output_expression=has_output_expression,
                may_display_output=(
                    has_output_expression or may_display_output(compiled.mod)
                ),
                definitions=tuple(sorted(row.cell.defs)),
                references=tuple(sorted(row.cell.refs)),
                parents=tuple(sorted(app._graph.parents[row.cell_id])),
                children=tuple(sorted(app._graph.children[row.cell_id])),
                column=row.config.column,
                disabled=row.config.disabled,
                hide_code=row.config.hide_code,
                source=SourceSpan(
                    start_line=scanned.start_line,
                    end_line=scanned.end_line,
                    end_column=end_column,
                ),
            )
        )
    return StaticNotebook(
        cells=tuple(cells),
        app_config=app._config.asdict(),
        source_revision=source_revision,
    )
