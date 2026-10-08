from __future__ import annotations

from pathlib import Path

import pytest
from marimo_export import open_export

from marimo_studio._delivery.export import export_view
from marimo_studio._views.api import prepare_view
from marimo_studio.view_providers._builtin.typst import provider as typst

pytestmark = pytest.mark.skipif(
    not typst.availability().available,
    reason="marimo-studio[typst] is unavailable",
)

REPORT = """#import "marimo.typ": marimo_cell, marimo_output, marimo_value
#set page(width: 8cm, height: auto)
#let summary = marimo_value("summary", default: (doubled: "unset", labels: ()))
#let chart = marimo_output("chart", width: 6cm)
#let bars = marimo_cell("bars", width: 6cm)
// Each prepared state supplies all three, so its rendition embeds both figures.
#if summary.doubled != "unset" {
  assert(chart != none, message: "no chart")
  assert(bars != none, message: "no bars cell")
}
Doubled is #summary.doubled for #summary.labels.len() labels
#chart
#bars
"""
SUMMARY_CELL = """@app.cell
def _(doubled):
    from matplotlib.figure import Figure

    summary = {"doubled": doubled, "labels": ["north", "south"]}
    chart = Figure(figsize=(4, 2))
    chart.subplots().bar(["doubled"], [doubled])
    return chart, summary


@app.cell
def bars(chart):
    chart
    return


if __name__"""


def _report(notebook: Path) -> Path:
    notebook.write_text(
        notebook.read_text(encoding="utf-8").replace("if __name__", SUMMARY_CELL),
        encoding="utf-8",
    )
    setup = prepare_view(notebook, "report", starter="marimo-studio/typst:default")
    setup.root.joinpath("main.typ").write_text(REPORT, encoding="utf-8")
    return setup.root


@pytest.mark.native_process
@pytest.mark.xdist_group("managed-export")
def test_zero_python_export_renders_each_prepared_state(
    notebook_path: Path,
    tmp_path: Path,
) -> None:
    _report(notebook_path)
    output = tmp_path / "site"

    export_view(notebook_path, output, runtime="zero-python", prepare_timeout=120.0)

    support = output / "_marimo-studio" / "views" / "report" / "zero-python"
    (instance,) = (path for path in support.iterdir() if path.is_dir())
    states = open_export(instance).states()
    renditions = {path.stem: path for path in (output / "renditions").iterdir()}
    assert set(renditions) == {state.fingerprint for state in states}
    default = output.joinpath("main.pdf").read_bytes()
    for path in renditions.values():
        assert path.suffix == ".pdf"
        assert path.read_bytes().startswith(b"%PDF-")
        assert path.read_bytes() != default
    assert not any(output.rglob("*.typ"))


def test_wasm_export_publishes_the_document_without_its_template(
    notebook_path: Path,
    tmp_path: Path,
) -> None:
    _report(notebook_path)
    output = tmp_path / "site"

    export_view(notebook_path, output, runtime="wasm")

    assert output.joinpath("main.pdf").read_bytes().startswith(b"%PDF-")
    assert '<marimo-document src="main.pdf"' in output.joinpath("index.html").read_text(
        encoding="utf-8"
    )
    assert not any(output.rglob("*.typ"))
