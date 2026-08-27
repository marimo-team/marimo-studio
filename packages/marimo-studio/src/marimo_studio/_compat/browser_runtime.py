"""Build browser runtime projections for the pinned Marimo release."""

from __future__ import annotations

import hashlib
from pathlib import Path

from marimo_studio._compat.browser_notebook import (
    BROWSER_BRIDGE_CELL_NAME,
    browser_notebook_source,
)
from marimo_studio._delivery.browser_ports import (
    BrowserRuntimeCell,
    BrowserRuntimeProjection,
)
from marimo_studio.errors._internal import CompatibilityError


def _digest(*values: str) -> str:
    digest = hashlib.sha256()
    for value in values:
        digest.update(value.encode("utf-8"))
        digest.update(b"\0")
    return digest.hexdigest()


def _execution_cells(
    notebook: Path,
    code: str,
) -> tuple[tuple[BrowserRuntimeCell, ...], str]:
    try:
        from marimo._ast.load import (
            get_notebook_serializer,
            load_notebook_ir,
        )

        notebook_ir = get_notebook_serializer(notebook).deserialize(
            code,
            filepath=str(notebook),
        )
        if notebook_ir is None or not notebook_ir.valid:
            raise ValueError("the projected notebook is invalid")
        app = load_notebook_ir(notebook_ir)
        app._maybe_initialize()
        rows = tuple(app._cell_manager.cell_data())
    except Exception as error:
        raise CompatibilityError(
            "Marimo could not compile the browser execution catalog."
        ) from error
    cells = tuple(BrowserRuntimeCell(str(row.cell_id), row.code) for row in rows)
    bootstrap = tuple(
        cell.runtime_id
        for cell, row in zip(cells, rows, strict=True)
        if row.name == BROWSER_BRIDGE_CELL_NAME
        and "_studio_projection_bridge_ready" in row.code
    )
    if len(bootstrap) != 1:
        raise CompatibilityError(
            "Marimo could not identify the browser projection bootstrap cell."
        )
    return cells, bootstrap[0]


class PrivateBrowserRuntimeProjector:
    """Build one browser runtime projection for the pinned Marimo release."""

    def __init__(self, *, version: str, commit: str) -> None:
        self.version = version
        self.commit = commit

    def project(
        self,
        notebook: Path,
        source: str,
    ) -> BrowserRuntimeProjection:
        code = browser_notebook_source(notebook, source)
        cells, bootstrap_cell_id = _execution_cells(notebook, code)
        return BrowserRuntimeProjection(
            instance=_digest(self.version, self.commit, code),
            version=self.version,
            commit=self.commit,
            code=code,
            execution_cells=cells,
            bootstrap_cell_id=bootstrap_cell_id,
        )
