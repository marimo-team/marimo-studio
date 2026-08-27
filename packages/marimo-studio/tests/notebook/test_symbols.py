"""Protect notebook symbol graph construction."""

from __future__ import annotations

from pathlib import Path

from marimo_studio._notebook.inspection import inspect_notebook
from marimo_studio._projections.symbol_graph import build_notebook_symbol_graph


def test_symbol_graph_indexes_targets_variables_and_dependencies(
    notebook_path: Path,
) -> None:
    notebook = inspect_notebook(notebook_path)
    first, second = notebook.cells

    graph = build_notebook_symbol_graph(
        notebook,
        {"inputs": first, "summary": second},
    )

    assert graph.cell_targets == {
        "inputs": (first.ref,),
        "summary": (second.ref,),
    }
    assert graph.variables["x"].producers == (first.ref,)
    assert graph.variables["x"].consumers == (second.ref,)
    assert graph.variables["doubled"].producers == (second.ref,)
    assert graph.dependency_closure(second.ref) == (first.ref, second.ref)
    assert graph.cells[first.ref].aliases == ("inputs",)
    assert graph.cells[second.ref].aliases == ("summary",)

    payload = graph.to_dict()
    assert payload["revision"] == graph.revision
    assert payload["cellTargets"] == {
        "inputs": [str(first.ref)],
        "summary": [str(second.ref)],
    }


def test_symbol_graph_revision_tracks_semantic_aliases(notebook_path: Path) -> None:
    notebook = inspect_notebook(notebook_path)
    first, second = notebook.cells

    original = build_notebook_symbol_graph(notebook, {"summary": second})
    repeated = build_notebook_symbol_graph(notebook, {"summary": second})
    renamed = build_notebook_symbol_graph(notebook, {"result": second})
    rebound = build_notebook_symbol_graph(notebook, {"summary": first})

    assert repeated.revision == original.revision
    assert renamed.revision != original.revision
    assert rebound.revision != original.revision
