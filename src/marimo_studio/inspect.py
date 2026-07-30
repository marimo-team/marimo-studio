"""Inspect a notebook statically or through an explicit runtime probe."""

from __future__ import annotations

import ast
import hashlib
from dataclasses import dataclass, replace
from pathlib import Path

from marimo_studio._cell_refs import cell_refs
from marimo_studio._compat.notebook import load_static_notebook
from marimo_studio._compat.runtime_probe import (
    RuntimeProbe,
    probe_runtime,
)
from marimo_studio.errors import ConfigurationError
from marimo_studio.types import (
    CellConfigSpec,
    CellSpec,
    NotebookSpec,
    SourceSpan,
)

_PREVIEW_LINES = 8
_PREVIEW_CHARS = 600
_RUNTIME_VALUE_BYTES = 64 * 1024


@dataclass(frozen=True)
class RuntimeInspection:
    notebook: NotebookSpec
    runtime: RuntimeProbe


def select_cells(
    notebook: NotebookSpec,
    *,
    output_expressions: bool = False,
    limit: int | None = None,
) -> tuple[CellSpec, ...]:
    """Select notebook cells for an inspection result."""
    cells = tuple(
        cell
        for cell in notebook.cells
        if not output_expressions or cell.has_output_expression
    )
    return cells if limit is None else cells[:limit]


def _source_spans(path: Path, source_lines: list[int]) -> list[SourceSpan]:
    source = path.read_text(encoding="utf-8")
    try:
        module = ast.parse(source, filename=str(path))
    except SyntaxError as error:
        raise ConfigurationError(f"Could not parse notebook {path}: {error}") from error

    functions = {
        node.lineno: node
        for node in module.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and any(
            (
                isinstance(decorator, ast.Attribute)
                and decorator.attr in {"cell", "setup"}
            )
            or (
                isinstance(decorator, ast.Call)
                and isinstance(decorator.func, ast.Attribute)
                and decorator.func.attr in {"cell", "setup"}
            )
            for decorator in node.decorator_list
        )
    }

    spans: list[SourceSpan] = []
    for source_line in source_lines:
        node = functions.get(source_line)
        if node is None:
            spans.append(SourceSpan(source_line, source_line))
            continue
        decorator_lines = [
            decorator.lineno for decorator in node.decorator_list if decorator.lineno
        ]
        start_line = min([node.lineno, *decorator_lines])
        spans.append(
            SourceSpan(
                start_line=start_line,
                end_line=node.end_lineno or node.lineno,
                start_column=node.col_offset,
                end_column=node.end_col_offset or node.col_offset,
            )
        )
    return spans


def _has_output_expression(code: str) -> bool:
    try:
        body = ast.parse(code).body
    except SyntaxError:
        return False
    return bool(body and isinstance(body[-1], ast.Expr))


def _preview(code: str) -> str:
    lines = code.strip().splitlines()
    preview = "\n".join(lines[:_PREVIEW_LINES])
    if len(lines) > _PREVIEW_LINES:
        preview += "\n…"
    if len(preview) > _PREVIEW_CHARS:
        preview = preview[: _PREVIEW_CHARS - 1] + "…"
    return preview


def inspect_notebook(
    path: str | Path,
    *,
    include_code: bool = False,
) -> NotebookSpec:
    """Return the static cell inventory for a marimo notebook.

    Cell bodies are compiled for graph analysis and are never executed.
    """
    notebook_path = Path(path).expanduser().resolve()
    if not notebook_path.is_file():
        raise ConfigurationError(f"Notebook does not exist: {notebook_path}")

    static = load_static_notebook(notebook_path)
    source_digests = [
        hashlib.sha256(cell.code.encode("utf-8")).hexdigest() for cell in static.cells
    ]
    refs = cell_refs(cell.code for cell in static.cells)

    by_runtime_id = {
        cell.runtime_id: refs[index] for index, cell in enumerate(static.cells)
    }
    source_spans = _source_spans(
        notebook_path,
        [cell.source_line for cell in static.cells],
    )

    cells = tuple(
        CellSpec(
            ref=refs[index],
            runtime_id=cell.runtime_id,
            index=index,
            name=cell.name if cell.name != "_" else None,
            source=source_spans[index],
            code_sha256=source_digests[index],
            preview=_preview(cell.code),
            definitions=cell.definitions,
            references=cell.references,
            upstream=tuple(
                by_runtime_id[runtime_id]
                for runtime_id in cell.parents
                if runtime_id in by_runtime_id
            ),
            downstream=tuple(
                by_runtime_id[runtime_id]
                for runtime_id in cell.children
                if runtime_id in by_runtime_id
            ),
            config=CellConfigSpec(
                column=cell.column,
                disabled=cell.disabled,
                hide_code=cell.hide_code,
            ),
            has_output_expression=_has_output_expression(cell.code),
            code=cell.code if include_code else None,
        )
        for index, cell in enumerate(static.cells)
    )
    order = {cell.ref: cell.index for cell in cells}
    cells = tuple(
        replace(
            cell,
            upstream=tuple(sorted(cell.upstream, key=order.__getitem__)),
            downstream=tuple(sorted(cell.downstream, key=order.__getitem__)),
        )
        for cell in cells
    )
    return NotebookSpec(
        path=notebook_path,
        cells=cells,
        app_config=static.app_config,
    )


async def inspect_runtime(
    path: str | Path,
    *,
    include_code: bool = False,
) -> RuntimeInspection:
    """Run a notebook and return its static graph, outputs, and JSON values."""
    notebook = inspect_notebook(path, include_code=include_code)
    variables = tuple(
        dict.fromkeys(
            definition for cell in notebook.cells for definition in cell.definitions
        )
    )
    runtime = await probe_runtime(
        notebook.path,
        cell_ids=tuple(cell.runtime_id for cell in notebook.cells),
        variables=variables,
        show_tracebacks=True,
        value_max_bytes=_RUNTIME_VALUE_BYTES,
    )
    return RuntimeInspection(notebook=notebook, runtime=runtime)
