from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest
from marimo_export import StateSpace

from marimo_studio._prepared.compiler import compile_export_view
from marimo_studio._server.presentation.service import NotebookPresentation
from marimo_studio.errors import PublicationError

from ..delivery.export_test_support import configure_export_view


def _snapshot(notebook: Path):
    configure_export_view(notebook)
    return NotebookPresentation(notebook).snapshot("dashboard")


def test_compiler_uses_native_values_and_deduplicates_targets(
    notebook_path: Path,
) -> None:
    snapshot = _snapshot(notebook_path)

    compiled = compile_export_view(
        snapshot.resolved,
        snapshot.view_name,
        (*snapshot.sites, replace(snapshot.sites[1], id="site-repeat")),
    )

    assert compiled.bindings.values == {"doubled": "value:doubled"}
    assert compiled.bindings.outputs == {"doubled": "output:doubled"}
    assert compiled.bindings.cells == {"cell-2": "cell:cell-2"}
    cell_id = snapshot.resolved.aliases["cell-2"].runtime_id
    assert compiled.spec.to_value()["outputs"] == {
        "cell:cell-2": {"source": {"kind": "cell", "by": "id", "value": cell_id}},
        "output:doubled": {"source": {"kind": "output", "selector": "doubled"}},
        "value:doubled": {"source": {"kind": "native", "selector": "doubled"}},
    }


def test_compiler_exports_accepting_outputs_as_media(notebook_path: Path) -> None:
    snapshot = _snapshot(notebook_path)
    sites = tuple(
        replace(site, accept=("image/svg+xml", "image/png"))
        if site.kind == "output"
        else site
        for site in snapshot.sites
    )

    compiled = compile_export_view(snapshot.resolved, snapshot.view_name, sites)

    outputs = cast(dict[str, object], compiled.spec.to_value()["outputs"])
    assert compiled.bindings.outputs == {"doubled": "output:doubled"}
    assert outputs["output:doubled"] == {
        "source": {"kind": "export", "selector": "doubled"},
        "exporter": {
            "name": "media",
            "options": {"accept": ["image/svg+xml", "image/png"], "scale": 2.0},
            "dependencies": [],
        },
    }


def test_compiler_combines_a_public_state_space_with_inferred_outputs(
    notebook_path: Path,
) -> None:
    snapshot = _snapshot(notebook_path)
    state_space = StateSpace(
        default_state="matrix-000000",
        matrix={"scale": [1, 3]},
    )

    compiled = compile_export_view(
        snapshot.resolved,
        snapshot.view_name,
        snapshot.sites,
        state_space=state_space,
    )

    assert compiled.spec.default_state == "matrix-000000"
    assert compiled.spec.states == {
        "matrix-000000": {"scale": 1},
        "matrix-000001": {"scale": 3},
    }


def test_compiler_rejects_a_dynamic_mount(notebook_path: Path) -> None:
    snapshot = _snapshot(notebook_path)
    dynamic = replace(snapshot.sites[0], targets=None)

    with pytest.raises(
        PublicationError,
        match=r"projection at index\.html:\d+:\d+ selects its target at runtime",
    ):
        compile_export_view(
            snapshot.resolved,
            snapshot.view_name,
            (dynamic, *snapshot.sites[1:]),
        )
