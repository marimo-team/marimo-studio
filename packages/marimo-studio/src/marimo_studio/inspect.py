"""Inspect a notebook statically or through an explicit runtime probe."""

from __future__ import annotations

import ast
import hashlib
from dataclasses import dataclass, replace
from pathlib import Path

from marimo_studio._cell_refs import cell_refs
from marimo_studio._composition import create_tooling_adapters
from marimo_studio._runtime_limits import DEFAULT_RUNTIME_TIMEOUT
from marimo_studio.errors import CapabilityInputError, ConfigurationError
from marimo_studio.types import (
    CellConfigSpec,
    CellSpec,
    NotebookSpec,
    RuntimeProbe,
)

_PREVIEW_LINES = 8
_PREVIEW_CHARS = 600
_RUNTIME_VALUE_BYTES = 64 * 1024


@dataclass(frozen=True)
class InspectionResult:
    """Selected notebook cells with optional runtime evidence."""

    notebook: NotebookSpec
    cells: tuple[CellSpec, ...]
    runtime: RuntimeProbe | None = None

    def select(
        self,
        *,
        output_expressions: bool = False,
        limit: int | None = None,
    ) -> InspectionResult:
        return replace(
            self,
            cells=select_cells(
                self.notebook,
                output_expressions=output_expressions,
                limit=limit,
            ),
        )

    def to_dict(self) -> dict[str, object]:
        payload = self.notebook.to_dict()
        if self.runtime is None:
            payload["cells"] = [cell.to_dict() for cell in self.cells]
            return payload
        payload["cells"] = [
            {
                **cell.to_dict(),
                "runtime": self.runtime.cells[cell.runtime_id].to_dict(),
            }
            for cell in self.cells
        ]
        payload["runtime"] = self.runtime.values.to_dict()
        return payload


def select_cells(
    notebook: NotebookSpec,
    *,
    output_expressions: bool = False,
    limit: int | None = None,
) -> tuple[CellSpec, ...]:
    """Select notebook cells for an inspection result."""
    if limit is not None and (
        not isinstance(limit, int) or isinstance(limit, bool) or limit < 1
    ):
        raise CapabilityInputError(
            "invalid-inspection-request",
            "limit",
            "limit must be an integer greater than or equal to 1",
        )
    cells = tuple(
        cell
        for cell in notebook.cells
        if not output_expressions or cell.has_output_expression
    )
    return cells if limit is None else cells[:limit]


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

    static = create_tooling_adapters().notebook(notebook_path)
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


def inspect_notebook_result(
    path: str | Path,
    *,
    include_code: bool = False,
    output_expressions: bool = False,
    limit: int | None = None,
) -> InspectionResult:
    """Return selected static notebook cells as one capability result."""
    notebook = inspect_notebook(path, include_code=include_code)
    return InspectionResult(
        notebook=notebook,
        cells=select_cells(
            notebook,
            output_expressions=output_expressions,
            limit=limit,
        ),
    )


async def inspect_runtime(
    path: str | Path,
    *,
    include_code: bool = False,
    runtime_timeout: float = DEFAULT_RUNTIME_TIMEOUT,
) -> InspectionResult:
    """Run a notebook and return its static graph, outputs, and JSON values."""
    notebook = inspect_notebook(path, include_code=include_code)
    variables = tuple(
        dict.fromkeys(
            definition for cell in notebook.cells for definition in cell.definitions
        )
    )
    runtime = await create_tooling_adapters().runner(
        notebook.path,
        cell_ids=tuple(cell.runtime_id for cell in notebook.cells),
        variables=variables,
        output_selector_groups=(),
        show_tracebacks=True,
        timeout=runtime_timeout,
        value_max_bytes=_RUNTIME_VALUE_BYTES,
    )
    return InspectionResult(
        notebook=notebook,
        cells=notebook.cells,
        runtime=runtime,
    )


__all__ = [
    "InspectionResult",
    "inspect_notebook",
    "inspect_notebook_result",
    "inspect_runtime",
    "select_cells",
]
