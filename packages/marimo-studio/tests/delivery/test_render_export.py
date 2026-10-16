from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from marimo_export import StateSpace, open_export

import marimo_studio._delivery.renders as delivery_renders
from marimo_studio._delivery.export import export_view
from marimo_studio._views.api import prepare_view
from marimo_studio.errors import PublicationError
from marimo_studio.view_providers import ProjectDiagnostic
from marimo_studio.view_providers._builtin.typst import provider as typst

pytestmark = pytest.mark.skipif(
    not typst.availability().available,
    reason="marimo-studio[typst] is unavailable",
)

NOTEBOOK = """import marimo

app = marimo.App()


@app.cell
def _():
    import marimo as mo

    scale = mo.ui.slider(1, 3, value=1)
    return (scale,)


@app.cell
def _(scale):
    parity = {"odd": scale.value % 2 == 1}
    return (parity,)


if __name__ == "__main__":
    app.run()
"""
REPORT = """#import "marimo.typ": marimo_value
#let parity = marimo_value("parity", default: (odd: none))
Odd: #repr(parity.odd)
"""


def _report(notebook: Path) -> Path:
    setup = prepare_view(notebook, "report", starter="marimo-studio/typst:default")
    setup.root.joinpath("main.typ").write_text(REPORT, encoding="utf-8")
    return setup.root


def _three_states(root: Path) -> None:
    root.joinpath("states.yaml").write_text(
        json.dumps(
            StateSpace(
                default_state="one",
                states={"one": {}, "two": {"scale": 2}, "three": {"scale": 3}},
            ).to_value()
        ),
        encoding="utf-8",
    )


@pytest.mark.native_process
@pytest.mark.xdist_group("managed-export")
def test_zero_python_export_renders_each_distinct_state_capture_once(
    tmp_path: Path,
) -> None:
    notebook = tmp_path / "analysis.py"
    notebook.write_text(NOTEBOOK, encoding="utf-8")
    root = _report(notebook)
    # Scales one and three read the same parity, so they share one render.
    _three_states(root)
    output = tmp_path / "site"

    export_view(
        notebook, output, view="report", runtime="zero-python", prepare_timeout=120.0
    )

    view = output / "_marimo-studio" / "views" / "report"
    (instance,) = (path for path in (view / "zero-python").iterdir() if path.is_dir())
    scales = {
        state.fingerprint: state.inputs.get("scale", 1)
        for state in open_export(instance).states()
    }
    index = json.loads(view.joinpath("renders", "index.json").read_bytes())
    states: dict[str, dict[str, Any]] = index["states"]
    assert set(states) == set(scales)
    bundles = {
        scales[fingerprint]: entry["main.typ"] for fingerprint, entry in states.items()
    }
    assert bundles[1]["bundle"] == bundles[3]["bundle"] != bundles[2]["bundle"]
    for entry in bundles.values():
        (file,) = entry["files"]
        assert (entry["render"], entry["main"], file["mediaType"]) == (
            "main.typ",
            "main.pdf",
            "application/pdf",
        )
        content = view.joinpath("renders", entry["bundle"], "main.pdf").read_bytes()
        assert content.startswith(b"%PDF-")
        assert hashlib.sha256(content).hexdigest() == file["sha256"]
    assert not any(output.rglob("*.typ"))


@pytest.mark.native_process
@pytest.mark.xdist_group("managed-export")
def test_zero_python_export_keeps_the_warnings_of_each_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    notebook = tmp_path / "analysis.py"
    notebook.write_text(NOTEBOOK, encoding="utf-8")
    root = _report(notebook)
    # Scales one and three render identical files from different values.
    root.joinpath("main.typ").write_text(
        '#import "marimo.typ": marimo_value\n'
        '#let scale = marimo_value("scale.value", default: 1)\n'
        "Odd: #repr(calc.odd(scale))\n",
        encoding="utf-8",
    )
    _three_states(root)
    run_render = delivery_renders.run_render

    def warned(*args: Any) -> Any:
        bundle = run_render(*args)
        scale = args[3]["scale.value"]
        warning = ProjectDiagnostic("scale", "warning", f"Scale {scale}")
        return replace(bundle, warnings=(warning,))

    monkeypatch.setattr(delivery_renders, "run_render", warned)
    output = tmp_path / "site"

    export_view(
        notebook, output, view="report", runtime="zero-python", prepare_timeout=120.0
    )

    view = output / "_marimo-studio" / "views" / "report"
    index = json.loads(view.joinpath("renders", "index.json").read_bytes())
    entries = [state["main.typ"] for state in index["states"].values()]
    shown = {entry["warnings"][0]["message"]: entry["bundle"] for entry in entries}
    assert set(shown) == {"Scale 1", "Scale 2", "Scale 3"}
    assert shown["Scale 1"] == shown["Scale 3"] != shown["Scale 2"]


@pytest.mark.native_process
@pytest.mark.xdist_group("managed-export")
def test_zero_python_export_renders_a_render_without_reads_once(
    tmp_path: Path,
) -> None:
    notebook = tmp_path / "analysis.py"
    notebook.write_text(NOTEBOOK, encoding="utf-8")
    root = _report(notebook)
    root.joinpath("main.typ").write_text("= Methods\n", encoding="utf-8")
    output = tmp_path / "site"

    export_view(notebook, output, view="report", runtime="zero-python")

    view = output / "_marimo-studio" / "views" / "report"
    index = json.loads(view.joinpath("renders", "index.json").read_bytes())
    ((entry,),) = (state.values() for state in index["states"].values())
    assert (entry["render"], entry["main"], entry["absent"]) == (
        "main.typ",
        "main.pdf",
        [],
    )
    content = view.joinpath("renders", entry["bundle"], "main.pdf").read_bytes()
    assert content.startswith(b"%PDF-")


@pytest.mark.native_process
@pytest.mark.xdist_group("managed-export")
def test_zero_python_export_bounds_the_renders_its_states_need(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    notebook = tmp_path / "analysis.py"
    notebook.write_text(NOTEBOOK, encoding="utf-8")
    _three_states(_report(notebook))
    # Three states of one render stand in for the hundreds a real export needs
    # to exceed the budget.
    monkeypatch.setattr(delivery_renders, "MAX_STATIC_RENDERS", 2)

    with pytest.raises(PublicationError) as raised:
        export_view(
            notebook,
            tmp_path / "site",
            view="report",
            runtime="zero-python",
            prepare_timeout=120.0,
        )

    assert raised.value.code == "render-states-exceeded"


def test_wasm_export_publishes_the_page_without_its_template(tmp_path: Path) -> None:
    notebook = tmp_path / "analysis.py"
    notebook.write_text(NOTEBOOK, encoding="utf-8")
    _report(notebook)
    output = tmp_path / "site"

    export_view(notebook, output, view="report", runtime="wasm")

    page = output.joinpath("index.html").read_text(encoding="utf-8")
    assert '<marimo-output render="main.typ"></marimo-output>' in page
    assert not any(output.rglob("*.typ"))
