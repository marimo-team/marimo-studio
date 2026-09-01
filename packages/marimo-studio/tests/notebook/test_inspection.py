"""Protect saved notebook inspection."""

from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path
from textwrap import indent
from time import monotonic
from typing import Any

import marimo
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


def _write_single_cell_notebook(
    path: Path,
    body: str,
) -> None:
    path.write_text(
        f'''\
import marimo

__generated_with = "{marimo.__version__}"
app = marimo.App()

@app.cell
def _(mo):
{indent(body, "    ")}

if __name__ == "__main__":
    app.run()
''',
        encoding="utf-8",
    )


def _inspect_with_symbolic_budget(
    notebook: Path,
    budget: int,
    monkeypatch: pytest.MonkeyPatch,
) -> Any:
    loader: Any = inspection_module.create_static_notebook_loader()
    monkeypatch.setitem(
        loader.__globals__,
        "_POSSIBLE_OUTPUT_WORK_BUDGET",
        budget,
    )
    return inspect_notebook(notebook).cells[0]


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
    assert producer.kind == output.kind == "cell"
    assert producer.markdown is None
    assert output.code is None
    assert output.source.start_line < output.source.end_line


def test_inspection_can_return_complete_cell_code(notebook_path: Path) -> None:
    spec = inspect_notebook(notebook_path, include_code=True)

    assert spec.cells[1].code is not None
    assert "doubled = x * 2" in spec.cells[1].code
    assert spec.cells[1].preview == spec.cells[1].code


def test_cell_spec_serializes_the_possible_output_signal(notebook_path: Path) -> None:
    output = inspect_notebook(notebook_path).cells[1]

    assert output.may_display_output is True
    assert output.to_dict()["may_display_output"] is True


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
    assert setup.kind == "setup"
    assert function.kind == "function"
    assert class_definition.kind == "class"
    assert multiline.kind == async_cell.kind == "cell"


def test_inspection_exposes_literal_marimo_markdown(tmp_path: Path) -> None:
    notebook = tmp_path / "markdown.py"
    notebook.write_text(
        f'''\
import marimo

__generated_with = "{marimo.__version__}"
app = marimo.App(app_title="Notebook title")

@app.cell
def _():
    import marimo as mo
    return (mo,)

@app.cell
def introduction(mo):
    mo.md(r"""
    # Evidence report

    Current results.
    """)
    return

if __name__ == "__main__":
    app.run()
''',
        encoding="utf-8",
    )

    spec = inspect_notebook(notebook, include_code=True)

    assert spec.app_config["app_title"] == "Notebook title"
    assert spec.cells[1].markdown == "# Evidence report\n\nCurrent results."


