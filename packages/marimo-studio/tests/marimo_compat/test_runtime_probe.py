from __future__ import annotations

import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from typing import Any, cast

import marimo
import pytest

import marimo_studio._compat.kernel_values.kernel as kernel_values_module
from marimo_studio._compat.kernel_values.authorization import (
    probe_output_arguments,
    probe_value_arguments,
)
from marimo_studio._compat.kernel_values.kernel import _KernelBridgeLifespan
from marimo_studio._compat.notebook import load_static_notebook
from marimo_studio._compat.runtime_probe import probe_runtime

from .values_test_support import (
    _encoded_json,
    _native_output_context,
    _selector_specs,
)


def test_runtime_probe_reads_values_through_the_native_kernel_queue(
    tmp_path: Path,
) -> None:
    import sys

    main_module = sys.modules["__main__"]
    notebook = tmp_path / "runtime.py"
    notebook.write_text(
        """\
import marimo

__generated_with = "__MARIMO_VERSION__"
app = marimo.App()


@app.cell
def _():
    print("side effect")
    context = {"count": 3, "unused": object()}
    return (context,)


if __name__ == "__main__":
    app.run()
""".replace("__MARIMO_VERSION__", marimo.__version__),
        encoding="utf-8",
    )
    cell = load_static_notebook(notebook).cells[0]

    result = asyncio.run(
        probe_runtime(
            notebook,
            cell_ids=(cell.runtime_id,),
            variables=("context.count",),
            timeout=10,
        )
    )

    assert result.cells[cell.runtime_id].status == "idle"
    assert result.cells[cell.runtime_id].outputs
    assert result.values.values == {"context.count": 3}
    assert sys.modules["__main__"] is main_module


