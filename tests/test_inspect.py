from __future__ import annotations

from pathlib import Path

from marimo_studio import inspect_notebook
from marimo_studio._cell_refs import (
    _cell_fingerprint,
    _layout_fingerprint,
)
from marimo_studio.inspect import select_cells


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
    source = """\
import marimo

__generated_with = "0.23.0"
app = marimo.App()


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
    notebook = tmp_path / "spans.py"
    notebook.write_text(source, encoding="utf-8")

    cells = inspect_notebook(notebook).cells
    multiline = next(cell for cell in cells if "total = value + 1" in cell.preview)
    function = next(cell for cell in cells if cell.name == "*normalize")
    class_definition = next(cell for cell in cells if cell.name == "*Model")
    async_cell = next(cell for cell in cells if cell.name == "async_result")
    lines = source.splitlines()

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


def test_inspection_reports_the_complete_setup_block(tmp_path: Path) -> None:
    source = """\
import marimo

__generated_with = "0.23.0"
app = marimo.App()


with app.setup:
    import math


@app.cell
def result():
    math.sqrt(4)
    return
"""
    notebook = tmp_path / "setup.py"
    notebook.write_text(source, encoding="utf-8")

    setup = next(
        cell for cell in inspect_notebook(notebook).cells if cell.name == "setup"
    )
    lines = source.splitlines()

    assert setup.source.start_line == lines.index("with app.setup:") + 1
    assert setup.source.end_line == lines.index("    import math") + 1


def test_inspection_selects_display_cells_before_applying_the_limit(
    notebook_path: Path,
) -> None:
    spec = inspect_notebook(notebook_path)

    selected = select_cells(spec, output_expressions=True, limit=1)

    assert selected == (spec.cells[1],)


def test_cell_fingerprint_survives_marimo_string_formatting() -> None:
    legacy = '''\
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

    assert _cell_fingerprint(legacy) != _cell_fingerprint(serialized)
    assert _layout_fingerprint(legacy) == _layout_fingerprint(serialized)
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
