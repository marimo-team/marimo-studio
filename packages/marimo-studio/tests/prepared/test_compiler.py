from __future__ import annotations

from dataclasses import replace
from pathlib import Path, PurePosixPath
from typing import cast

import pytest
from marimo_export import StateSpace
from marimo_export.values import Size

from marimo_studio._prepared.compiler import compile_export_view
from marimo_studio._server.presentation.service import NotebookPresentation
from marimo_studio.errors import PublicationError
from marimo_studio.view_providers._artifact_sites import ArtifactSite

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


def _render_reads(
    snapshot,
    render: str,
    *,
    output_accept: tuple[str, ...],
    size: Size | None = None,
) -> tuple[ArtifactSite, ...]:
    """Return one read per page target, as the render of ``render`` reads it."""
    return tuple(
        replace(
            site,
            id=f"read-{render}-{site.kind}",
            render=PurePosixPath(render),
            accept=(
                output_accept
                if site.kind == "output"
                else ("application/json",)
                if site.kind == "value"
                else ("image/png",)
            ),
            size=size if site.kind == "output" else None,
        )
        for site in snapshot.sites
    )


def test_compiler_exports_render_reads_as_json_and_sized_media(
    notebook_path: Path,
) -> None:
    snapshot = _snapshot(notebook_path)
    reads = _render_reads(
        snapshot, "main.typ", output_accept=("application/pdf",), size=Size(250.38)
    )

    compiled = compile_export_view(
        snapshot.resolved, snapshot.view_name, (*snapshot.sites, *reads)
    )

    outputs = cast(dict[str, object], compiled.spec.to_value()["outputs"])
    report = compiled.bindings.renders["main.typ"]
    value = report.values["doubled"]
    output = report.outputs["doubled"]
    assert value != compiled.bindings.values["doubled"]
    assert output != compiled.bindings.outputs["doubled"]
    assert outputs[value] == {"source": {"kind": "json", "selector": "doubled"}}
    assert outputs[output] == {
        "source": {"kind": "export", "selector": "doubled"},
        "exporter": {
            "name": "media",
            "options": {
                "accept": ["application/pdf"],
                "scale": 2.0,
                "size": {"width": 250.38, "height": None},
            },
            "dependencies": [],
        },
    }
    assert compiled.bindings.values == {"doubled": "value:doubled"}
    assert compiled.bindings.outputs == {"doubled": "output:doubled"}


def test_render_reads_in_the_page_form_share_the_page_output(
    notebook_path: Path,
) -> None:
    snapshot = _snapshot(notebook_path)
    page = tuple(
        replace(site, accept=("image/png",)) if site.kind == "output" else site
        for site in snapshot.sites
    )
    reads = _render_reads(snapshot, "main.typ", output_accept=("image/png",))

    compiled = compile_export_view(
        snapshot.resolved, snapshot.view_name, (*page, *reads)
    )

    report = compiled.bindings.renders["main.typ"]
    assert report.outputs == {"doubled": "output:doubled"}
    assert report.cells == {"cell-2": "cell:cell-2"}
    assert set(cast(dict[str, object], compiled.spec.to_value()["outputs"])) == {
        "cell:cell-2",
        "output:doubled",
        "value:doubled",
        report.values["doubled"],
    }


def test_two_renders_reading_one_target_in_different_forms_get_distinct_outputs(
    notebook_path: Path,
) -> None:
    snapshot = _snapshot(notebook_path)
    reads = (
        *_render_reads(snapshot, "main.typ", output_accept=("application/pdf",)),
        *_render_reads(snapshot, "slides.typ", output_accept=("image/svg+xml",)),
    )

    compiled = compile_export_view(
        snapshot.resolved, snapshot.view_name, (*snapshot.sites, *reads)
    )

    report = compiled.bindings.renders["main.typ"].outputs["doubled"]
    slides = compiled.bindings.renders["slides.typ"].outputs["doubled"]
    assert len({report, slides, compiled.bindings.outputs["doubled"]}) == 3
    assert compiled.bindings.renders["main.typ"].values == (
        compiled.bindings.renders["slides.typ"].values
    )


def test_view_bindings_record_the_reads_of_each_render(
    notebook_path: Path,
) -> None:
    snapshot = _snapshot(notebook_path)
    reads = _render_reads(snapshot, "main.typ", output_accept=("application/pdf",))

    page_only = compile_export_view(
        snapshot.resolved, snapshot.view_name, snapshot.sites
    )
    with_render = compile_export_view(
        snapshot.resolved, snapshot.view_name, (*snapshot.sites, *reads)
    )

    assert page_only.bindings.to_dict() == {
        "cells": {"cell-2": "cell:cell-2"},
        "outputs": {"doubled": "output:doubled"},
        "values": {"doubled": "value:doubled"},
        "renders": {},
    }
    report = with_render.bindings.renders["main.typ"]
    assert report.outputs["doubled"] != "output:doubled"
    assert report.values["doubled"] != "value:doubled"
    assert with_render.bindings.to_dict()["renders"] == {
        "main.typ": {
            "cells": {"cell-2": "cell:cell-2"},
            "outputs": {"doubled": report.outputs["doubled"]},
            "values": {"doubled": report.values["doubled"]},
        }
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
