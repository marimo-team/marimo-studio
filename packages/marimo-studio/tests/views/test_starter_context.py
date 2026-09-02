"""Protect notebook-aware starter target planning."""

from __future__ import annotations

from pathlib import Path, PurePosixPath

import marimo
import pytest

from marimo_studio import inspect_notebook
from marimo_studio._views.starter_context import (
    starter_bindings,
    starter_context,
)
from marimo_studio._workspace.models import StudioDefinition
from marimo_studio.errors import ConfigurationError
from marimo_studio.view_providers import CellRef, StarterPlan


def _notebook(path: Path) -> None:
    path.write_text(
        f'''\
import marimo

__generated_with = "{marimo.__version__}"
app = marimo.App()

@app.cell
def summary():
    "Summary"
    return

@app.cell
def _():
    "Details"
    return

@app.cell
def _():
    "Conclusion"
    return

if __name__ == "__main__":
    app.run()
''',
        encoding="utf-8",
    )


def _studio(path: Path, cells: dict[str, CellRef]) -> StudioDefinition:
    return StudioDefinition(
        root=path.parent,
        config_path=path,
        config_source="notebook",
        notebook=path,
        view_root=path.parent / "__marimo__" / "studio" / path.stem,
        default_view="dashboard",
        default_runtime="server",
        runtimes=("server",),
        preserve_session=False,
        cells=cells,
        show_cell_logs=True,
        config_generation="fixture-config-generation",
    )


def test_starter_context_prefers_names_aliases_and_collision_free_targets(
    tmp_path: Path,
) -> None:
    path = tmp_path / "analysis.py"
    _notebook(path)
    notebook = inspect_notebook(path, include_code=True)
    first, second, _third = notebook.cells
    studio = _studio(
        path,
        {
            "details": second.ref,
            "cell-3": first.ref,
        },
    )

    context = starter_context(notebook, studio, "dashboard")

    assert [context.cell_targets[cell.ref].target for cell in notebook.cells] == [
        "summary",
        "details",
        "cell-3-2",
    ]


def test_starter_bindings_persist_selected_aliases_for_the_observed_cells(
    tmp_path: Path,
) -> None:
    path = tmp_path / "analysis.py"
    _notebook(path)
    notebook = inspect_notebook(path, include_code=True)
    studio = _studio(path, {"details": notebook.cells[1].ref})
    context = starter_context(notebook, studio, "dashboard")
    plan = StarterPlan(
        files={PurePosixPath("index.html"): b"<html></html>"},
        cell_targets=tuple(context.cell_targets.values()),
    )

    bindings = starter_bindings(notebook, studio, (plan,))

    assert bindings == {
        "details": notebook.cells[1].ref,
        "cell-3": notebook.cells[2].ref,
    }


def test_starter_bindings_reject_an_alias_rebound_during_creation(
    tmp_path: Path,
) -> None:
    path = tmp_path / "analysis.py"
    _notebook(path)
    notebook = inspect_notebook(path, include_code=True)
    context = starter_context(notebook, None, "dashboard")
    plan = StarterPlan(
        files={PurePosixPath("index.html"): b"<html></html>"},
        cell_targets=(context.cell_targets[notebook.cells[1].ref],),
    )
    rebound = _studio(path, {"cell-2": notebook.cells[2].ref})

    with pytest.raises(ConfigurationError, match="changed while files were prepared"):
        starter_bindings(notebook, rebound, (plan,))
