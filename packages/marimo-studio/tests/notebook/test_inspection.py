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
    notebook = tmp_path / "display.py"
    notebook.write_text(
        f'''\
import marimo

__generated_with = "{marimo.__version__}"
app = marimo.App()

@app.cell
def _(mo):
    shown = mo.md("shown")
    shown
    return

@app.cell
def _(mo):
    hidden = mo.md("hidden")
    hidden;
    return

@app.cell
def _(mo):
    result = mo.sql("SELECT 1")
    return (result,)

@app.cell
def _(mo):
    quiet = mo.sql("SELECT 1", output=False)
    return (quiet,)

@app.cell
def _(duckdb):
    relation = duckdb.sql("SELECT 1")
    return (relation,)

@app.cell
def _(duckdb):
    cursor = duckdb.execute("SELECT 1")
    return (cursor,)

@app.cell
def _(mo):
    keyword_query = mo.sql(query="SELECT 1")
    return (keyword_query,)

@app.cell
def _(mo):
    if True:
        mo.output.append("shown")
    return

@app.cell
def _(mo):
    def unused():
        mo.sql(query="SELECT 1")
        mo.output.replace("hidden")
    return (unused,)

@app.cell
def _(mo):
    def emit():
        mo.output.append("shown")
    emit()
    value = 1
    return (value,)

@app.cell
def _(mo):
    events = (mo.output.append(str(i)) for i in range(3))
    return (events,)

@app.cell
def _(mo):
    def shadowed_emit():
        mo.output.append("hidden")
    def invoke(shadowed_emit):
        shadowed_emit()
    invoke(lambda: None)
    shadowed_value = 1
    return (shadowed_value,)

@app.cell
def _(mo):
    for consumed_index in (mo.output.append(str(i)) for i in range(1)):
        pass
    consumed_value = 1
    return (consumed_index, consumed_value)

@app.cell
def _(mo):
    stored_events = (mo.output.append(str(i)) for i in range(1))
    stored_values = tuple(stored_events)
    return (stored_events, stored_values)

@app.cell
def _(mo):
    def generate_events():
        for i in range(1):
            yield mo.output.append(str(i))
    generated_events = generate_events()
    generated_values = tuple(generated_events)
    return (generate_events, generated_events, generated_values)

@app.cell
def _(mo):
    def captured_emit():
        mo.output.append("shown")
        yield 1
    def captured_quiet():
        yield 1
    captured_source = captured_emit()
    captured_events = (value for value in captured_source)
    captured_source = captured_quiet()
    captured_values = tuple(captured_events)
    return (
        captured_emit,
        captured_events,
        captured_quiet,
        captured_source,
        captured_values,
    )

@app.cell
def _(mo):
    next_events = (mo.output.append("shown") for _ in range(1))
    next_value = next(next_events)
    return (next_events, next_value)

@app.cell
def _(mo):
    iter_events = (mo.output.append("shown") for _ in range(1))
    iter_iterator = iter(iter_events)
    iter_value = next(iter_iterator)
    return (iter_events, iter_iterator, iter_value)

@app.cell
def _(mo):
    def default_emit():
        mo.output.append("shown")
    def invoke_default(callback=default_emit):
        callback()
    invoke_default()
    default_value = 1
    return (default_emit, default_value, invoke_default)

@app.cell
def _(mo):
    def captured_default_emit():
        mo.output.append("shown")
    def captured_default_quiet():
        return
    def invoke_captured_default(callback=captured_default_emit):
        callback()
    captured_default_emit = captured_default_quiet
    invoke_captured_default()
    captured_default_value = 1
    return (
        captured_default_emit,
        captured_default_quiet,
        captured_default_value,
        invoke_captured_default,
    )

@app.cell
def _(mo):
    (lambda: mo.output.append("shown"))()
    invoked_lambda_value = 1
    return (invoked_lambda_value,)

@app.cell
def _(mo):
    lazy_lambda_events = (
        lambda: (mo.output.append("hidden") for _ in range(1))
    )()
    lazy_lambda_value = 1
    return (lazy_lambda_events, lazy_lambda_value)

@app.cell
def _(mo):
    consumed_lambda_events = (
        lambda: (mo.output.append("shown") for _ in range(1))
    )()
    consumed_lambda_values = tuple(consumed_lambda_events)
    return (consumed_lambda_events, consumed_lambda_values)

@app.cell
def _(mo):
    def make_lazy_events():
        return (mo.output.append("hidden") for _ in range(1))
    named_lazy_events = make_lazy_events()
    return (make_lazy_events, named_lazy_events)

@app.cell
def _(mo):
    def make_consumed_events():
        return (mo.output.append("shown") for _ in range(1))
    named_consumed_events = make_consumed_events()
    named_consumed_values = tuple(named_consumed_events)
    return (make_consumed_events, named_consumed_events, named_consumed_values)

@app.cell
def _(mo):
    def make_unreachable_events():
        return ()
        return (mo.output.append("hidden") for _ in range(1))
    unreachable_events = make_unreachable_events()
    unreachable_values = tuple(unreachable_events)
    return (make_unreachable_events, unreachable_events, unreachable_values)

@app.cell
def _(mo):
    def make_try_events():
        try:
            return ()
            return (mo.output.append("hidden") for _ in range(1))
        finally:
            pass
    try_events = make_try_events()
    try_values = tuple(try_events)
    return (make_try_events, try_events, try_values)

@app.cell
def _(mo):
    def make_try_else_events():
        try:
            return ()
        except Exception:
            return ()
        else:
            return (mo.output.append("hidden") for _ in range(1))
    try_else_events = make_try_else_events()
    try_else_values = tuple(try_else_events)
    return (make_try_else_events, try_else_events, try_else_values)

@app.cell
def _(mo):
    def make_post_try_events():
        try:
            return ()
        finally:
            pass
        return (mo.output.append("hidden") for _ in range(1))
    post_try_events = make_post_try_events()
    post_try_values = tuple(post_try_events)
    return (make_post_try_events, post_try_events, post_try_values)

@app.cell
def _(mo):
    def make_overridden_try_events():
        try:
            return (mo.output.append("hidden") for _ in range(1))
        finally:
            return ()
    overridden_try_events = make_overridden_try_events()
    overridden_try_values = tuple(overridden_try_events)
    return (make_overridden_try_events, overridden_try_events, overridden_try_values)

@app.cell
def _(mo):
    for break_index in range(1):
        break
        mo.output.append("hidden")
    for continue_index in range(1):
        continue
        mo.output.append("hidden")
    loop_control_value = 1
    return (break_index, continue_index, loop_control_value)

@app.cell
def _(mo):
    for try_break_index in range(1):
        try:
            break
        finally:
            pass
        mo.output.append("hidden")
    for try_continue_index in range(1):
        try:
            continue
        finally:
            pass
        mo.output.append("hidden")
    try_loop_control_value = 1
    return (try_break_index, try_continue_index, try_loop_control_value)

@app.cell
def _(mo):
    def make_match_events():
        match 1:
            case _:
                return ()
        return (mo.output.append("hidden") for _ in range(1))
    match_events = make_match_events()
    match_values = tuple(match_events)
    return (make_match_events, match_events, match_values)

@app.cell
def _(mo):
    for match_break_index in range(1):
        match 1:
            case _:
                break
        mo.output.append("hidden")
    for match_continue_index in range(1):
        match 1:
            case _:
                continue
        mo.output.append("hidden")
    match_loop_control_value = 1
    return (match_break_index, match_continue_index, match_loop_control_value)

@app.cell
def _(mo):
    def match_emit():
        mo.output.append("shown")
    match 0:
        case 1 as match_emit:
            pass
        case _:
            match_emit()
    match_scope_value = 1
    return (match_emit, match_scope_value)

@app.cell
def _(mo):
    def run_branch(flag):
        def branch_emit():
            mo.output.append("shown")
        def branch_quiet():
            return
        if flag:
            branch_emit = branch_quiet
            return
        branch_emit()
    run_branch(False)
    branch_scope_value = 1
    return (branch_scope_value, run_branch)

@app.cell
def _(mo):
    def consume_if_events(flag):
        if flag:
            if_events = (mo.output.append("shown-a") for _ in range(1))
        else:
            if_events = (mo.output.append("shown-b") for _ in range(1))
        return tuple(if_events)
    if_event_values = consume_if_events(True)
    return (consume_if_events, if_event_values)

@app.cell
def _(mo):
    def consume_match_events(flag):
        match flag:
            case 0:
                matched_events = (mo.output.append("shown-a") for _ in range(1))
            case _:
                matched_events = (mo.output.append("shown-b") for _ in range(1))
        return tuple(matched_events)
    matched_event_values = consume_match_events(0)
    return (consume_match_events, matched_event_values)

@app.cell
def _(mo):
    def consume_mixed_if_events(flag):
        if flag:
            mixed_if_events = (mo.output.append("shown") for _ in range(1))
        else:
            mixed_if_events = ()
        return tuple(mixed_if_events)
    mixed_if_values = consume_mixed_if_events(True)
    return (consume_mixed_if_events, mixed_if_values)

@app.cell
def _(mo):
    def consume_partial_match_events(flag):
        match flag:
            case 0:
                partial_match_events = (
                    mo.output.append("shown") for _ in range(1)
                )
        return tuple(partial_match_events)
    partial_match_values = consume_partial_match_events(0)
    return (consume_partial_match_events, partial_match_values)

@app.cell
def _(mo):
    zero_for_events = (mo.output.append("shown") for _ in range(1))
    for _ in ():
        zero_for_events = ()
    zero_for_values = tuple(zero_for_events)
    return (zero_for_events, zero_for_values)

@app.cell
def _(mo):
    zero_while_events = (mo.output.append("shown") for _ in range(1))
    while False:
        zero_while_events = ()
    zero_while_values = tuple(zero_while_events)
    return (zero_while_events, zero_while_values)

@app.cell
def _(mo):
    def try_scope_emit():
        mo.output.append("shown")
    def try_scope_quiet():
        return
    try:
        pass
    except Exception:
        try_scope_emit = try_scope_quiet
    try_scope_emit()
    try_scope_value = 1
    return (try_scope_emit, try_scope_quiet, try_scope_value)

@app.cell
def _(mo):
    def finally_emit():
        mo.output.append("shown")
    def run_finally_binding():
        try:
            finally_callback = finally_emit
            return ()
        finally:
            finally_callback()
    run_finally_binding()
    finally_binding_value = 1
    return (finally_binding_value, finally_emit, run_finally_binding)

@app.cell
def _(mo):
    def handler_snapshot_emit():
        mo.output.append("shown")
    def handler_snapshot_quiet():
        return
    def handler_snapshot_fail():
        raise RuntimeError
    def run_handler_snapshot():
        handler_snapshot_callback = handler_snapshot_quiet
        try:
            handler_snapshot_callback = handler_snapshot_emit
            handler_snapshot_fail()
            handler_snapshot_callback = handler_snapshot_quiet
        except RuntimeError:
            handler_snapshot_callback()
    run_handler_snapshot()
    handler_snapshot_value = 1
    return (
        handler_snapshot_emit,
        handler_snapshot_fail,
        handler_snapshot_quiet,
        handler_snapshot_value,
        run_handler_snapshot,
    )

@app.cell
def _(mo):
    def nested_handler_emit():
        mo.output.append("shown")
    def nested_handler_quiet():
        return
    def nested_handler_fail():
        raise RuntimeError
    def run_nested_handler():
        nested_handler_callback = nested_handler_quiet
        try:
            if True:
                nested_handler_callback = nested_handler_emit
                nested_handler_fail()
                nested_handler_callback = nested_handler_quiet
        except RuntimeError:
            nested_handler_callback()
    run_nested_handler()
    nested_handler_value = 1
    return (
        nested_handler_emit,
        nested_handler_fail,
        nested_handler_quiet,
        nested_handler_value,
        run_nested_handler,
    )

@app.cell
def _(mo):
    class FakeOutput:
        @staticmethod
        def append(value):
            return value
    class FakeMarimo:
        output = FakeOutput()
    def invoke_fake(mo):
        mo.output.append("hidden")
    invoke_fake(FakeMarimo())
    fake_marimo_value = 1
    return (FakeMarimo, FakeOutput, fake_marimo_value, invoke_fake)

@app.cell
def _(mo):
    def invoke_real(real_marimo):
        real_marimo.output.append("shown")
    invoke_real(mo)
    real_marimo_value = 1
    return (invoke_real, real_marimo_value)

@app.cell
def _(mo):
    append_alias = mo.output.append
    append_alias("shown")
    append_alias_value = 1
    return (append_alias, append_alias_value)

@app.cell
def _(mo):
    sql_alias = mo.sql
    sql_alias_result = sql_alias("SELECT 1")
    return (sql_alias, sql_alias_result)

@app.cell
def _(mo):
    quiet_sql_alias = mo.sql
    quiet_sql_result = quiet_sql_alias("SELECT 1", output=False)
    return (quiet_sql_alias, quiet_sql_result)

@app.cell
def _(mo):
    append_namespace = mo.output
    append_namespace.append("shown")
    append_namespace_value = 1
    return (append_namespace, append_namespace_value)

@app.cell
def _(mo):
    replace_namespace = mo.output
    replace_namespace.replace("shown")
    replace_namespace_value = 1
    return (replace_namespace, replace_namespace_value)

@app.cell
def _(mo):
    indexed_namespace = mo.output
    indexed_namespace.replace_at_index("shown", 0)
    indexed_namespace_value = 1
    return (indexed_namespace, indexed_namespace_value)

@app.cell
def _(mo):
    from marimo import output
    output.append("shown")
    direct_output_value = 1
    return (direct_output_value, output)

@app.cell
def _(mo):
    from marimo import sql
    direct_sql_result = sql("SELECT 1")
    return (direct_sql_result, sql)

@app.cell
def _(mo):
    from marimo import output as imported_output
    imported_output.append("shown")
    imported_output_value = 1
    return (imported_output, imported_output_value)

@app.cell
def _(mo):
    from marimo import sql as imported_sql
    imported_sql_result = imported_sql("SELECT 1")
    return (imported_sql, imported_sql_result)

@app.cell
async def _(mo):
    async def awaited_events():
        mo.output.append("shown")
        yield 1
    awaited_iterator = awaited_events()
    awaited_value = await anext(awaited_iterator)
    return (awaited_events, awaited_iterator, awaited_value)

@app.cell
def _(mo):
    async def unawaited_events():
        mo.output.append("hidden")
        yield 1
    unawaited_iterator = unawaited_events()
    unawaited_value = anext(unawaited_iterator)
    return (unawaited_events, unawaited_iterator, unawaited_value)

@app.cell
async def _(mo):
    async def shadowed_anext_events():
        mo.output.append("hidden")
        yield 1
    async def anext(iterator):
        return iterator
    shadowed_anext_iterator = shadowed_anext_events()
    shadowed_anext_value = await anext(shadowed_anext_iterator)
    return (
        anext,
        shadowed_anext_events,
        shadowed_anext_iterator,
        shadowed_anext_value,
    )

@app.cell
def _(mo):
    enumerated_events = (mo.output.append("shown") for _ in range(1))
    stored_enumerate = enumerate(enumerated_events)
    stored_enumerate_values = tuple(stored_enumerate)
    return (enumerated_events, stored_enumerate, stored_enumerate_values)

@app.cell
def _(mo):
    inline_enumerate_values = tuple(
        enumerate(mo.output.append("shown") for _ in range(1))
    )
    return (inline_enumerate_values,)

@app.cell
def _(mo):
    lazy_enumerate_events = (mo.output.append("hidden") for _ in range(1))
    lazy_enumerate = enumerate(lazy_enumerate_events, start=1)
    return (lazy_enumerate, lazy_enumerate_events)

@app.cell
def _(mo):
    stored_map = map(mo.output.append, ["shown"])
    stored_map_values = tuple(stored_map)
    return (stored_map, stored_map_values)

@app.cell
def _(mo):
    inline_map_values = tuple(map(mo.output.append, ["shown"]))
    return (inline_map_values,)

@app.cell
def _(mo):
    lazy_map = map(mo.output.append, ["hidden"])
    lazy_map_value = 1
    return (lazy_map, lazy_map_value)

@app.cell
def _(mo):
    def local_map_callback(value):
        mo.output.append(value)
    local_map = map(local_map_callback, ["shown"])
    local_map_values = tuple(local_map)
    return (local_map, local_map_callback, local_map_values)

@app.cell
def _(mo):
    stored_filter = filter(mo.output.append, ["shown"])
    stored_filter_values = tuple(stored_filter)
    return (stored_filter, stored_filter_values)

@app.cell
def _(mo):
    inline_filter_values = tuple(filter(mo.output.append, ["shown"]))
    return (inline_filter_values,)

@app.cell
def _(mo):
    lazy_filter = filter(mo.output.append, ["hidden"])
    lazy_filter_value = 1
    return (lazy_filter, lazy_filter_value)

@app.cell
def _(mo):
    none_filter_values = tuple(filter(None, [1]))
    none_filter_value = 1
    return (none_filter_value, none_filter_values)

@app.cell
def _(mo):
    def local_filter_callback(value):
        mo.output.append(value)
        return True
    local_filter = filter(local_filter_callback, ["shown"])
    local_filter_values = tuple(local_filter)
    return (local_filter, local_filter_callback, local_filter_values)

@app.cell
def _(mo):
    stored_zip_events = (mo.output.append("shown") for _ in range(1))
    stored_zip = zip(stored_zip_events, [1])
    stored_zip_values = tuple(stored_zip)
    return (stored_zip, stored_zip_events, stored_zip_values)

@app.cell
def _(mo):
    inline_zip_values = tuple(
        zip((mo.output.append("shown") for _ in range(1)), [1])
    )
    return (inline_zip_values,)

@app.cell
def _(mo):
    lazy_zip_events = (mo.output.append("hidden") for _ in range(1))
    lazy_zip = zip(lazy_zip_events, [1])
    return (lazy_zip, lazy_zip_events)

@app.cell
def _(mo):
    second_zip_events = (mo.output.append("shown") for _ in range(1))
    multi_zip_values = tuple(zip([1], second_zip_events))
    return (multi_zip_values, second_zip_events)

@app.cell
def _(mo):
    strict_zip_events = (mo.output.append("shown") for _ in range(1))
    strict_zip_values = tuple(zip(strict_zip_events, [1], strict=True))
    return (strict_zip_events, strict_zip_values)
''',
        encoding="utf-8",
    )

    cells = inspect_notebook(notebook).cells

    assert [cell.has_output_expression for cell in cells] == [True] + [False] * 77
    assert [cell.may_display_output for cell in cells] == [
        True,
        False,
        True,
        False,
        False,
        False,
        True,
        True,
        False,
        True,
        False,
        False,
        True,
        True,
        True,
        True,
        True,
        True,
        True,
        True,
        True,
        False,
        True,
        False,
        True,
        False,
        False,
        False,
        False,
        False,
        False,
        False,
        False,
        False,
        True,
        True,
        True,
        True,
        True,
        True,
        True,
        True,
        True,
        True,
        True,
        True,
        False,
        True,
        True,
        True,
        False,
        True,
        True,
        True,
        True,
        True,
        True,
        True,
        True,
        False,
        False,
        True,
        True,
        False,
        True,
        True,
        False,
        True,
        True,
        True,
        False,
        False,
        True,
        True,
        True,
        False,
        True,
        True,
    ]


