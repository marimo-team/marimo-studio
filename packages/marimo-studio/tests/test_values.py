from __future__ import annotations

import asyncio
import json
import math
from contextlib import contextmanager
from pathlib import Path
from typing import Any, cast

import marimo
import pytest

import marimo_studio._compat.kernel_values.kernel as kernel_values_module
import marimo_studio._compat.runtime_probe as runtime_probe_module
from marimo_studio._compat.kernel_values import (
    ValueReadUnavailable,
    read_session_values,
    render_session_outputs,
)
from marimo_studio._compat.kernel_values.kernel import _KernelBridgeLifespan
from marimo_studio._compat.kernel_values.outputs import KernelOutputRenderer
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


class _OutputLifecycle:
    def __init__(self) -> None:
        self.disposed: list[object] = []
        self.deletions: list[bool] = []
        self.registry: dict[object, object] = {}

    def dispose(self, cell_id: object, *, deletion: bool) -> None:
        self.disposed.append(cell_id)
        self.deletions.append(deletion)


class _OutputRegistry:
    def __init__(self) -> None:
        self._constructing_cells: dict[str, object] = {}
        self._objects: dict[str, object] = {}

    @staticmethod
    def delete(*_: object) -> None:
        return


class _OutputContext:
    def __init__(self) -> None:
        self.cell_lifecycle_registry = _OutputLifecycle()
        self.ui_element_registry = _OutputRegistry()

    @contextmanager
    def with_cell_id(self, _: object):
        yield

    @contextmanager
    def provide_ui_ids(self, _: str):
        yield


def _native_output_context() -> Any:
    from marimo._ast.app import App, AppKernelRunnerRegistry, InternalApp
    from marimo._plugins.ui._core.ids import IDProvider, NoIDProviderException
    from marimo._plugins.ui._core.registry import UIElementRegistry
    from marimo._runtime.cell_lifecycle_registry import CellLifecycleRegistry
    from marimo._runtime.context.script_context import ScriptRuntimeContext
    from marimo._runtime.functions import FunctionRegistry
    from marimo._runtime.state import StateRegistry
    from marimo._runtime.virtual_file.storage import InMemoryStorage
    from marimo._runtime.virtual_file.virtual_file import VirtualFileRegistry

    app = InternalApp(App())
    context = ScriptRuntimeContext(
        _app=app,
        ui_element_registry=UIElementRegistry(),
        state_registry=StateRegistry(),
        function_registry=FunctionRegistry(),
        cell_lifecycle_registry=CellLifecycleRegistry(),
        virtual_file_registry=VirtualFileRegistry(storage=InMemoryStorage()),
        virtual_files_supported=True,
        app_kernel_runner_registry=AppKernelRunnerRegistry(),
        cache=cast(Any, None),
        stream=cast(Any, None),
        stdout=None,
        stderr=None,
        children=[],
        parent=None,
        filename=None,
        app_config=app.config,
    )
    id_provider: IDProvider | None = None

    @contextmanager
    def provide_ui_ids(prefix: str):
        nonlocal id_provider
        previous = id_provider
        id_provider = IDProvider(prefix)
        try:
            yield
        finally:
            id_provider = previous

    def take_id() -> str:
        if id_provider is None:
            raise NoIDProviderException
        return id_provider.take_id()

    mutable_context = cast(Any, context)
    mutable_context.provide_ui_ids = provide_ui_ids
    mutable_context.take_id = take_id
    return context


def _resource_element_class() -> type[Any]:
    from dataclasses import dataclass

    from marimo._plugins.ui._core.ui_element import UIElement
    from marimo._runtime.functions import Function

    @dataclass
    class PingArgs:
        pass

    class ResourceElement(UIElement[str, str]):
        def __init__(self, url: str) -> None:
            super().__init__(
                component_name="resource-element",
                initial_value="",
                label=None,
                on_change=None,
                args={"url": url},
                functions=(Function("ping", PingArgs, self._ping),),
            )

        def _ping(self, _: PingArgs) -> str:
            return "pong"

        def _convert_value(self, value: str) -> str:
            return value

    return ResourceElement


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


