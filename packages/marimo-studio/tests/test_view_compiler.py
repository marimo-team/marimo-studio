import json
import re
from dataclasses import replace
from pathlib import Path

import pytest
from marimo_export.wire import canonical_json_bytes

from marimo_studio._server.presentation import NotebookPresentation
from marimo_studio._server.studio.view_compiler import ViewBindings, compile_export_view
from marimo_studio._workspace import load_studio
from marimo_studio.values import parse_value_reference
from marimo_studio.workspace import bind_cell, ensure_view

from .helpers import replace_app_shell

_HOST_BOUNDARY_FIXTURE = (
    Path(__file__).resolve().parents[2]
    / "protocol"
    / "fixtures"
    / "projection-host-boundary.json"
)


def _write_shell(template: Path, content: str) -> None:
    template.write_text(
        replace_app_shell(template.read_text(encoding="utf-8"), content),
        encoding="utf-8",
    )


def _configured_template(notebook_path: Path) -> Path:
    source = notebook_path.read_text(encoding="utf-8")
    named = source.replace("def _(x):", "def chart(x):")
    assert named != source
    notebook_path.write_text(named, encoding="utf-8")
    setup = ensure_view(notebook_path)
    bind_cell(load_studio(notebook_path), "summary", 1)
    bind_cell(load_studio(notebook_path), "headline", 1)
    return setup.root / "index.html"


def test_view_compiler_derives_outputs_and_deduplicates_shared_sources(
    notebook_path: Path,
) -> None:
    template = _configured_template(notebook_path)
    _write_shell(
        template,
        '<span mo-value="doubled"></span>'
        '<marimo-output value="doubled"></marimo-output>'
        '<marimo-cell name="summary"></marimo-cell>'
        '<marimo-cell name="headline"></marimo-cell>',
    )

    snapshot = NotebookPresentation(notebook_path).snapshot("dashboard")
    compiled = compile_export_view(snapshot)

    assert compiled.spec.default_state == "baseline"
    assert dict(compiled.spec.states) == {"baseline": {}}
    assert set(compiled.bindings.values) == {"doubled"}
    assert set(compiled.bindings.outputs) == {"doubled"}
    assert set(compiled.bindings.cells) == {"headline", "summary"}
    assert compiled.bindings.cells["headline"] == compiled.bindings.cells["summary"]
    assert len(compiled.spec.outputs) == 3

    value_output = compiled.bindings.values["doubled"]
    rendered_output = compiled.bindings.outputs["doubled"]
    cell_output = compiled.bindings.cells["summary"]
    assert value_output == "value:doubled"
    assert rendered_output == "output:doubled"
    assert cell_output == "cell:chart"
    assert compiled.spec.to_value() == {
        "schema": "marimo-export.spec.v1",
        "default_state": "baseline",
        "states": {"baseline": {}},
        "outputs": {
            value_output: {"source": {"kind": "value", "selector": "doubled"}},
            rendered_output: {"source": {"kind": "output", "selector": "doubled"}},
            cell_output: {
                "source": {
                    "kind": "cell",
                    "by": "name",
                    "value": "chart",
                }
            },
        },
    }


def test_layout_and_host_changes_preserve_export_spec_identity(
    notebook_path: Path,
) -> None:
    template = _configured_template(notebook_path)
    presentation = NotebookPresentation(notebook_path)
    _write_shell(
        template,
        '<section><span mo-value="doubled"></span>'
        '<marimo-output value="doubled"></marimo-output>'
        '<marimo-cell name="summary"></marimo-cell></section>',
    )
    first = compile_export_view(
        presentation.snapshot("dashboard"),
        states={"baseline": {}, "selected": {"x": 2}},
        default_state="selected",
    )

    _write_shell(
        template,
        '<main><marimo-cell name="headline"></marimo-cell>'
        '<div><marimo-output value="doubled"></marimo-output></div>'
        '<span mo-value="doubled"></span></main>',
    )
    second = compile_export_view(
        presentation.snapshot("dashboard"),
        states={"baseline": {}, "selected": {"x": 2}},
        default_state="selected",
    )

    assert first.spec.default_state == second.spec.default_state == "selected"
    assert first.spec.states == second.spec.states
    assert canonical_json_bytes(first.spec.to_value()) == canonical_json_bytes(
        second.spec.to_value()
    )
    assert first.bindings.cells != second.bindings.cells
    assert dict(first.bindings.cells) == {"summary": first.bindings.cells["summary"]}
    assert dict(second.bindings.cells) == {
        "headline": second.bindings.cells["headline"]
    }
    assert first.bindings.cells["summary"] == second.bindings.cells["headline"]
    assert first.bindings.outputs == second.bindings.outputs
    assert first.bindings.values == second.bindings.values


def test_oversized_readable_output_name_uses_a_bounded_digest(
    notebook_path: Path,
) -> None:
    template = _configured_template(notebook_path)
    _write_shell(template, '<span mo-value="doubled"></span>')
    snapshot = NotebookPresentation(notebook_path).snapshot("dashboard")
    source = "a" * 250
    bounded = replace(
        snapshot,
        value_references={source: parse_value_reference(source)},
    )

    compiled = compile_export_view(bounded)

    name = compiled.bindings.values[source]
    assert re.fullmatch(r"value:[0-9a-f]{64}", name)
    assert len(name.encode()) <= 255


def test_projection_host_bound_matches_the_browser_fixture() -> None:
    fixture = json.loads(_HOST_BOUNDARY_FIXTURE.read_text(encoding="utf-8"))
    host = fixture["character"] * fixture["valid_repetitions"]
    invalid = host + fixture["invalid_suffix"]

    bindings = ViewBindings(
        cells={},
        outputs={},
        values={host: "value:doubled"},
    )

    assert len(host.encode("utf-8")) == fixture["maximum_utf8_bytes"]
    assert dict(bindings.values) == {host: "value:doubled"}
    with pytest.raises(ValueError, match="1024 UTF-8 bytes"):
        ViewBindings(cells={}, outputs={}, values={invalid: "value:doubled"})


def test_readable_cell_name_collision_uses_source_specific_digests(
    notebook_path: Path,
) -> None:
    template = _configured_template(notebook_path)
    _write_shell(template, '<marimo-cell name="summary"></marimo-cell>')
    snapshot = NotebookPresentation(notebook_path).snapshot("dashboard")
    base = snapshot.resolved.aliases["summary"]
    named = replace(base, name="shared", runtime_id="named-runtime")
    identified = replace(base, name=None, runtime_id="shared")
    resolved_view = replace(
        snapshot.resolved.views["dashboard"],
        cell_aliases=("named-host", "identified-host"),
    )
    resolved = replace(
        snapshot.resolved,
        aliases={
            **snapshot.resolved.aliases,
            "named-host": named,
            "identified-host": identified,
        },
        views={**snapshot.resolved.views, "dashboard": resolved_view},
    )
    colliding = replace(snapshot, resolved=resolved)

    compiled = compile_export_view(colliding)

    named_output = compiled.bindings.cells["named-host"]
    identified_output = compiled.bindings.cells["identified-host"]
    assert re.fullmatch(r"cell:[0-9a-f]{64}", named_output)
    assert re.fullmatch(r"cell:[0-9a-f]{64}", identified_output)
    assert named_output != identified_output
    assert compiled.spec.to_value()["outputs"] == {
        named_output: {"source": {"kind": "cell", "by": "name", "value": "shared"}},
        identified_output: {"source": {"kind": "cell", "by": "id", "value": "shared"}},
    }
