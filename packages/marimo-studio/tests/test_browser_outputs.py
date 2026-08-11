from __future__ import annotations

import weakref
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from types import SimpleNamespace
from typing import Any, cast

import pytest

from marimo_studio._compat.browser_notebook import _value_bridge
from marimo_studio._compat.kernel_values.models import OUTPUT_OWNER_PREFIX
from marimo_studio._compat.kernel_values.outputs import KernelOutputRenderer
from marimo_studio.values import parse_value_reference


class _CellApp:
    def __init__(self) -> None:
        self.function: Callable[[], None] | None = None

    def cell(self, **_: object) -> Callable[[Callable[[], None]], Callable[[], None]]:
        def register(function: Callable[[], None]) -> Callable[[], None]:
            self.function = function
            return function

        return register


class _FunctionRegistry:
    def __init__(self, *, fail_on_registration: int | None = None) -> None:
        self.namespaces: dict[str, dict[str, Any]] = {}
        self.deleted: list[str] = []
        self.registration_count = 0
        self.fail_on_registration = fail_on_registration

    def register(self, namespace: str, function: Any) -> None:
        self.registration_count += 1
        if self.registration_count == self.fail_on_registration:
            raise RuntimeError("registration failed")
        self.namespaces.setdefault(namespace, {})[function.name] = function

    def get_function(self, namespace: str, name: str) -> Any | None:
        return self.namespaces.get(namespace, {}).get(name)

    def delete(self, namespace: str) -> None:
        self.deleted.append(namespace)
        self.namespaces.pop(namespace, None)


class _UIElementRegistry:
    def __init__(self) -> None:
        self._objects: dict[str, weakref.ReferenceType[Any]] = {}
        self._constructing_cells: dict[str, object] = {}
        self._bindings: dict[str, set[str]] = {}

    def delete(self, object_id: str, python_id: int) -> None:
        reference = self._objects.get(object_id)
        value = reference() if reference is not None else None
        if value is not None and id(value) != python_id:
            return
        self._objects.pop(object_id, None)
        self._constructing_cells.pop(object_id, None)
        self._bindings.pop(object_id, None)


class _LifecycleRegistry:
    def __init__(self, context: _GeneratedContext) -> None:
        self._context = context
        self.registry: dict[object, set[Any]] = {}
        self.added: list[Any] = []
        self.disposed: list[object] = []
        self.dispose_attempts: list[object] = []
        self.fail_add = False
        self.failed_disposals = 0

    def add(self, item: Any) -> None:
        if self.fail_add:
            raise RuntimeError("lifecycle registration failed")
        item.create(self._context)
        self.added.append(item)
        self.registry.setdefault(self._context.cell_id, set()).add(item)

    def dispose(self, cell_id: object, *, deletion: bool) -> None:
        del deletion
        self.dispose_attempts.append(cell_id)
        if self.failed_disposals:
            self.failed_disposals -= 1
            raise RuntimeError("dispose failed")
        self.disposed.append(cell_id)
        self.registry.pop(cell_id, None)


class _Kernel:
    @contextmanager
    def lock_globals(self) -> Iterator[None]:
        yield


class _QueryParams:
    def __init__(self) -> None:
        self.values: dict[str, str | list[str]] = {}

    def to_dict(self) -> dict[str, str | list[str]]:
        return dict(self.values)

    def remove(self, key: str) -> None:
        self.values.pop(key, None)

    def set(self, key: str, value: str | list[str]) -> None:
        self.values[key] = value


class _GeneratedContext:
    def __init__(self, *, fail_on_registration: int | None = None) -> None:
        from marimo._types.ids import CellId_t

        self.function_registry = _FunctionRegistry(
            fail_on_registration=fail_on_registration
        )
        self.ui_element_registry = _UIElementRegistry()
        self.cell_id: object = CellId_t("browser-bridge")
        self.cell_lifecycle_registry = _LifecycleRegistry(self)
        self.query_params = _QueryParams()
        self.globals: dict[str, object] = {"control": object()}
        self._kernel = _Kernel()
        self.ui_prefix: str | None = None
        self.notifications: list[object] = []

    @contextmanager
    def with_cell_id(self, cell_id: object) -> Iterator[None]:
        previous = self.cell_id
        self.cell_id = cell_id
        try:
            yield
        finally:
            self.cell_id = previous

    @contextmanager
    def provide_ui_ids(self, prefix: str) -> Iterator[None]:
        previous = self.ui_prefix
        self.ui_prefix = prefix
        try:
            yield
        finally:
            self.ui_prefix = previous


class _ElementFunction:
    name = "ping"

    def __init__(self, element: _Element) -> None:
        self.element = element


class _Element:
    def __init__(self) -> None:
        self._args = SimpleNamespace(functions=(_ElementFunction(self),))


def _format_element(context: _GeneratedContext) -> Any:
    from marimo._output.formatting import FormattedOutput

    def format_element(*_: object, **__: object) -> FormattedOutput:
        assert context.ui_prefix is not None
        object_id = f"{context.ui_prefix}-0"
        element = _Element()
        context.ui_element_registry._objects[object_id] = weakref.ref(element)
        context.ui_element_registry._constructing_cells[object_id] = context.cell_id
        context.function_registry.register(object_id, element._args.functions[0])
        return FormattedOutput(
            "text/html",
            f'<marimo-ui-element object-id="{object_id}"></marimo-ui-element>',
        )

    return format_element


