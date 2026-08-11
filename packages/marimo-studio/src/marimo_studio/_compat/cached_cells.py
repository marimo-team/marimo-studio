"""Keep native cell-cache restores safe in Studio sessions."""

from __future__ import annotations

from collections.abc import Callable
from io import BytesIO
from threading import Lock
from typing import Any, cast

from marimo_studio.errors import CompatibilityError

_UI_ELEMENT_STUB = "marimo._save.stubs.ui_element_stub.UIElementStub"
_POLARS_TYPES = (
    "polars.dataframe.frame.DataFrame",
    "polars.series.series.Series",
)
_PATCH_LOCK = Lock()
_PATCH_USERS = 0
_ORIGINAL_UI_CHECK: Callable[[Any, dict[str, Any]], bool] | None = None
_PATCHED_UI_CHECK: Callable[[Any, dict[str, Any]], bool] | None = None
_ORIGINAL_POLARS_LOADERS: dict[str, str | None] = {}
_ORIGINAL_TENSOR_BUFFER: Callable[[Any], memoryview] | None = None
_PATCHED_TENSOR_BUFFER: Callable[[Any], memoryview] | None = None


def _type_name(value: object) -> str:
    return f"{type(value).__module__}.{type(value).__name__}"


def _contains_cached_ui(value: object, seen: set[int] | None = None) -> bool:
    from marimo._plugins.ui._core.ui_element import UIElement

    if isinstance(value, UIElement):
        return True
    if getattr(value, "type_name", None) == _UI_ELEMENT_STUB:
        return True
    if _type_name(value) == _UI_ELEMENT_STUB:
        return True

    if not isinstance(value, (dict, list, set, tuple)):
        return False
    if seen is None:
        seen = set()
    value_id = id(value)
    if value_id in seen:
        return False
    seen.add(value_id)
    values = value.values() if isinstance(value, dict) else value
    return any(_contains_cached_ui(item, seen) for item in values)


def _cached_result_contains_ui(attempt: Any) -> bool:
    return any(_contains_cached_ui(value) for value in attempt.defs.values()) or (
        _contains_cached_ui(attempt.meta.get("return"))
    )


def keep_cached_cells_compatible() -> Callable[[], None]:
    """Keep native cached data lazy and interactive outputs live."""
    from marimo._runtime.executor.lifecycles.cached import CachedLifecycle
    from marimo._save import encode
    from marimo._save.stubs.lazy_stub import LAZY_STUB_LOOKUP

    cached_lifecycle_class = cast(Any, CachedLifecycle)
    encode_module = cast(Any, encode)

    global _ORIGINAL_POLARS_LOADERS
    global _ORIGINAL_TENSOR_BUFFER, _PATCHED_TENSOR_BUFFER
    global _ORIGINAL_UI_CHECK, _PATCHED_UI_CHECK, _PATCH_USERS
    with _PATCH_LOCK:
        if _PATCH_USERS and (
            CachedLifecycle._restored_ui_defs is not _PATCHED_UI_CHECK
            or encode._contiguous_tensor_bytes is not _PATCHED_TENSOR_BUFFER
            or any(
                LAZY_STUB_LOOKUP.get(type_name) != "pickle"
                for type_name in _POLARS_TYPES
            )
        ):
            raise CompatibilityError(
                "Another owner replaced the cached-cell repair while Studio "
                "was using it."
            )
        if _PATCH_USERS == 0:
            original = CachedLifecycle._restored_ui_defs

            def restored_ui_defs(attempt: Any, glbls: dict[str, Any]) -> bool:
                return original(attempt, glbls) or _cached_result_contains_ui(attempt)

            _ORIGINAL_UI_CHECK = original
            _PATCHED_UI_CHECK = restored_ui_defs
            cached_lifecycle_class._restored_ui_defs = staticmethod(restored_ui_defs)
            _ORIGINAL_POLARS_LOADERS = {
                type_name: LAZY_STUB_LOOKUP.get(type_name)
                for type_name in _POLARS_TYPES
            }
            for type_name in _POLARS_TYPES:
                LAZY_STUB_LOOKUP[type_name] = "pickle"

            original_tensor_buffer = encode._contiguous_tensor_bytes

            def contiguous_tensor_bytes(value: Any) -> memoryview:
                if _type_name(value) in _POLARS_TYPES:
                    frame = value.to_frame() if hasattr(value, "to_frame") else value
                    buffer = BytesIO()
                    frame.serialize(buffer)
                    return memoryview(buffer.getvalue())
                return original_tensor_buffer(value)

            _ORIGINAL_TENSOR_BUFFER = original_tensor_buffer
            _PATCHED_TENSOR_BUFFER = contiguous_tensor_bytes
            encode_module._contiguous_tensor_bytes = contiguous_tensor_bytes
        _PATCH_USERS += 1

    released = False

    def release() -> None:
        nonlocal released
        global _ORIGINAL_POLARS_LOADERS
        global _ORIGINAL_TENSOR_BUFFER, _PATCHED_TENSOR_BUFFER
        global _ORIGINAL_UI_CHECK, _PATCHED_UI_CHECK, _PATCH_USERS
        with _PATCH_LOCK:
            if released:
                return
            if _PATCH_USERS > 1:
                _PATCH_USERS -= 1
                released = True
                return
            if (
                CachedLifecycle._restored_ui_defs is not _PATCHED_UI_CHECK
                or encode._contiguous_tensor_bytes is not _PATCHED_TENSOR_BUFFER
                or any(
                    LAZY_STUB_LOOKUP.get(type_name) != "pickle"
                    for type_name in _POLARS_TYPES
                )
            ):
                raise CompatibilityError(
                    "Another owner replaced the cached-cell repair before "
                    "Studio could restore it."
                )
            _PATCH_USERS = 0
            released = True
            if (
                _ORIGINAL_UI_CHECK is not None
                and CachedLifecycle._restored_ui_defs is _PATCHED_UI_CHECK
            ):
                cached_lifecycle_class._restored_ui_defs = staticmethod(
                    _ORIGINAL_UI_CHECK
                )
            for type_name, loader in _ORIGINAL_POLARS_LOADERS.items():
                if LAZY_STUB_LOOKUP.get(type_name) != "pickle":
                    continue
                if loader is None:
                    LAZY_STUB_LOOKUP.pop(type_name, None)
                else:
                    LAZY_STUB_LOOKUP[type_name] = loader
            if (
                _ORIGINAL_TENSOR_BUFFER is not None
                and encode._contiguous_tensor_bytes is _PATCHED_TENSOR_BUFFER
            ):
                encode_module._contiguous_tensor_bytes = _ORIGINAL_TENSOR_BUFFER
            _ORIGINAL_POLARS_LOADERS = {}
            _ORIGINAL_TENSOR_BUFFER = None
            _PATCHED_TENSOR_BUFFER = None
            _ORIGINAL_UI_CHECK = None
            _PATCHED_UI_CHECK = None

    return release
