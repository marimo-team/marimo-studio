"""Protect saved notebook inspection."""

from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path
from typing import Any

import pytest

import marimo_studio._notebook.inspection as inspection_module
from marimo_studio import inspect_notebook
from marimo_studio._notebook.cell_refs import (
    _cell_fingerprint,
    _layout_fingerprint,
)
from marimo_studio._notebook.inspection import (
    inspect_notebook_result,
    inspect_runtime,
    select_cells,
)
from marimo_studio.errors import CapabilityInputError, ConfigurationError

from ..helpers import empty_notebook_source


def test_inspection_accepts_a_canonical_empty_notebook(tmp_path: Path) -> None:
    notebook = tmp_path / "empty.py"
    notebook.write_text(empty_notebook_source(), encoding="utf-8")

    assert inspect_notebook(notebook).cells == ()


def test_inspection_builds_graph_without_executing_cells(
    notebook_path: Path,
) -> None:
    marker = notebook_path.parent / "cell-executed"

    spec = inspect_notebook(notebook_path)

    assert not marker.exists()
    assert spec.path == notebook_path
    assert len(spec.cells) == 2
    producer, output = spec.cells
    assert "x" in producer.definitions
    assert output.references == ("x",)
    assert output.upstream == (producer.ref,)
    assert producer.downstream == (output.ref,)
    assert output.has_output_expression is True
    assert output.code is None
    assert output.source.start_line < output.source.end_line


def test_inspection_can_return_complete_cell_code(notebook_path: Path) -> None:
    spec = inspect_notebook(notebook_path, include_code=True)

    assert spec.cells[1].code is not None
    assert "doubled = x * 2" in spec.cells[1].code
    assert spec.cells[1].preview == spec.cells[1].code


def test_inspection_reports_complete_decorated_cell_spans(
    tmp_path: Path,
) -> None:
    source = (
        "\n\n"
        + """\
import marimo

__generated_with = "0.24.0"
app = marimo.App()


with app.setup:
    import math


@app.cell(
    hide_code=True,
)
def _(
    value,
):
    total = value + 1
    total
    return (total,)


@app.function
def normalize(value: int) -> int:
    return value + 1


@app.class_definition
class Model:
    value = 1


@app.cell
async def async_result():
    result = 2
    result
    return
"""
    )
    notebook = tmp_path / "spans.py"
    notebook.write_text(source, encoding="utf-8")

    cells = inspect_notebook(notebook).cells
    multiline = next(cell for cell in cells if "total = value + 1" in cell.preview)
    setup = next(cell for cell in cells if cell.name == "setup")
    function = next(cell for cell in cells if cell.name == "*normalize")
    class_definition = next(cell for cell in cells if cell.name == "*Model")
    async_cell = next(cell for cell in cells if cell.name == "async_result")
    lines = source.splitlines()

    assert setup.source.start_line == lines.index("with app.setup:") + 1
    assert setup.source.end_line == lines.index("    import math") + 1
    assert multiline.source.start_line == lines.index("@app.cell(") + 1
    assert multiline.source.end_line == lines.index("    return (total,)") + 1
    assert function.source.start_line == lines.index("@app.function") + 1
    assert function.source.end_line == lines.index("    return value + 1") + 1
    assert (
        class_definition.source.start_line == lines.index("@app.class_definition") + 1
    )
    assert class_definition.source.end_line == lines.index("    value = 1") + 1
    assert async_cell.source.start_line == lines.index("@app.cell", 20) + 1
    assert async_cell.source.end_line == lines.index("    return", 20) + 1


def test_inspection_selects_display_cells_before_applying_the_limit(
    notebook_path: Path,
) -> None:
    spec = inspect_notebook(notebook_path)

    selected = select_cells(spec, output_expressions=True, limit=1)

    assert selected == (spec.cells[1],)


def test_inspection_selects_exact_cells_by_ref_name_and_index(
    notebook_path: Path,
) -> None:
    spec = inspect_notebook(notebook_path)
    producer, output = spec.cells

    selected = select_cells(
        spec,
        selectors=(producer.ref, str(output.ref), output.index),
    )

    assert selected == (producer, output)
    with pytest.raises(CapabilityInputError) as raised:
        select_cells(spec, selectors=("missing-cell",))
    assert raised.value.code == "invalid-inspection-request"
    assert raised.value.field == "selectors"