def test_inspection_reports_possible_marimo_output_paths(tmp_path: Path) -> None:
    # Each case exercises a distinct symbolic execution decision. Equivalent
    # spellings and repeated control-flow shapes belong to the parser suites.
    cases = (
        ("visible-expression", 'mo.md("shown")\nreturn', False, True),
        ("semicolon-suppressed-expression", 'mo.md("hidden");\nreturn', False, False),
        (
            "marimo-sql",
            'result = mo.sql("SELECT 1")\nreturn (result,)',
            False,
            True,
        ),
        (
            "marimo-sql-output-disabled",
            'result = mo.sql("SELECT 1", output=False)\nreturn (result,)',
            False,
            False,
        ),
        (
            "output-append",
            'mo.output.append("shown")\nvalue = 1\nreturn (value,)',
            False,
            True,
        ),
        (
            "output-replace",
            'mo.output.replace("shown")\nvalue = 1\nreturn (value,)',
            False,
            True,
        ),
        (
            "output-replace-at-index",
            'mo.output.replace_at_index("shown", 0)\nvalue = 1\nreturn (value,)',
            False,
            True,
        ),
        (
            "unused-callback",
            'def emit():\n    mo.output.append("hidden")\nreturn (emit,)',
            False,
            False,
        ),
        (
            "invoked-callback",
            (
                "def emit():\n"
                '    mo.output.append("shown")\n'
                "emit()\n"
                "value = 1\n"
                "return (emit, value)"
            ),
            False,
            True,
        ),
        (
            "lazy-generator",
            (
                'events = (mo.output.append("hidden") for _ in range(1))\n'
                "return (events,)"
            ),
            False,
            False,
        ),
        (
            "consumed-generator",
            (
                'events = (mo.output.append("shown") for _ in range(1))\n'
                "values = tuple(events)\n"
                "return (events, values)"
            ),
            False,
            True,
        ),
        (
            "for-consumed-generator",
            (
                'events = (mo.output.append("shown") for _ in range(1))\n'
                "for event in events:\n"
                "    value = event\n"
                "return (events, value)"
            ),
            False,
            True,
        ),
        (
            "iter-next-consumed-generator",
            (
                'events = (mo.output.append("shown") for _ in range(1))\n'
                "iterator = iter(events)\n"
                "value = next(iterator)\n"
                "return (events, iterator, value)"
            ),
            False,
            True,
        ),
        (
            "consumed-named-generator",
            (
                "def events():\n"
                '    yield mo.output.append("shown")\n'
                "values = tuple(events())\n"
                "return (events, values)"
            ),
            False,
            True,
        ),
        (
            "immediate-lambda",
            '(lambda: mo.output.append("shown"))()\nreturn',
            False,
            True,
        ),
        (
            "lazy-lambda-generator",
            (
                "events = (lambda: "
                '(mo.output.append("hidden") for _ in range(1)))()\n'
                "return (events,)"
            ),
            False,
            False,
        ),
        (
            "consumed-lambda-generator",
            (
                "events = (lambda: "
                '(mo.output.append("shown") for _ in range(1)))()\n'
                "values = tuple(events)\n"
                "return (events, values)"
            ),
            False,
            True,
        ),
        (
            "captured-default",
            (
                "def emit():\n"
                '    mo.output.append("shown")\n'
                "def invoke(callback=emit):\n"
                "    callback()\n"
                "emit = lambda: None\n"
                "invoke()\n"
                "return (emit, invoke)"
            ),
            False,
            True,
        ),
        (
            "unreachable-after-return",
            (
                "def events():\n"
                "    return ()\n"
                '    return (mo.output.append("hidden") for _ in range(1))\n'
                "values = tuple(events())\n"
                "return (events, values)"
            ),
            False,
            False,
        ),
        (
            "exhaustive-match-return",
            (
                "def events():\n"
                "    match 1:\n"
                "        case _:\n"
                "            return ()\n"
                '    return (mo.output.append("hidden") for _ in range(1))\n'
                "values = tuple(events())\n"
                "return (events, values)"
            ),
            False,
            False,
        ),
        (
            "finally-overrides-deferred-return",
            (
                "def finally_events():\n"
                "    try:\n"
                '        return (mo.output.append("hidden") for _ in range(1))\n'
                "    finally:\n"
                "        return ()\n"
                "finally_source = finally_events()\n"
                "finally_values = tuple(finally_source)\n"
                "return (finally_events, finally_source, finally_values)"
            ),
            False,
            False,
        ),
        (
            "loop-control",
            ('for _ in range(1):\n    break\n    mo.output.append("hidden")\nreturn'),
            False,
            False,
        ),
        (
            "branch-binding",
            (
                "def run(flag):\n"
                "    def emit():\n"
                '        mo.output.append("shown")\n'
                "    def quiet():\n"
                "        return\n"
                "    if flag:\n"
                "        emit = quiet\n"
                "        return\n"
                "    emit()\n"
                "run(False)\n"
                "value = 1\n"
                "return (run, value)"
            ),
            False,
            True,
        ),
        (
            "match-binding",
            (
                "def emit():\n"
                '    mo.output.append("shown")\n'
                "match 0:\n"
                "    case 1 as emit:\n"
                "        pass\n"
                "    case _:\n"
                "        emit()\n"
                "value = 1\n"
                "return (emit, value)"
            ),
            False,
            True,
        ),
        (
            "try-handler-binding",
            (
                "def emit():\n"
                '    mo.output.append("shown")\n'
                "def quiet():\n"
                "    return\n"
                "callback = quiet\n"
                "try:\n"
                "    callback = emit\n"
                "    raise RuntimeError\n"
                "except RuntimeError:\n"
                "    callback()\n"
                "value = 1\n"
                "return (callback, emit, quiet, value)"
            ),
            False,
            True,
        ),
        (
            "finally-binding",
            (
                "def emit():\n"
                '    mo.output.append("shown")\n'
                "def run():\n"
                "    try:\n"
                "        return ()\n"
                "    finally:\n"
                "        emit()\n"
                "run()\n"
                "value = 1\n"
                "return (emit, run, value)"
            ),
            False,
            True,
        ),
        (
            "shadowed-marimo",
            (
                "class Output:\n"
                "    def append(self, value):\n"
                "        return value\n"
                "class FakeMarimo:\n"
                "    output = Output()\n"
                "def invoke(mo):\n"
                '    mo.output.append("hidden")\n'
                "invoke(FakeMarimo())\n"
                "value = 1\n"
                "return (FakeMarimo, Output, invoke, value)"
            ),
            False,
            False,
        ),
        (
            "operation-alias",
            (
                "append = mo.output.append\n"
                'append("shown")\n'
                "value = 1\n"
                "return (append, value)"
            ),
            False,
            True,
        ),
        (
            "imported-operation",
            (
                "from marimo import output\n"
                'output.append("shown")\n'
                "value = 1\n"
                "return (output, value)"
            ),
            False,
            True,
        ),
        (
            "consumed-enumerate",
            (
                'events = (mo.output.append("shown") for _ in range(1))\n'
                "values = tuple(enumerate(events))\n"
                "return (events, values)"
            ),
            False,
            True,
        ),
        (
            "consumed-map",
            'values = tuple(map(mo.output.append, ["shown"]))\nreturn (values,)',
            False,
            True,
        ),
        (
            "consumed-filter",
            'values = tuple(filter(mo.output.append, ["shown"]))\nreturn (values,)',
            False,
            True,
        ),
        (
            "consumed-zip-secondary-source",
            (
                'events = (mo.output.append("shown") for _ in range(1))\n'
                "values = tuple(zip([1], events))\n"
                "return (events, values)"
            ),
            False,
            True,
        ),
        (
            "zero-iteration-rebinding",
            (
                'events = (mo.output.append("shown") for _ in range(1))\n'
                "for _ in ():\n"
                "    events = ()\n"
                "values = tuple(events)\n"
                "return (events, values)"
            ),
            False,
            True,
        ),
        (
            "zero-iteration-while-rebinding",
            (
                'events = (mo.output.append("shown") for _ in range(1))\n'
                "while False:\n"
                "    events = ()\n"
                "values = tuple(events)\n"
                "return (events, values)"
            ),
            False,
            True,
        ),
        (
            "unawaited-async-generator",
            (
                "async def events():\n"
                '    mo.output.append("hidden")\n'
                "    yield 1\n"
                "value = anext(events())\n"
                "return (events, value)"
            ),
            False,
            False,
        ),
        (
            "shadowed-anext",
            (
                "async def shadowed_events():\n"
                '    mo.output.append("hidden")\n'
                "    yield 1\n"
                "async def anext(iterator):\n"
                "    return iterator\n"
                "shadowed_iterator = shadowed_events()\n"
                "shadowed_value = await anext(shadowed_iterator)\n"
                "return (anext, shadowed_events, shadowed_iterator, shadowed_value)"
            ),
            True,
            False,
        ),
        (
            "awaited-async-generator",
            (
                "async def events():\n"
                '    mo.output.append("shown")\n'
                "    yield 1\n"
                "value = await anext(events())\n"
                "return (events, value)"
            ),
            True,
            True,
        ),
    )

    def isolated_cell_body(
        index: int,
        name: str,
        body: str,
        async_cell: bool,
    ) -> str:
        if index < 2 or name in {
            "finally-overrides-deferred-return",
            "shadowed-anext",
        }:
            return body
        declaration = "async def" if async_cell else "def"
        await_call = "await " if async_cell else ""
        return (
            f"{declaration} case_{index}():\n"
            f"{indent(body, '    ')}\n"
            f"result_{index} = {await_call}case_{index}()\n"
            "return"
        )

    rendered_cells = "\n\n".join(
        f"@app.cell\n{'async def' if async_cell else 'def'} _(mo):\n"
        f"{indent(isolated_cell_body(index, name, body, async_cell), '    ')}"
        for index, (name, body, async_cell, _expected) in enumerate(cases)
    )
    notebook = tmp_path / "display.py"
    notebook.write_text(
        f'''\
import marimo

__generated_with = "{marimo.__version__}"
app = marimo.App()

{rendered_cells}

if __name__ == "__main__":
    app.run()
''',
        encoding="utf-8",
    )
    cells = inspect_notebook(notebook).cells
    assert len(cells) == len(cases)

    for (name, _body, _async_cell, expected), cell in zip(
        cases,
        cells,
        strict=True,
    ):
        assert cell.may_display_output is expected, name


