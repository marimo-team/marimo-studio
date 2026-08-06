from __future__ import annotations

import asyncio
import math
from pathlib import Path
from typing import cast

import marimo
import pytest

import marimo_studio._compat.kernel_values.kernel as kernel_values_module
import marimo_studio._compat.runtime_probe as runtime_probe_module
from marimo_studio._compat.kernel_values import (
    ValueReadUnavailable,
    read_session_values,
)
from marimo_studio._compat.kernel_values.kernel import _KernelValueLifespan
from marimo_studio._compat.kernel_values.selectors import _read_values
from marimo_studio._compat.kernel_values.session import _FunctionResultWaiter
from marimo_studio._compat.notebook import load_static_notebook
from marimo_studio._compat.runtime_probe import probe_runtime
from marimo_studio._compat.version import assert_supported_version
from marimo_studio.errors import ProtocolError
from marimo_studio.types import ValuePathStep
from marimo_studio.values import (
    parse_value_reference,
    resolve_value_reference,
)


def test_value_reference_preserves_attribute_and_item_selection() -> None:
    reference = parse_value_reference('portfolio.rows[0]["market.value"].formatted')

    assert reference.source == 'portfolio.rows[0]["market.value"].formatted'
    assert reference.variable == "portfolio"
    assert reference.path == (
        ValuePathStep("attribute", "rows"),
        ValuePathStep("item", 0),
        ValuePathStep("item", "market.value"),
        ValuePathStep("attribute", "formatted"),
    )


def test_dot_selection_prefers_mapping_keys_then_uses_attributes() -> None:
    class Report:
        label = "attribute"

    mapping = {"label": "mapping", "report": Report()}

    assert (
        resolve_value_reference(
            {"context": mapping},
            parse_value_reference("context.label"),
        )
        == "mapping"
    )
    assert (
        resolve_value_reference(
            {"context": mapping},
            parse_value_reference("context.report.label"),
        )
        == "attribute"
    )


def test_value_reference_rejects_python_expressions() -> None:
    for source in (
        "",
        "context.get('date')",
        "context['date']",
        "context[1:2]",
        "context[01]",
    ):
        with pytest.raises(ValueError):
            parse_value_reference(source)


def test_kernel_projection_returns_exact_json_leaves_and_local_errors() -> None:
    namespace = {
        "context": {
            "label": "July 29, 2026",
            "rows": [{"ticker": "HTMX"}],
        },
        "infinite": math.inf,
        "opaque": object(),
    }
    selectors = (
        "context.label",
        "context.rows[0].ticker",
        "context.missing",
        "infinite",
        "opaque",
        "absent",
        "unlisted",
    )

    result = _read_values(
        namespace,
        selectors,
        set(selectors).difference({"unlisted"}),
        max_value_bytes=1_000,
    )

    assert result.values == {
        "context.label": "July 29, 2026",
        "context.rows[0].ticker": "HTMX",
    }
    errors = cast(dict[str, object], result.to_dict()["errors"])
    assert cast(dict[str, str], errors["context.missing"])["code"] == (
        "value-path-unavailable"
    )
    assert cast(dict[str, str], errors["infinite"])["code"] == ("not-json-serializable")
    assert cast(dict[str, str], errors["opaque"])["code"] == ("not-json-serializable")
    assert cast(dict[str, str], errors["absent"])["code"] == "missing-variable"
    assert cast(dict[str, str], errors["unlisted"])["code"] == "unknown-selector"


def test_kernel_projection_bounds_each_selected_leaf() -> None:
    result = _read_values(
        {"context": {"small": {"count": 3}, "large": "x" * 100}},
        ("context.small", "context.large"),
        {"context.small", "context.large"},
        max_value_bytes=32,
    )

    assert result.values == {"context.small": {"count": 3}}
    assert result.errors["context.large"].code == "value-too-large"


def test_kernel_projection_bounds_the_aggregate_response() -> None:
    result = _read_values(
        {"context": {"first": "x" * 400, "second": "y" * 700}},
        ("context.first", "context.second"),
        {"context.first", "context.second"},
        max_value_bytes=800,
        max_response_bytes=1_000,
    )

    assert result.values == {"context.first": "x" * 400}
    assert result.errors["context.second"].code == "response-too-large"