def test_kernel_lifespan_tolerates_code_mode_reinstantiation() -> None:
    class Lifespan:
        def __init__(self) -> None:
            self.entries = 0
            self.exits = 0

        async def __aenter__(self) -> None:
            self.entries += 1

        async def __aexit__(self, *_args: object) -> None:
            self.exits += 1

    lifecycle = Lifespan()

    class Kernel:
        _lifespan: Any = lifecycle

    class Context:
        _kernel = Kernel()

    async def exercise() -> None:
        await lifecycle.__aenter__()
        kernel_values_module._guard_entered_lifespan(Context())
        guarded = Context._kernel._lifespan
        await guarded.__aenter__()
        await guarded.__aexit__(None, None, None)

    asyncio.run(exercise())

    assert lifecycle.entries == 1
    assert lifecycle.exits == 1


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
        async with _KernelBridgeLifespan():
            assert context.function_registry.registered == [
                "_marimo_studio",
                "_marimo_studio",
                "_marimo_studio",
            ]

    asyncio.run(exercise())

    assert context.function_registry.deleted == ["_marimo_studio"]


def test_kernel_lifespan_activates_after_the_first_view_is_created(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from marimo._runtime import context as runtime_context
    from marimo._runtime.context import kernel_context as kernel_context_module

    notebook = tmp_path / "notebook.py"
    notebook.write_text("import marimo\n", encoding="utf-8")

    class Kernel:
        def __init__(self) -> None:
            self.globals = {"summary": {"papers": 3_877}}
            self.lock_count = 0

        @contextmanager
        def lock_globals(self):
            self.lock_count += 1
            yield

    cache_activations: list[bool] = []
    cache_releases: list[bool] = []

    def keep_cached_cells_compatible() -> Any:
        cache_activations.append(True)
        return lambda: cache_releases.append(True)

    current = _native_output_context()
    current.filename = str(notebook)
    current._kernel = Kernel()
    monkeypatch.setattr(runtime_context, "get_context", lambda: current)
    monkeypatch.setattr(
        kernel_context_module,
        "KernelRuntimeContext",
        type(current),
    )
    monkeypatch.setattr(
        kernel_values_module,
        "keep_cached_cells_compatible",
        keep_cached_cells_compatible,
    )

    async def exercise() -> None:
        async with _KernelBridgeLifespan():
            functions = current.function_registry.namespaces["_marimo_studio"].functions
            assert set(functions) == {
                "read_values",
                "render_values",
                "sync_query",
            }
            read = functions["read_values"]

            before = cast(
                dict[str, Any],
                read(
                    {
                        "selectors": ["summary.papers"],
                        "max_value_bytes": 1_000,
                    }
                ),
            )
            assert before["values"] == {}
            assert (
                cast(dict[str, Any], before["errors"])["summary.papers"]["code"]
                == "unknown-selector"
            )
            assert not cache_activations
            assert current._kernel.lock_count == 0

            view = tmp_path / "__marimo__" / "studio" / "notebook" / "dashboard"
            view.mkdir(parents=True)
            view.joinpath("index.html").write_text(
                '<span mo-value="summary.papers"></span>',
                encoding="utf-8",
            )
            tmp_path.joinpath("pyproject.toml").write_text(
                """\
[tool.marimo-studio]
notebook = "notebook.py"
default = "dashboard"
""",
                encoding="utf-8",
            )

            after = cast(
                dict[str, Any],
                read(
                    {
                        "selectors": ["summary.papers"],
                        "max_value_bytes": 1_000,
                    }
                ),
            )
            assert after["values"] == {"summary.papers": 3_877}
            assert cache_activations == [True]
            assert current._kernel.lock_count == 1

    try:
        with current.install():
            asyncio.run(exercise())
    finally:
        current.virtual_file_registry.shutdown()

    assert current.function_registry.namespaces == {}
    assert cache_releases == [True]


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


def test_output_timeout_is_terminal_after_one_kernel_dispatch() -> None:
    from marimo._messaging.notification import ConsumerCapabilities
    from marimo._types.ids import ConsumerId

    consumer = object()

    class Room:
        @staticmethod
        def get_consumer(consumer_id: ConsumerId) -> object | None:
            return consumer if consumer_id == ConsumerId("editor") else None

        @staticmethod
        def get_capabilities(current: object) -> ConsumerCapabilities:
            assert current is consumer
            return ConsumerCapabilities.EDITOR

    class Session:
        room = Room()
        dispatched = 0

        @staticmethod
        @contextmanager
        def scoped(_: object):
            yield

        def put_control_request(self, *_: object, **__: object) -> None:
            self.dispatched += 1

    session = Session()
    with pytest.raises(ValueReadUnavailable) as raised:
        asyncio.run(
            render_session_outputs(
                session,
                ("summary",),
                ("summary",),
                consumer_id="editor",
                timeout=0,
            )
        )

    assert session.dispatched == 1
    assert raised.value.code == "output-read-timeout"
    assert raised.value.transient is False


def test_output_consumer_detach_finishes_read_and_releases_owners() -> None:
    from marimo._messaging.notification import ConsumerCapabilities
    from marimo._runtime.commands import InvokeFunctionCommand
    from marimo._types.ids import ConsumerId

    class Consumer:
        consumer_id = ConsumerId("preview-a")

        def __init__(self) -> None:
            self.detached = False

        def on_detach(self) -> None:
            self.detached = True

    consumer = Consumer()

    class Room:
        connected = True

        def get_consumer(self, consumer_id: ConsumerId) -> object | None:
            if self.connected and consumer_id == consumer.consumer_id:
                return consumer
            return None

        @staticmethod
        def get_capabilities(current: object) -> ConsumerCapabilities:
            assert current is consumer
            return ConsumerCapabilities.EDITOR

    class Session:
        room = Room()

        def __init__(self) -> None:
            self.requests: list[tuple[object, object]] = []
            self.dispatched: asyncio.Event | None = None

        @staticmethod
        @contextmanager
        def scoped(_: object):
            yield

        def put_control_request(self, request: object, **kwargs: object) -> None:
            self.requests.append((request, kwargs.get("from_consumer_id")))
            if self.dispatched is not None:
                self.dispatched.set()

    session = Session()

    async def disconnect() -> ValueReadUnavailable:
        session.dispatched = asyncio.Event()
        read = asyncio.create_task(
            render_session_outputs(
                session,
                ("summary",),
                ("summary",),
                consumer_id=str(consumer.consumer_id),
                timeout=10,
            )
        )
        await session.dispatched.wait()
        session.room.connected = False
        consumer.on_detach()
        with pytest.raises(ValueReadUnavailable) as raised:
            await asyncio.wait_for(read, timeout=1)
        return raised.value

    error = asyncio.run(disconnect())

    assert error.code == "consumer-unavailable"
    raw_cleanup, origin = session.requests[-1]
    cleanup = cast(InvokeFunctionCommand, raw_cleanup)
    assert cleanup.args == {
        "selectors": [],
        "active_selectors": [],
        "consumer_id": "preview-a",
        "max_output_bytes": 1_000_000,
    }
    assert origin is None
    assert consumer.detached is True


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


def test_output_renderer_releases_stable_native_owners(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from marimo._output.formatting import FormattedOutput

    context = _OutputContext()
    notifications: list[object] = []
    monkeypatch.setattr(
        "marimo._output.formatting.try_format",
        lambda *_args, **_kwargs: FormattedOutput(
            "text/html", "<strong>Ready</strong>"
        ),
    )
    monkeypatch.setattr(
        "marimo._messaging.notification_utils.broadcast_notification",
        lambda notification: notifications.append(notification.cell_id),
    )
    renderer = KernelOutputRenderer(context)

    rendered = renderer.render(
        {"summary": object()},
        ("summary",),
        ("summary",),
        {"summary"},
        consumer_id="preview-a",
        max_output_bytes=1_000,
    )
    inactive = renderer.render(
        {"summary": object()},
        ("summary",),
        (),
        {"summary"},
        consumer_id="preview-a",
        max_output_bytes=1_000,
    )

    owner = context.cell_lifecycle_registry.disposed[0]
    assert str(owner).startswith("__marimo_studio_output_")
    assert rendered.outputs["summary"].owner_cell_id == str(owner)
    assert inactive.errors["summary"].code == "inactive-selector"
    assert context.cell_lifecycle_registry.disposed == [owner]
    assert context.cell_lifecycle_registry.deletions == [False]
    assert notifications == [owner]


@pytest.mark.parametrize("release", ["selector-removal", "renderer-close"])
def test_output_renderer_deletes_function_bearing_native_resources(
    monkeypatch: pytest.MonkeyPatch,
    release: str,
) -> None:
    import gc

    from marimo._output.formatting import FormattedOutput
    from marimo._runtime.virtual_file.virtual_file import (
        VirtualFileLifecycleItem,
    )

    context = _native_output_context()
    ResourceElement = _resource_element_class()

    def format_output(*_args: object, **_kwargs: object) -> FormattedOutput:
        item = VirtualFileLifecycleItem(ext="txt", buffer=b"resource")
        item.add_to_cell_lifecycle_registry()
        element = ResourceElement(item.virtual_file.url)
        return FormattedOutput("text/html", element.text)

    monkeypatch.setattr("marimo._output.formatting.try_format", format_output)
    monkeypatch.setattr(
        "marimo._messaging.notification_utils.broadcast_notification",
        lambda _notification: None,
    )
    renderer = KernelOutputRenderer(context)
    gc_was_enabled = gc.isenabled()
    gc.disable()
    try:
        with context.install():
            first = renderer.render(
                {"summary": object()},
                ("summary",),
                ("summary",),
                {"summary"},
                consumer_id="preview-a",
                max_output_bytes=10_000,
            )
            owner = next(iter(context.cell_lifecycle_registry.registry))
            filename = next(iter(context.virtual_file_registry.filenames()))
            assert first.outputs["summary"].owner_cell_id == str(owner)
            assert context.virtual_file_registry.refcount(filename) == 1

            if release == "renderer-close":
                renderer.close()
            else:
                renderer.render(
                    {"summary": object()},
                    (),
                    (),
                    {"summary"},
                    consumer_id="preview-a",
                    max_output_bytes=10_000,
                )

            assert context.cell_lifecycle_registry.registry == {}
            assert context.virtual_file_registry.registry == {}
            assert context.function_registry.namespaces == {}
    finally:
        if gc_was_enabled:
            gc.enable()
        gc.collect()
        context.virtual_file_registry.shutdown()


def test_output_renderer_preserves_cached_resources_across_consumers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import gc

    from marimo._output.hypertext import Html
    from marimo._runtime.virtual_file.virtual_file import (
        VirtualFileLifecycleItem,
        read_virtual_file,
    )

    class CachedVirtualFileOutput:
        def __init__(self) -> None:
            self.output: Html | None = None

        def _mime_(self) -> tuple[str, str]:
            if self.output is None:
                item = VirtualFileLifecycleItem(ext="txt", buffer=b"resource")
                item.add_to_cell_lifecycle_registry()
                self.output = Html(f'<a href="{item.virtual_file.url}">download</a>')
            return self.output._mime_()

    monkeypatch.setattr(
        "marimo._messaging.notification_utils.broadcast_notification",
        lambda _notification: None,
    )
    context = _native_output_context()
    renderer = KernelOutputRenderer(context)
    value = CachedVirtualFileOutput()
    try:
        with context.install():
            first = renderer.render(
                {"summary": value},
                ("summary",),
                ("summary",),
                {"summary"},
                consumer_id="preview-a",
                max_output_bytes=10_000,
            )
            filename = next(iter(context.virtual_file_registry.filenames()))
            assert filename in first.outputs["summary"].data
            assert read_virtual_file(filename, len(b"resource")) == b"resource"

            second = renderer.render(
                {"summary": value},
                ("summary",),
                ("summary",),
                {"summary"},
                consumer_id="preview-b",
                max_output_bytes=10_000,
            )
            assert filename in second.outputs["summary"].data
            assert read_virtual_file(filename, len(b"resource")) == b"resource"

            renderer.render(
                {"summary": value},
                (),
                (),
                {"summary"},
                consumer_id="preview-a",
                max_output_bytes=10_000,
            )
            refreshed = renderer.render(
                {"summary": value},
                ("summary",),
                ("summary",),
                {"summary"},
                consumer_id="preview-b",
                max_output_bytes=10_000,
            )
            assert filename in refreshed.outputs["summary"].data
            assert read_virtual_file(filename, len(b"resource")) == b"resource"

            renderer.render(
                {"summary": value},
                (),
                (),
                {"summary"},
                consumer_id="preview-b",
                max_output_bytes=10_000,
            )
            remounted = renderer.render(
                {"summary": value},
                ("summary",),
                ("summary",),
                {"summary"},
                consumer_id="preview-c",
                max_output_bytes=10_000,
            )
            assert filename in remounted.outputs["summary"].data
            assert read_virtual_file(filename, len(b"resource")) == b"resource"

            renderer.render(
                {"summary": value},
                (),
                (),
                {"summary"},
                consumer_id="preview-c",
                max_output_bytes=10_000,
            )
            value.output = None
            gc.collect()
            renderer.render(
                {},
                (),
                (),
                set(),
                consumer_id="preview-d",
                max_output_bytes=10_000,
            )
            assert context.cell_lifecycle_registry.registry == {}
            assert context.virtual_file_registry.registry == {}
    finally:
        context.virtual_file_registry.shutdown()


def test_output_renderer_preserves_cached_ui_elements_across_selectors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import gc

    from marimo._runtime.virtual_file.virtual_file import VirtualFileLifecycleItem

    ResourceElement = _resource_element_class()

    class CachedElementOutput:
        def __init__(self) -> None:
            self.element: Any | None = None

        def _mime_(self) -> tuple[str, str]:
            if self.element is None:
                item = VirtualFileLifecycleItem(ext="txt", buffer=b"resource")
                item.add_to_cell_lifecycle_registry()
                self.element = ResourceElement(item.virtual_file.url)
            return self.element._mime_()

    monkeypatch.setattr(
        "marimo._messaging.notification_utils.broadcast_notification",
        lambda _notification: None,
    )
    context = _native_output_context()
    renderer = KernelOutputRenderer(context)
    value = CachedElementOutput()
    try:
        with context.install():
            initial = renderer.render(
                {"first": value, "second": value},
                ("first", "second"),
                ("first", "second"),
                {"first", "second"},
                consumer_id="preview-a",
                max_output_bytes=10_000,
            )
            object_id = next(iter(context.ui_element_registry._objects))
            filename = next(iter(context.virtual_file_registry.filenames()))
            assert object_id in initial.outputs["first"].data
            assert object_id in initial.outputs["second"].data

            refreshed = renderer.render(
                {"first": value, "second": value},
                ("first",),
                ("first", "second"),
                {"first", "second"},
                consumer_id="preview-a",
                max_output_bytes=10_000,
            )
            assert object_id in refreshed.outputs["first"].data
            assert context.ui_element_registry.get_object(object_id) is value.element
            assert context.function_registry.get_function(object_id, "ping") is not None

            surviving = renderer.render(
                {"first": value, "second": value},
                ("second",),
                ("second",),
                {"first", "second"},
                consumer_id="preview-a",
                max_output_bytes=10_000,
            )
            assert object_id in surviving.outputs["second"].data
            assert context.virtual_file_registry.refcount(filename) == 1
            assert context.ui_element_registry.get_object(object_id) is value.element
            assert context.function_registry.get_function(object_id, "ping") is not None

            value.element = None
            gc.collect()
            renderer.render(
                {},
                (),
                (),
                set(),
                consumer_id="preview-a",
                max_output_bytes=10_000,
            )
            assert context.cell_lifecycle_registry.registry == {}
            assert context.virtual_file_registry.registry == {}
            assert context.function_registry.namespaces == {}
            assert context.ui_element_registry._objects == {}
    finally:
        value.element = None
        gc.collect()
        context.virtual_file_registry.shutdown()


def test_output_renderer_preserves_notebook_ui_owner_until_source_release(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import gc

    from marimo._types.ids import CellId_t

    monkeypatch.setattr(
        "marimo._messaging.notification_utils.broadcast_notification",
        lambda _notification: None,
    )
    ResourceElement = _resource_element_class()
    context = _native_output_context()
    renderer = KernelOutputRenderer(context)
    source: dict[str, Any] = {}
    try:
        with context.install():
            source_cell = CellId_t("source-cell")
            with context.with_cell_id(source_cell):
                source["element"] = ResourceElement("https://example.com/resource")
            object_id = next(iter(context.ui_element_registry._objects))
            context.ui_element_registry._bindings[object_id] = {"source_widget"}

            initial = renderer.render(
                source,
                ("element",),
                ("element",),
                {"element"},
                consumer_id="preview-a",
                max_output_bytes=10_000,
            )
            refreshed = renderer.render(
                source,
                ("element",),
                ("element",),
                {"element"},
                consumer_id="preview-a",
                max_output_bytes=10_000,
            )

            assert object_id in initial.outputs["element"].data
            assert object_id in refreshed.outputs["element"].data
            assert context.ui_element_registry.get_cell(object_id) == source_cell
            assert context.ui_element_registry._bindings[object_id] == {"source_widget"}
            assert context.function_registry.get_function(object_id, "ping") is not None
            with context.with_cell_id(source_cell), pytest.raises(RuntimeError):
                _ = source["element"].value

            renderer.render(
                source,
                (),
                (),
                {"element"},
                consumer_id="preview-a",
                max_output_bytes=10_000,
            )
            assert context.ui_element_registry.get_cell(object_id) == source_cell
            assert context.function_registry.get_function(object_id, "ping") is not None

            source.clear()
            gc.collect()
            renderer.render(
                {},
                (),
                (),
                set(),
                consumer_id="preview-b",
                max_output_bytes=10_000,
            )
            assert context.ui_element_registry._objects == {}
            assert context.ui_element_registry._constructing_cells == {}
            assert context.function_registry.namespaces == {}
    finally:
        source.clear()
        gc.collect()
        context.virtual_file_registry.shutdown()


def test_output_renderer_defers_creator_notification_for_shared_ui(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import gc

    ResourceElement = _resource_element_class()

    class CachedElementOutput:
        def __init__(self) -> None:
            self.element: Any | None = None

        def _mime_(self) -> tuple[str, str]:
            if self.element is None:
                self.element = ResourceElement("https://example.com/resource")
            return self.element._mime_()

    notifications: list[str] = []
    monkeypatch.setattr(
        "marimo._messaging.notification_utils.broadcast_notification",
        lambda notification: notifications.append(str(notification.cell_id)),
    )
    context = _native_output_context()
    renderer = KernelOutputRenderer(context)
    value = CachedElementOutput()
    try:
        with context.install():
            initial = renderer.render(
                {"first": value, "second": value},
                ("first", "second"),
                ("first", "second"),
                {"first", "second"},
                consumer_id="preview-a",
                max_output_bytes=10_000,
            )
            object_id = next(iter(context.ui_element_registry._objects))
            first_owner = initial.outputs["first"].owner_cell_id
            second_owner = initial.outputs["second"].owner_cell_id
            assert str(context.ui_element_registry.get_cell(object_id)) == first_owner

            refreshed = renderer.render(
                {"first": value, "second": value},
                ("second",),
                ("second",),
                {"first", "second"},
                consumer_id="preview-a",
                max_output_bytes=10_000,
            )
            assert object_id in refreshed.outputs["second"].data
            assert refreshed.outputs["second"].reset_ui_object_ids == ()
            assert first_owner not in notifications
            assert context.function_registry.get_function(object_id, "ping") is not None

            renderer.render(
                {"first": value, "second": value},
                (),
                (),
                {"first", "second"},
                consumer_id="preview-a",
                max_output_bytes=10_000,
            )
            assert notifications == [second_owner]

            value.element = None
            gc.collect()
            renderer.render(
                {},
                (),
                (),
                set(),
                consumer_id="preview-b",
                max_output_bytes=10_000,
            )
            assert set(notifications) == {first_owner, second_owner}
    finally:
        value.element = None
        gc.collect()
        with context.install():
            renderer.render(
                {},
                (),
                (),
                set(),
                consumer_id="preview-b",
                max_output_bytes=10_000,
            )
        context.virtual_file_registry.shutdown()


def test_output_renderer_resets_a_fresh_ui_element_reusing_the_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import gc
    import weakref

    from marimo._output.formatting import FormattedOutput

    ResourceElement = _resource_element_class()
    created: list[weakref.ReferenceType[Any]] = []

    def format_output(*_args: object, **_kwargs: object) -> FormattedOutput:
        element = ResourceElement(f"https://example.com/{len(created)}")
        created.append(weakref.ref(element))
        return FormattedOutput("text/html", element.text)

    notifications: list[str] = []
    monkeypatch.setattr("marimo._output.formatting.try_format", format_output)
    monkeypatch.setattr(
        "marimo._messaging.notification_utils.broadcast_notification",
        lambda notification: notifications.append(str(notification.cell_id)),
    )
    context = _native_output_context()
    renderer = KernelOutputRenderer(context)
    try:
        with context.install():
            first = renderer.render(
                {"control": object()},
                ("control",),
                ("control",),
                {"control"},
                consumer_id="preview-a",
                max_output_bytes=10_000,
            )
            object_id = next(iter(context.ui_element_registry._objects))
            second = renderer.render(
                {"control": object()},
                ("control",),
                ("control",),
                {"control"},
                consumer_id="preview-a",
                max_output_bytes=10_000,
            )

            owner = first.outputs["control"].owner_cell_id
            assert second.outputs["control"].owner_cell_id == owner
            assert set(context.ui_element_registry._objects) == {object_id}
            assert context.ui_element_registry.get_object(object_id) is created[1]()
            assert created[0]() is None
            assert created[1]() is not None
            assert second.outputs["control"].reset_ui_object_ids == (object_id,)
            assert notifications == []
    finally:
        with context.install():
            renderer.close()
        gc.collect()
        context.virtual_file_registry.shutdown()


def test_output_renderer_defers_owner_notification_for_mixed_ui(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import gc
    import weakref

    from marimo._output.formatting import FormattedOutput
    from marimo._plugins.ui._core.ui_element import UIElement

    class ProjectedElement(UIElement[int, int]):
        def __init__(self, value: int) -> None:
            super().__init__(
                component_name="projected-element",
                initial_value=value,
                label=None,
                on_change=None,
                args={},
            )

        def _convert_value(self, value: int) -> int:
            return value

    class MixedOutput:
        def __init__(self, value: int) -> None:
            self.value = value
            self.fresh: Any | None = None

        def format(self) -> str:
            if self.fresh is None:
                self.fresh = ProjectedElement(self.value)
                fresh.append(weakref.ref(self.fresh))
            cached_element = cached[0]
            if cached_element is None:
                cached_element = ProjectedElement(1)
                cached[0] = cached_element
            return self.fresh.text + cached_element.text

    cached: list[Any | None] = [None]
    fresh: list[weakref.ReferenceType[Any]] = []

    def format_output(value: MixedOutput, **_kwargs: object) -> FormattedOutput:
        return FormattedOutput("text/html", value.format())

    notifications: list[str] = []
    monkeypatch.setattr("marimo._output.formatting.try_format", format_output)
    monkeypatch.setattr(
        "marimo._messaging.notification_utils.broadcast_notification",
        lambda notification: notifications.append(str(notification.cell_id)),
    )
    context = _native_output_context()
    renderer = KernelOutputRenderer(context)
    value: MixedOutput | None = MixedOutput(2)
    try:
        with context.install():
            first = renderer.render(
                {"controls": value},
                ("controls",),
                ("controls",),
                {"controls"},
                consumer_id="preview-a",
                max_output_bytes=10_000,
            )
            object_ids = tuple(context.ui_element_registry._objects)
            cached_element = cached[0]
            value = None
            gc.collect()
            assert fresh[0]() is None
            assert set(context.ui_element_registry._objects) == {object_ids[1]}

            value = MixedOutput(1)
            second = renderer.render(
                {"controls": value},
                ("controls",),
                ("controls",),
                {"controls"},
                consumer_id="preview-a",
                max_output_bytes=10_000,
            )

            owner = first.outputs["controls"].owner_cell_id
            assert second.outputs["controls"].owner_cell_id == owner
            assert set(context.ui_element_registry._objects) == set(object_ids)
            assert context.ui_element_registry.get_object(object_ids[0]) is fresh[1]()
            assert (
                context.ui_element_registry.get_object(object_ids[1]) is cached_element
            )
            assert fresh[1]() is value.fresh
            assert second.outputs["controls"].reset_ui_object_ids == (object_ids[0],)
            assert notifications == []
    finally:
        value = None
        cached[0] = None
        with context.install():
            renderer.close()
        gc.collect()
        context.virtual_file_registry.shutdown()


def test_output_renderer_scopes_native_owners_to_each_consumer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from marimo._output.formatting import FormattedOutput

    context = _OutputContext()
    monkeypatch.setattr(
        "marimo._output.formatting.try_format",
        lambda *_args, **_kwargs: FormattedOutput(
            "text/html", "<button>Ready</button>"
        ),
    )
    monkeypatch.setattr(
        "marimo._messaging.notification_utils.broadcast_notification",
        lambda _notification: None,
    )
    renderer = KernelOutputRenderer(context)

    first = renderer.render(
        {"summary": object(), "detail": object()},
        ("summary",),
        ("summary",),
        {"summary", "detail"},
        consumer_id="preview-a",
        max_output_bytes=1_000,
    )
    second = renderer.render(
        {"summary": object(), "detail": object()},
        ("summary",),
        ("summary",),
        {"summary", "detail"},
        consumer_id="preview-b",
        max_output_bytes=1_000,
    )
    renderer.render(
        {"summary": object(), "detail": object()},
        ("detail",),
        ("detail",),
        {"summary", "detail"},
        consumer_id="preview-b",
        max_output_bytes=1_000,
    )
    refreshed = renderer.render(
        {"summary": object(), "detail": object()},
        ("summary",),
        ("summary",),
        {"summary", "detail"},
        consumer_id="preview-a",
        max_output_bytes=1_000,
    )

    first_owner = first.outputs["summary"].owner_cell_id
    second_owner = second.outputs["summary"].owner_cell_id
    assert first_owner != second_owner
    assert refreshed.outputs["summary"].owner_cell_id == first_owner
    assert [str(owner) for owner in context.cell_lifecycle_registry.disposed].count(
        first_owner
    ) == 1
    assert context.cell_lifecycle_registry.deletions[-1] is False


@pytest.mark.parametrize(
    ("failed_namespace", "error_code"),
    [
        ({}, "missing-variable"),
        ({"report": {}}, "value-path-unavailable"),
    ],
)
def test_output_renderer_releases_resources_on_resolution_failure(
    failed_namespace: dict[str, object],
    error_code: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from marimo._output.formatting import FormattedOutput

    context = _OutputContext()
    monkeypatch.setattr(
        "marimo._output.formatting.try_format",
        lambda *_args, **_kwargs: FormattedOutput(
            "text/html", "<button>Ready</button>"
        ),
    )
    monkeypatch.setattr(
        "marimo._messaging.notification_utils.broadcast_notification",
        lambda _notification: None,
    )
    renderer = KernelOutputRenderer(context)
    selector = 'report["table"]'
    ready_namespace = {"report": {"table": object()}}

    ready = renderer.render(
        ready_namespace,
        (selector,),
        (selector,),
        {selector},
        consumer_id="preview-a",
        max_output_bytes=1_000,
    )
    failed = renderer.render(
        failed_namespace,
        (selector,),
        (selector,),
        {selector},
        consumer_id="preview-a",
        max_output_bytes=1_000,
    )
    recovered = renderer.render(
        ready_namespace,
        (selector,),
        (selector,),
        {selector},
        consumer_id="preview-a",
        max_output_bytes=1_000,
    )

    owner = ready.outputs[selector].owner_cell_id
    assert failed.errors[selector].code == error_code
    assert recovered.outputs[selector].owner_cell_id == owner
    assert [str(item) for item in context.cell_lifecycle_registry.disposed].count(
        owner
    ) == 1
    assert context.cell_lifecycle_registry.deletions == [False]


def test_output_renderer_bounds_the_encoded_response_and_releases_owners(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from marimo._output.formatting import FormattedOutput

    data = 'quoted "value" ' * 8
    monkeypatch.setattr(
        "marimo._output.formatting.try_format",
        lambda *_args, **_kwargs: FormattedOutput("text/plain", data),
    )
    monkeypatch.setattr(
        "marimo._messaging.notification_utils.broadcast_notification",
        lambda _notification: None,
    )
    monkeypatch.setattr(
        "marimo_studio._compat.kernel_values.outputs.time.time",
        lambda: 1.0,
    )
    baseline_renderer = KernelOutputRenderer(_OutputContext())
    baseline = baseline_renderer.render(
        {"summary": object()},
        ("summary",),
        ("summary",),
        {"summary"},
        consumer_id="preview-a",
        max_output_bytes=10_000,
    )
    expected_output = baseline.outputs["summary"].to_dict()
    output_size = len(
        json.dumps(
            expected_output,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    )
    response_size = len(
        json.dumps(
            baseline.to_dict(),
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    )
    limit = output_size + 1
    assert len(data.encode("utf-8")) < limit < response_size
    baseline_renderer.close()
    context = _OutputContext()

    rendered = KernelOutputRenderer(context).render(
        {"summary": object()},
        ("summary",),
        ("summary",),
        {"summary"},
        consumer_id="preview-a",
        max_output_bytes=limit,
    )

    assert rendered.outputs == {}
    assert rendered.errors["*"].code == "response-too-large"
    assert len(context.cell_lifecycle_registry.disposed) == 1
    assert context.cell_lifecycle_registry.deletions == [False]


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