def test_inspection_includes_complete_upstream_context(
    notebook_path: Path,
) -> None:
    spec = inspect_notebook(notebook_path)

    selected = select_cells(
        spec,
        selectors=(1,),
        output_expressions=True,
        context="upstream",
        limit=1,
    )

    assert selected == spec.cells


def test_selected_inspection_attaches_code_only_to_result_cells(
    notebook_path: Path,
) -> None:
    result = inspect_notebook_result(
        notebook_path,
        include_code=True,
        selectors=(1,),
    )

    assert len(result.cells) == 1
    assert result.cells[0].index == 1
    expected = inspect_notebook(notebook_path, include_code=True).cells[1]
    assert result.cells[0].code == expected.code
    assert result.cells[0].code is not None
    assert hashlib.sha256(result.cells[0].code.encode()).hexdigest() == (
        result.cells[0].code_sha256
    )
    assert all(cell.code is None for cell in result.notebook.cells)


def test_runtime_inspection_requests_only_selected_cells_and_values(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    async def probe(_path: Path, **options: object) -> Any:
        captured.update(options)
        return object()

    monkeypatch.setattr(inspection_module, "create_runtime_probe", lambda: probe)
    result = asyncio.run(
        inspect_runtime(
            notebook_path,
            include_code=True,
            selectors=(1,),
        )
    )

    assert captured["cell_ids"] == (result.cells[0].runtime_id,)
    assert captured["variables"] == result.cells[0].definitions
    assert all(cell.code is None for cell in result.notebook.cells)


def test_runtime_inspection_rejects_a_change_after_static_selection(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    load = inspection_module.create_static_notebook_loader()

    def load_then_change(path: Path):
        static = load(path)
        path.write_text(
            path.read_text(encoding="utf-8") + "\n# changed\n", encoding="utf-8"
        )
        return static

    called = False

    async def probe(_path: Path, **_options: object) -> Any:
        nonlocal called
        called = True
        return object()

    monkeypatch.setattr(
        inspection_module,
        "create_static_notebook_loader",
        lambda: load_then_change,
    )
    monkeypatch.setattr(inspection_module, "create_runtime_probe", lambda: probe)

    with pytest.raises(ConfigurationError, match="changed during inspection"):
        asyncio.run(inspect_runtime(notebook_path, selectors=(1,)))
    assert called is False


def test_runtime_inspection_rejects_a_change_during_execution(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def probe(path: Path, **_options: object) -> Any:
        path.write_text(
            path.read_text(encoding="utf-8") + "\n# changed\n", encoding="utf-8"
        )
        return object()

    monkeypatch.setattr(inspection_module, "create_runtime_probe", lambda: probe)

    with pytest.raises(ConfigurationError, match="changed during inspection"):
        asyncio.run(inspect_runtime(notebook_path, selectors=(1,)))


def test_cell_fingerprint_survives_marimo_string_formatting() -> None:
    expanded = '''\
mo.md(
    f"""
    ## Report
    Value: {value}
    """
)
'''
    serialized = '''\
mo.md(f"""
## Report
Value: {value}
""")
'''

    assert _cell_fingerprint(expanded) != _cell_fingerprint(serialized)
    assert _layout_fingerprint(expanded) == _layout_fingerprint(serialized)
    assert _layout_fingerprint(serialized) != _layout_fingerprint(
        serialized.replace("Report", "Forecast")
    )


def test_cell_fingerprint_ignores_python_formatting_and_comments() -> None:
    compact = "total=sum(values)\ntotal"
    formatted = """\
# Aggregate the current selection.
total = sum(values)

total
"""

    assert _cell_fingerprint(compact) == _cell_fingerprint(formatted)


def test_cell_fingerprint_distinguishes_multiline_string_values() -> None:
    indented = 'value = """\\n    alpha\\n    beta\\n"""'
    flush = 'value = """\\nalpha\\nbeta\\n"""'
    leading_newline = 'value = """\\nalpha\\n"""'
    no_leading_newline = 'value = """alpha\\n"""'

    assert _cell_fingerprint(indented) != _cell_fingerprint(flush)
    assert _cell_fingerprint(leading_newline) != _cell_fingerprint(no_leading_newline)
    assert _layout_fingerprint(indented) != _layout_fingerprint(flush)