def test_inspection_conservatively_falls_back_at_the_symbolic_budget(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    notebook = tmp_path / "small-budget.py"
    _write_single_cell_notebook(
        notebook,
        "value = 1\nreturn (value,)",
    )
    loader: Any = inspection_module.create_static_notebook_loader()
    monkeypatch.setitem(loader.__globals__, "_POSSIBLE_OUTPUT_WORK_BUDGET", 1)

    cell = inspect_notebook(notebook).cells[0]

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
    loader: Any = inspection_module.create_static_notebook_loader()
    monkeypatch.setitem(loader.__globals__, "_POSSIBLE_OUTPUT_WORK_BUDGET", 1_500)

    cell = inspect_notebook(notebook).cells[0]

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
    loader: Any = inspection_module.create_static_notebook_loader()
    monkeypatch.setitem(loader.__globals__, "_POSSIBLE_OUTPUT_WORK_BUDGET", 500)

    cell = inspect_notebook(notebook).cells[0]

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
    loader: Any = inspection_module.create_static_notebook_loader()
    monkeypatch.setitem(loader.__globals__, "_POSSIBLE_OUTPUT_WORK_BUDGET", 1_500)

    cell = inspect_notebook(notebook).cells[0]

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
    loader: Any = inspection_module.create_static_notebook_loader()
    monkeypatch.setitem(loader.__globals__, "_POSSIBLE_OUTPUT_WORK_BUDGET", 1_000)

    cell = inspect_notebook(notebook).cells[0]

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
    loader: Any = inspection_module.create_static_notebook_loader()
    monkeypatch.setitem(loader.__globals__, "_POSSIBLE_OUTPUT_WORK_BUDGET", 1_000)

    cell = inspect_notebook(notebook).cells[0]

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
    loader: Any = inspection_module.create_static_notebook_loader()
    monkeypatch.setitem(loader.__globals__, "_POSSIBLE_OUTPUT_WORK_BUDGET", 1_500)

    cell = inspect_notebook(notebook).cells[0]

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
    loader: Any = inspection_module.create_static_notebook_loader()
    monkeypatch.setitem(loader.__globals__, "_POSSIBLE_OUTPUT_WORK_BUDGET", 1_000)

    cell = inspect_notebook(notebook).cells[0]

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
    loader: Any = inspection_module.create_static_notebook_loader()
    monkeypatch.setitem(loader.__globals__, "_POSSIBLE_OUTPUT_WORK_BUDGET", 1_000)

    cell = inspect_notebook(notebook).cells[0]

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