def _install_generated_adapter(
    monkeypatch: pytest.MonkeyPatch,
    context: _GeneratedContext,
) -> None:
    monkeypatch.setattr("marimo._runtime.context.get_context", lambda: context)
    monkeypatch.setattr(
        "marimo._output.formatting.try_format", _format_element(context)
    )
    monkeypatch.setattr(
        "marimo._messaging.notification_utils.broadcast_notification",
        lambda notification: context.notifications.append(notification.cell_id),
    )
    reference = parse_value_reference("control")
    app = _CellApp()
    namespace: dict[str, Any] = {"app": app}
    exec(_value_bridge({"control": reference}, {"control": reference}), namespace)
    assert app.function is not None
    app.function()


def _call_bridge(
    context: _GeneratedContext,
    name: str,
    payload: dict[str, object],
) -> dict[str, Any]:
    function = context.function_registry.get_function("_marimo_studio", name)
    assert function is not None
    return cast(dict[str, Any], function(payload))


def _render(
    context: _GeneratedContext,
    consumer_id: str,
    selectors: list[str],
    active_selectors: list[str],
) -> dict[str, Any]:
    return _call_bridge(
        context,
        "render_values",
        {
            "selectors": selectors,
            "active_selectors": active_selectors,
            "consumer_id": consumer_id,
            "max_output_bytes": 10_000,
        },
    )


def test_generated_output_adapter_owns_replaces_and_releases_outputs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _GeneratedContext()
    _install_generated_adapter(monkeypatch, context)

    first = _render(context, "preview-a", ["control"], ["control"])
    second = _render(context, "preview-a", ["control"], ["control"])
    other = _render(context, "preview-b", ["control"], ["control"])

    first_output = first["outputs"]["control"]
    second_output = second["outputs"]["control"]
    other_output = other["outputs"]["control"]
    owner = first_output["ownerCellId"]
    object_id = f"{owner}-0"
    assert owner.startswith(OUTPUT_OWNER_PREFIX)
    assert second_output["ownerCellId"] == owner
    assert other_output["ownerCellId"] != owner
    assert second_output["resetUiObjectIds"] == [object_id]

    released = _render(context, "preview-a", [], [])
    attempts = context.cell_lifecycle_registry.dispose_attempts.count(owner)
    assert released == {"outputs": {}, "errors": {}}
    assert object_id not in context.ui_element_registry._objects
    assert object_id not in context.function_registry.namespaces

    assert _render(context, "preview-a", [], []) == {"outputs": {}, "errors": {}}
    assert context.cell_lifecycle_registry.dispose_attempts.count(owner) == attempts


def test_generated_output_adapter_retries_release_after_cleanup_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _GeneratedContext()
    _install_generated_adapter(monkeypatch, context)
    rendered = _render(context, "preview-a", ["control"], ["control"])
    owner = rendered["outputs"]["control"]["ownerCellId"]
    context.cell_lifecycle_registry.failed_disposals = 1

    with pytest.raises(RuntimeError, match="dispose failed"):
        _render(context, "preview-a", [], [])

    assert _render(context, "preview-a", [], []) == {"outputs": {}, "errors": {}}
    assert context.cell_lifecycle_registry.dispose_attempts.count(owner) == 2
    assert _render(context, "preview-a", [], []) == {"outputs": {}, "errors": {}}
    assert context.cell_lifecycle_registry.dispose_attempts.count(owner) == 2


def test_generated_output_adapter_retries_and_idempotently_closes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _GeneratedContext()
    _install_generated_adapter(monkeypatch, context)
    rendered = _render(context, "preview-a", ["control"], ["control"])
    owner = rendered["outputs"]["control"]["ownerCellId"]
    lifecycle = context.cell_lifecycle_registry.added[0]
    context.cell_lifecycle_registry.failed_disposals = 1

    assert lifecycle.dispose(context, False) is False
    assert lifecycle.dispose(context, False) is True
    assert lifecycle.dispose(context, False) is True
    assert context.cell_lifecycle_registry.dispose_attempts.count(owner) == 2
    assert "_marimo_studio" not in context.function_registry.namespaces


@pytest.mark.parametrize("failure", ["function", "lifecycle"])
def test_generated_output_adapter_cleans_partial_setup(
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    context = _GeneratedContext(
        fail_on_registration=3 if failure == "function" else None
    )
    context.cell_lifecycle_registry.fail_add = failure == "lifecycle"

    with pytest.raises(RuntimeError, match="failed"):
        _install_generated_adapter(monkeypatch, context)

    assert "_marimo_studio" not in context.function_registry.namespaces
    assert context.function_registry.deleted == ["_marimo_studio"]
    assert context.cell_lifecycle_registry.added == []


def test_native_output_renderer_retries_and_idempotently_closes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from marimo._output.formatting import FormattedOutput

    context = _GeneratedContext()
    monkeypatch.setattr(
        "marimo._output.formatting.try_format",
        lambda *_args, **_kwargs: FormattedOutput("text/plain", "ready"),
    )
    monkeypatch.setattr(
        "marimo._messaging.notification_utils.broadcast_notification",
        lambda _notification: None,
    )
    renderer = KernelOutputRenderer(context)
    rendered = renderer.render(
        {"control": object()},
        ("control",),
        ("control",),
        {"control"},
        consumer_id="preview-a",
        max_output_bytes=10_000,
    )
    owner = rendered.outputs["control"].owner_cell_id
    context.cell_lifecycle_registry.failed_disposals = 1

    with pytest.raises(RuntimeError, match="dispose failed"):
        renderer.close()

    renderer.close()
    renderer.close()
    assert context.cell_lifecycle_registry.dispose_attempts.count(owner) == 2
    with pytest.raises(RuntimeError, match="already closed"):
        renderer.render(
            {},
            (),
            (),
            set(),
            consumer_id="preview-a",
            max_output_bytes=10_000,
        )
