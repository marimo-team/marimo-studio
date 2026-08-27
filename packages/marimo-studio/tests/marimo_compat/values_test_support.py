"""Build kernel-value fixtures for compatibility tests."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import PurePosixPath
from typing import Any, Literal, cast

import pytest

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
from marimo_studio._projections.values import (
    parse_value_reference,
)
from marimo_studio.view_providers import SourceLocation


@pytest.fixture(scope="module", autouse=True)
def _projection_authorization_key() -> None:
    initialize_projection_authorization_key()


def _selector_spec(source: str):
    reference = parse_value_reference(source)
    return (
        reference.variable,
        tuple((step.kind, step.value) for step in reference.path),
    )


def _selector_specs(*sources: str):
    return {source: _selector_spec(source) for source in sources}


def _bound_projection(
    source: str,
    kind: Literal["value", "output"] = "value",
) -> BoundProjection:
    reference = parse_value_reference(source)
    producer = cell_refs((f"{reference.variable} = None",))[0]
    projection = ResolvedProjection(
        request=ProjectionRequest(
            site_id=f"site:{kind}:{source}",
            instance_id=f"projection:{kind}:{source}",
            target=source,
        ),
        kind=kind,
        source=SourceLocation(PurePosixPath("view.html"), 1, 1),
        producer=producer,
        variable=reference.variable,
        selector_path=reference.path,
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
