"""Build kernel-value fixtures for compatibility tests."""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from hashlib import sha256
from pathlib import PurePosixPath
from types import SimpleNamespace
from typing import Any, Literal, cast

import pytest
from marimo_export.values import ValueSelector

from marimo_studio._compat.kernel_values.authorization import (
    BoundProjection,
    RuntimeCellBinding,
)
from marimo_studio._compat.kernel_values.authorization_key import (
    initialize_projection_authorization_key,
)
from marimo_studio._notebook.cell_refs import cell_refs
from marimo_studio._projections.resolution import (
    ProjectionRequest,
    ResolvedProjection,
)
from marimo_studio.view_providers import SourceLocation


@pytest.fixture(scope="module", autouse=True)
def _projection_authorization_key() -> None:
    initialize_projection_authorization_key()


def _selectors(*sources: str) -> dict[str, ValueSelector]:
    return {source: ValueSelector(source) for source in sources}


def _encoded_json(value: object) -> dict[str, object]:
    encoded = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return {
        "codec": "json-v1",
        "fingerprint": f"sha256:{sha256(encoded).hexdigest()}",
        "value": value,
    }


def _bound_projection(
    source: str,
    kind: Literal["value", "output"] = "value",
) -> BoundProjection:
    selector = ValueSelector(source)
    producer = cell_refs((f"{selector.root} = None",))[0]
    projection = ResolvedProjection(
        request=ProjectionRequest(
            site_id=f"site:{kind}:{source}",
            instance_id=f"projection:{kind}:{source}",
            target=source,
        ),
        kind=kind,
        source=SourceLocation(PurePosixPath("view.html"), 1, 1),
        producer=producer,
        selector=selector,
        dependency_closure=(producer,),
    )
    return BoundProjection(
        projection,
        (RuntimeCellBinding(producer, "runtime-projection"),),
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


def assert_native_resources_released(context: Any) -> None:
    assert context.cell_lifecycle_registry.registry == {}
    assert context.virtual_file_registry.registry == {}
    assert context.function_registry.namespaces == {}
    assert context.ui_element_registry._objects == {}
    assert context.ui_element_registry._constructing_cells == {}


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


class _SummarySession:
    # The host keys live graphs in a WeakKeyDictionary, so the session has to
    # be a hashable object. SimpleNamespace is unhashable.
    def __init__(self, code: str = "summary = {'total': 3}") -> None:
        self.document = SimpleNamespace(cells=[SimpleNamespace(id="runtime-summary")])
        self.session_view = SimpleNamespace(
            last_executed_code={"runtime-summary": code}
        )


def _install_projection_host(
    monkeypatch: pytest.MonkeyPatch,
    session: Any,
    build: Any,
    *,
    read: Any | None = None,
    render: Any | None = None,
    current_session: Any | None = None,
) -> Any:
    from marimo_studio._compat.kernel_values import host as projection_host
    from marimo_studio._projections.runtime_records import (
        OutputRenderResult,
        ValueReadResult,
    )

    async def empty_read(*_args: Any, **_kwargs: Any) -> ValueReadResult:
        return ValueReadResult({}, {})

    async def empty_render(*_args: Any, **_kwargs: Any) -> OutputRenderResult:
        return OutputRenderResult({}, {})

    monkeypatch.setattr(
        projection_host,
        "current_session",
        current_session if current_session is not None else (lambda *_args: session),
    )
    monkeypatch.setattr(projection_host, "_build_live_projection_state", build)
    monkeypatch.setattr(projection_host, "read_session_values", read or empty_read)
    monkeypatch.setattr(
        projection_host, "render_session_outputs", render or empty_render
    )
    return projection_host.PrivateKernelProjectionHost()


async def _call_projection(
    host: Any,
    operation: str,
    projection: Any,
    session_id: str = "session",
) -> Any:
    return await getattr(host, operation)(
        SimpleNamespace(),
        session_id,
        "revision-1",
        (projection,),
        (projection,),
        consumer_id="preview-a",
        runtime_cell_refs={projection.producer: "runtime-summary"},
    )


def _sample_arrow_table() -> Any:
    import pyarrow as pa

    return pa.table({"x": [1]})


@contextmanager
def _installed_value_encoder() -> Iterator[tuple[Any, Any]]:
    from marimo_studio._compat.kernel_values.representations import ValueEncoder

    context = _native_output_context()
    encoder = ValueEncoder(context)
    try:
        with context.install():
            yield context, encoder
    finally:
        context.virtual_file_registry.shutdown()


def _preview_value_read(
    encoder: Any,
    values: dict[str, object],
    *names: str,
) -> Any:
    from marimo_studio._compat.kernel_values.selectors import _read_values

    return _read_values(
        values,
        _selectors(*names),
        consumer_id="preview",
        revision="revision-1",
        encoder=encoder,
    )