def test_inspection_conservatively_falls_back_at_the_symbolic_budget(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    notebook = tmp_path / "small-budget.py"
    _write_single_cell_notebook(
        notebook,
        "value = 1\nreturn (value,)",
    )
    cell = _inspect_with_symbolic_budget(notebook, 1, monkeypatch)

    assert not cell.has_output_expression
    assert cell.may_display_output


def test_inspection_charges_repeated_wide_call_scopes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    notebook = tmp_path / "wide-call-scopes.py"
    unreachable = "\n".join(
        f"    unreachable_{index} = {index}" for index in range(100)
    )
    repeated_calls = "\n".join("wide_scope()" for _index in range(20))
    _write_single_cell_notebook(
        notebook,
        f"def wide_scope():\n    return\n{unreachable}\n\n"
        f"{repeated_calls}\nvalue = 1\nreturn (value,)",
    )
    cell = _inspect_with_symbolic_budget(notebook, 1_500, monkeypatch)

    assert cell.may_display_output


def test_inspection_charges_scope_copies_before_branch_allocation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    notebook = tmp_path / "wide-match.py"
    bindings = "\n".join(f"bound_{index} = {index}" for index in range(30))
    cases = "\n".join(f"    case {index}:\n        pass" for index in range(20))
    _write_single_cell_notebook(
        notebook,
        f"{bindings}\nmatch 0:\n{cases}\n    case _:\n        pass\n"
        "value = 1\nreturn (value,)",
    )
    cell = _inspect_with_symbolic_budget(notebook, 500, monkeypatch)

    assert cell.may_display_output


def test_inspection_charges_repeated_alternative_scans(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    notebook = tmp_path / "callback-alternatives.py"
    callbacks = "\n\n".join(
        f"def alternative_{index}():\n    return" for index in range(16)
    )
    cases = "\n".join(
        f"    case {index}:\n        selected_callback = alternative_{index}"
        for index in range(15)
    )
    repeated_calls = "\n".join("selected_callback()" for _index in range(20))
    _write_single_cell_notebook(
        notebook,
        f"{callbacks}\n\nmatch 0:\n{cases}\n    case _:\n"
        f"        selected_callback = alternative_15\n{repeated_calls}\n"
        "value = 1\nreturn (value,)",
    )
    cell = _inspect_with_symbolic_budget(notebook, 1_500, monkeypatch)

    assert cell.may_display_output


def test_inspection_charges_deep_scope_lookups(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    notebook = tmp_path / "deep-scope-lookups.py"
    unresolved_calls = "\n".join("    unresolved_name()" for _index in range(20))
    functions = [f"def depth_0():\n{unresolved_calls}"]
    for depth in range(1, 21):
        functions.append(f"def depth_{depth}():\n    depth_{depth - 1}()")
    _write_single_cell_notebook(
        notebook,
        "\n\n".join(functions) + "\n\ndepth_20()\nvalue = 1\nreturn (value,)",
    )
    cell = _inspect_with_symbolic_budget(notebook, 1_000, monkeypatch)

    assert cell.may_display_output


def test_inspection_charges_control_flow_summaries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    notebook = tmp_path / "control-flow-summaries.py"
    control_flow = "return"
    for _depth in range(60):
        control_flow = f"if True:\n{indent(control_flow, '    ')}"
    repeated_calls = "\n".join("control_chain()" for _index in range(20))
    _write_single_cell_notebook(
        notebook,
        f"def control_chain():\n{indent(control_flow, '    ')}\n\n"
        f"{repeated_calls}\nvalue = 1\nreturn (value,)",
    )
    cell = _inspect_with_symbolic_budget(notebook, 1_000, monkeypatch)

    assert cell.may_display_output


def test_inspection_charges_cross_scope_try_collectors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    notebook = tmp_path / "cross-scope-try-collectors.py"
    deepest_statements = "\n".join(
        f"    deepest_{index} = {index}" for index in range(50)
    )
    functions = [f"def try_depth_0():\n{deepest_statements}"]
    for depth in range(1, 16):
        functions.append(
            f"def try_depth_{depth}():\n"
            "    try:\n"
            f"        try_depth_{depth - 1}()\n"
            "    finally:\n"
            "        pass"
        )
    _write_single_cell_notebook(
        notebook,
        "\n\n".join(functions) + "\n\ntry_depth_15()\nvalue = 1\nreturn (value,)",
    )
    cell = _inspect_with_symbolic_budget(notebook, 1_500, monkeypatch)

    assert cell.may_display_output


def test_inspection_stops_after_a_wide_sql_output_call(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    notebook = tmp_path / "wide-visible-sql.py"
    keywords = ",\n".join(f"        keyword_{index}={index}" for index in range(50))
    repeated_calls = "\n".join("wide_visible_sql()" for _index in range(50))
    _write_single_cell_notebook(
        notebook,
        "def wide_visible_sql():\n"
        "    mo.sql(\n"
        '        "SELECT 1",\n'
        f"{keywords},\n"
        "    )\n\n"
        f"{repeated_calls}\nvalue = 1\nreturn (value,)",
    )
    cell = _inspect_with_symbolic_budget(notebook, 1_000, monkeypatch)

    assert cell.may_display_output


def test_inspection_charges_wide_deferred_adapters(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    notebook = tmp_path / "wide-deferred-adapter.py"
    sources = ", ".join("[1]" for _index in range(50))
    repeated_consumers = "\n".join("tuple(wide_map)" for _index in range(20))
    _write_single_cell_notebook(
        notebook,
        "def quiet_map_callback(*values):\n"
        "    return values\n\n"
        f"wide_map = map(quiet_map_callback, {sources})\n"
        f"{repeated_consumers}\nvalue = 1\n"
        "return (quiet_map_callback, value, wide_map)",
    )
    cell = _inspect_with_symbolic_budget(notebook, 1_000, monkeypatch)

    assert cell.may_display_output


def test_inspection_bounds_branching_symbolic_calls(tmp_path: Path) -> None:
    notebook = tmp_path / "branching-calls.py"
    unreachable = "\n".join(
        f"    unreachable_{index} = {index}" for index in range(500)
    )
    functions = [f"def level_0():\n    return\n{unreachable}"]
    for level in range(1, 11):
        functions.append(
            f"def level_{level}():\n    level_{level - 1}()\n    level_{level - 1}()"
        )
    _write_single_cell_notebook(
        notebook,
        "\n\n".join(functions) + "\n\nlevel_10()\nvalue = 1\nreturn (value,)",
    )

    started = monotonic()
    cell = inspect_notebook(notebook).cells[0]
    elapsed = monotonic() - started

    assert elapsed < 5
    assert cell.may_display_output


def test_inspection_bounds_retained_try_scopes(tmp_path: Path) -> None:
    notebook = tmp_path / "try-scopes.py"
    assignments = "\n".join(f"    value_{index} = {index}" for index in range(500))
    _write_single_cell_notebook(
        notebook,
        f"try:\n{assignments}\nfinally:\n    pass\nvalue = 1\nreturn (value,)",
    )

    started = monotonic()
    cell = inspect_notebook(notebook).cells[0]
    elapsed = monotonic() - started

    assert elapsed < 5
    assert cell.may_display_output


def test_notebook_revision_tracks_provider_visible_source_locations(
    notebook_path: Path,
) -> None:
    original = inspect_notebook(notebook_path, include_code=True)
    notebook_path.write_text(
        "# Project metadata changed.\n" + notebook_path.read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    updated = inspect_notebook(notebook_path, include_code=True)

    assert updated.revision != original.revision
    assert updated.cells[0].source.start_line == original.cells[0].source.start_line + 1


def test_inspection_selects_output_expression_cells_before_applying_the_limit(
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


def test_runtime_inspection_rejects_an_aba_change_during_execution(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def probe(path: Path, **_options: object) -> object:
        source = path.read_text(encoding="utf-8")
        path.write_text(source + "\n# transient change\n", encoding="utf-8")
        path.write_text(source, encoding="utf-8")
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