def test_kernel_lifespan_registers_before_the_first_view_exists(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from marimo._runtime import context as runtime_context
    from marimo._runtime.context import kernel_context as kernel_context_module

    notebook = tmp_path / "notebook.py"
    notebook.write_text("import marimo\n", encoding="utf-8")
    tmp_path.joinpath("pyproject.toml").write_text(
        """\
[tool.marimo-studio]
notebook = "notebook.py"
default = "dashboard"
""",
        encoding="utf-8",
    )

    class Registry:
        def __init__(self) -> None:
            self.registered: list[str] = []
            self.deleted: list[str] = []

        def register(self, namespace: str, _: object) -> None:
            self.registered.append(namespace)

        def delete(self, namespace: str) -> None:
            self.deleted.append(namespace)

    class Context:
        filename = str(notebook)
        function_registry = Registry()
        query_params = object()
        _kernel = object()

    context = Context()
    monkeypatch.setattr(runtime_context, "get_context", lambda: context)
    monkeypatch.setattr(kernel_context_module, "KernelRuntimeContext", Context)
    monkeypatch.setattr(
        kernel_values_module,
        "keep_cached_cells_compatible",
        lambda: lambda: None,
    )

    async def exercise() -> None:
        async with _KernelValueLifespan():
            assert context.function_registry.registered == [
                "_marimo_studio",
                "_marimo_studio",
            ]

    asyncio.run(exercise())

    assert context.function_registry.deleted == ["_marimo_studio"]


def test_kernel_value_read_rejects_a_viewer_before_dispatch() -> None:
    from marimo._messaging.notification import ConsumerCapabilities
    from marimo._types.ids import ConsumerId

    consumer = object()

    class ViewerRoom:
        @staticmethod
        def get_consumer(consumer_id: ConsumerId) -> object | None:
            return consumer if consumer_id == ConsumerId("viewer") else None

        @staticmethod
        def get_capabilities(current: object) -> ConsumerCapabilities:
            assert current is consumer
            return ConsumerCapabilities.VIEWER

    class ViewerSession:
        room = ViewerRoom()

        @staticmethod
        def put_control_request(*_: object, **__: object) -> None:
            raise AssertionError("viewer request reached the kernel queue")

    with pytest.raises(ValueReadUnavailable) as raised:
        asyncio.run(
            read_session_values(
                ViewerSession(),
                ("context.good",),
                consumer_id="viewer",
            )
        )

    assert raised.value.code == "interaction-forbidden"
    assert raised.value.status_code == 403


def test_runtime_probe_reads_values_through_the_native_kernel_queue(
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


def test_runtime_probe_preserves_session_creation_failures(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FailingManager:
        shutdown_called = False

        @staticmethod
        def create_session(*_: object, **__: object) -> object:
            raise RuntimeError("session startup failed")

        def shutdown(self) -> None:
            self.shutdown_called = True

    manager = FailingManager()
    monkeypatch.setattr(
        runtime_probe_module,
        "_build_manager",
        lambda *_args, **_kwargs: manager,
    )

    with pytest.raises(RuntimeError, match="session startup failed"):
        asyncio.run(
            probe_runtime(
                notebook_path,
                cell_ids=(),
                variables=(),
            )
        )

    assert manager.shutdown_called


def test_runtime_rejects_marimo_below_the_supported_lower_bound(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(marimo, "__version__", "0.23.15")

    with pytest.raises(ProtocolError, match=r"Install marimo>=0\.23\.16"):
        assert_supported_version()


def test_value_waiter_surfaces_an_invalid_kernel_response() -> None:
    from marimo._messaging.notification import (
        FunctionCallResultNotification,
        HumanReadableStatus,
    )
    from marimo._messaging.serde import serialize_kernel_message
    from marimo._types.ids import RequestId

    async def receive() -> None:
        loop = asyncio.get_running_loop()
        waiter = _FunctionResultWaiter("call", loop)
        waiter.on_notification_sent(
            None,
            serialize_kernel_message(
                FunctionCallResultNotification(
                    function_call_id=RequestId("call"),
                    return_value={"values": []},
                    status=HumanReadableStatus(code="ok"),
                    found=True,
                )
            ),
        )
        with pytest.raises(ValueReadUnavailable) as raised:
            await waiter.future
        assert raised.value.code == "invalid-value-response"

    asyncio.run(receive())
