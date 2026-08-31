"""Inspect a notebook statically or through an explicit runtime probe."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path

from marimo_studio._composition import (
    create_runtime_probe,
    create_static_notebook_loader,
)
from marimo_studio._notebook.cell_refs import cell_refs
from marimo_studio._notebook.ports import StaticNotebook
from marimo_studio._notebook.records import (
    CellConfigSpec,
    CellSelector,
    CellSpec,
    InspectionContext,
    InspectionResult,
    NotebookSpec,
    select_cells,
)
from marimo_studio._processes.limits import DEFAULT_RUNTIME_TIMEOUT
from marimo_studio.errors import ConfigurationError

_PREVIEW_LINES = 8
_PREVIEW_CHARS = 600
_RUNTIME_VALUE_BYTES = 64 * 1024


def _revision(static: StaticNotebook, cells: tuple[CellSpec, ...]) -> str:
    payload = {
        "app_config": static.app_config,
        "cells": [cell.to_dict() for cell in cells],
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


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
    notebook, static = _notebook_snapshot(path)
    if not include_code:
        return notebook
    return replace(
        notebook,
        cells=_attach_selected_code(static, notebook.cells),
    )


def _notebook_snapshot(path: str | Path) -> tuple[NotebookSpec, StaticNotebook]:
    notebook_path = Path(path).expanduser().resolve()
    if not notebook_path.is_file():
        raise ConfigurationError(f"Notebook does not exist: {notebook_path}")
    static = create_static_notebook_loader()(notebook_path)
    source_digests = [
        hashlib.sha256(cell.code.encode("utf-8")).hexdigest() for cell in static.cells
    ]
    refs = cell_refs(cell.code for cell in static.cells)

    by_runtime_id = {
        cell.runtime_id: refs[index] for index, cell in enumerate(static.cells)
    }
    cells = tuple(
        CellSpec(
            ref=refs[index],
            runtime_id=cell.runtime_id,
            index=index,
            kind=cell.kind,
            name=cell.name if cell.name != "_" else None,
            source=cell.source,
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
            has_output_expression=cell.has_output_expression,
            displays_output=cell.displays_output,
            markdown=cell.markdown,
            code=None,
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
    return (
        NotebookSpec(
            path=notebook_path,
            revision=_revision(static, cells),
            cells=cells,
            app_config=static.app_config,
        ),
        static,
    )


def inspect_notebook_result(
    path: str | Path,
    *,
    include_code: bool = False,
    selectors: tuple[CellSelector, ...] = (),
    output_expressions: bool = False,
    context: InspectionContext = "selected",
    limit: int | None = None,
) -> InspectionResult:
    """Return selected static notebook cells as one capability result."""
    notebook, static = _notebook_snapshot(path)
    cells = select_cells(
        notebook,
        selectors=selectors,
        output_expressions=output_expressions,
        context=context,
        limit=limit,
    )
    if include_code:
        cells = _attach_selected_code(static, cells)
    return InspectionResult(
        notebook=notebook,
        cells=cells,
    )


async def inspect_runtime(
    path: str | Path,
    *,
    include_code: bool = False,
    selectors: tuple[CellSelector, ...] = (),
    output_expressions: bool = False,
    context: InspectionContext = "selected",
    limit: int | None = None,
    runtime_timeout: float = DEFAULT_RUNTIME_TIMEOUT,
) -> InspectionResult:
    """Run a notebook and return its static graph, outputs, and JSON values."""
    notebook, static = _notebook_snapshot(path)
    selected = select_cells(
        notebook,
        selectors=selectors,
        output_expressions=output_expressions,
        context=context,
        limit=limit,
    )
    cells = _attach_selected_code(static, selected) if include_code else selected
    variables = tuple(
        dict.fromkeys(
            definition for cell in selected for definition in cell.definitions
        )
    )
    _require_source_revision(notebook.path, static.source_revision)
    runtime = await create_runtime_probe()(
        notebook.path,
        cell_ids=tuple(cell.runtime_id for cell in selected),
        variables=variables,
        output_selector_groups=(),
        show_tracebacks=True,
        timeout=runtime_timeout,
        value_max_bytes=_RUNTIME_VALUE_BYTES,
    )
    _require_source_revision(notebook.path, static.source_revision)
    return InspectionResult(
        notebook=notebook,
        cells=cells,
        runtime=runtime,
    )


def _attach_selected_code(
    static: StaticNotebook,
    cells: tuple[CellSpec, ...],
) -> tuple[CellSpec, ...]:
    code = {cell.runtime_id: cell.code for cell in static.cells}
    return tuple(
        replace(
            cell,
            code=code[cell.runtime_id],
        )
        for cell in cells
    )


def _require_source_revision(path: Path, expected: str) -> None:
    try:
        current = hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as error:
        raise ConfigurationError(
            f"Notebook changed during inspection: {path}. Retry the request."
        ) from error
    if current != expected:
        raise ConfigurationError(
            f"Notebook changed during inspection: {path}. Retry the request."
        )
