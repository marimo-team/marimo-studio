from __future__ import annotations

import json
from typing import Any

import pytest

from marimo_studio._compat.kernel_values.outputs import KernelOutputRenderer

from .values_test_support import (
    _native_output_context,
    _OutputContext,
    _resource_element_class,
)


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