def test_probe_selector_leases_isolate_and_restore_concurrent_same_path_kernels(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from marimo._messaging.types import NoopStream
    from marimo._runtime.functions import Function
    from marimo._runtime.params import QueryParams
    from marimo._types.ids import CellId_t

    notebook = tmp_path / "runtime.py"
    notebook.write_text("import marimo\n", encoding="utf-8")
    monkeypatch.setattr(
        kernel_values_module,
        "keep_cached_cells_compatible",
        lambda: lambda: None,
    )
    both_leased = threading.Barrier(2)
    first_released = threading.Event()

    class Kernel:
        def __init__(self) -> None:
            self.globals = {"first": 1, "second": 2}

        @contextmanager
        def lock_globals(self):
            yield

    def inspect(
        owned: str,
        foreign: str,
        query_params: dict[str, str | list[str]],
    ) -> tuple[
        dict[str, Any],
        dict[str, Any],
        dict[str, Any],
        dict[str, Any],
        dict[str, str | list[str]],
    ]:
        context = _native_output_context()
        context.filename = str(notebook)
        context._kernel = Kernel()
        context._query_params = QueryParams(query_params, NoopStream())
        lifespan = _KernelBridgeLifespan()
        try:
            with context.install():
                try:
                    lifespan._enter(context, Function, CellId_t)
                    functions = context.function_registry.namespaces[
                        "_marimo_studio"
                    ].functions
                    values = cast(
                        dict[str, Any],
                        functions["read_values"](
                            {
                                **probe_value_arguments(
                                    _selector_specs(owned), f"probe-{owned}"
                                ),
                                "max_value_bytes": 1_000,
                            }
                        ),
                    )
                    foreign_values = cast(
                        dict[str, Any],
                        functions["read_values"](
                            {
                                **probe_value_arguments(
                                    _selector_specs(foreign), f"probe-{owned}"
                                ),
                                "max_value_bytes": 1_000,
                            }
                        ),
                    )
                    outputs = cast(
                        dict[str, Any],
                        functions["render_values"](
                            {
                                **probe_output_arguments(
                                    _selector_specs(owned),
                                    _selector_specs(owned),
                                    f"probe-{owned}",
                                ),
                                "max_output_bytes": 10_000,
                            }
                        ),
                    )
                    foreign_outputs = cast(
                        dict[str, Any],
                        functions["render_values"](
                            {
                                **probe_output_arguments(
                                    _selector_specs(foreign),
                                    _selector_specs(foreign),
                                    f"probe-{owned}",
                                ),
                                "max_output_bytes": 10_000,
                            }
                        ),
                    )
                    return (
                        values,
                        outputs,
                        foreign_values,
                        foreign_outputs,
                        dict(context.query_params.to_dict()),
                    )
                finally:
                    lifespan._close()
        finally:
            context.virtual_file_registry.shutdown()

    def first_probe() -> tuple[
        dict[str, Any],
        dict[str, Any],
        dict[str, Any],
        dict[str, Any],
        dict[str, str | list[str]],
    ]:
        try:
            with kernel_values_module.probe_selector_lease(
                notebook,
                ("first",),
                ("first",),
            ) as query_params:
                both_leased.wait(timeout=10)
                return inspect("first", "second", query_params)
        finally:
            first_released.set()

    def second_probe() -> tuple[
        dict[str, Any],
        dict[str, Any],
        dict[str, Any],
        dict[str, Any],
        dict[str, str | list[str]],
    ]:
        with kernel_values_module.probe_selector_lease(
            notebook,
            ("second",),
            ("second",),
        ) as query_params:
            both_leased.wait(timeout=10)
            assert first_released.wait(timeout=10)
            return inspect("second", "first", query_params)

    with ThreadPoolExecutor(max_workers=2) as executor:
        first_future = executor.submit(first_probe)
        second_future = executor.submit(second_probe)
        first = first_future.result(timeout=15)
        second = second_future.result(timeout=15)

    for owned, _foreign, (
        values,
        outputs,
        foreign_values,
        foreign_outputs,
        query_params,
    ) in (
        ("first", "second", first),
        ("second", "first", second),
    ):
        expected = 1 if owned == "first" else 2
        assert values["values"] == {owned: _encoded_json(expected)}
        assert values["errors"] == {}
        assert cast(dict[str, Any], foreign_values["errors"])["*"]["code"] == (
            "projection-authorization-invalid"
        )
        assert set(cast(dict[str, Any], outputs["outputs"])) == {owned}
        assert outputs["errors"] == {}
        assert cast(dict[str, Any], foreign_outputs["errors"])["*"]["code"] == (
            "projection-authorization-invalid"
        )
        assert query_params == {}
    assert not kernel_values_module._PROBE_SELECTOR_LEASES


def test_runtime_probe_formats_rich_values_with_marimo(
    tmp_path: Path,
) -> None:
    notebook = tmp_path / "runtime.py"
    notebook.write_text(
        """\
import marimo

__generated_with = "__MARIMO_VERSION__"
app = marimo.App()


@app.cell
def _():
    import polars as pl
    return (pl,)


@app.cell
def _(pl):
    df = pl.DataFrame({"label": ["alpha", "beta"], "value": [1, 2]})
    return (df,)


if __name__ == "__main__":
    app.run()
""".replace("__MARIMO_VERSION__", marimo.__version__),
        encoding="utf-8",
    )

    result = asyncio.run(
        probe_runtime(
            notebook,
            cell_ids=(),
            variables=(),
            output_selectors=("df",),
            timeout=10,
        )
    )

    output = result.outputs.outputs["df"]
    assert output.mimetype == "text/html"
    assert "marimo-ui-element" in output.data


def test_runtime_probe_bounds_each_projected_output_request(tmp_path: Path) -> None:
    notebook = tmp_path / "large_outputs.py"
    notebook.write_text(
        """\
import marimo

__generated_with = "__MARIMO_VERSION__"
app = marimo.App()


@app.cell
def _():
    first = "a" * 600_000
    second = "b" * 600_000
    return first, second


if __name__ == "__main__":
    app.run()
""".replace("__MARIMO_VERSION__", marimo.__version__),
        encoding="utf-8",
    )

    result = asyncio.run(
        probe_runtime(
            notebook,
            cell_ids=(),
            variables=(),
            output_selectors=("first", "second"),
            timeout=10,
        )
    )

    assert set(result.outputs.outputs) == {"first", "second"}
    assert result.outputs.errors == {}
