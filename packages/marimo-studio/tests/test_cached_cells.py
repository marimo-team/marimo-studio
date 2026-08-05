from types import SimpleNamespace
from typing import Any

from marimo._runtime.executor.lifecycles.cached import CachedLifecycle
from marimo._save import encode
from marimo._save.hash import data_to_buffer
from marimo._save.stubs.lazy_stub import LAZY_STUB_LOOKUP

from marimo_studio._compat.cached_cells import keep_cached_cells_compatible


def _attempt(*, definition: object = None, returned: object = None) -> Any:
    return SimpleNamespace(
        defs={} if definition is None else {"output": definition},
        meta={"return": returned},
        stateful_refs=set(),
    )


def _ui_marker() -> SimpleNamespace:
    return SimpleNamespace(type_name="marimo._save.stubs.ui_element_stub.UIElementStub")


def test_cached_ui_values_run_live_while_data_results_remain_lazy() -> None:
    release = keep_cached_cells_compatible()
    try:
        assert CachedLifecycle._restored_ui_defs(_attempt(definition=_ui_marker()), {})
        assert CachedLifecycle._restored_ui_defs(_attempt(returned=_ui_marker()), {})
        assert not CachedLifecycle._restored_ui_defs(
            _attempt(definition={"count": 18_259}, returned="ready"),
            {},
        )
    finally:
        release()


def test_polars_cache_uses_pickle_during_studio_kernel() -> None:
    dataframe_type = "polars.dataframe.frame.DataFrame"
    original = LAZY_STUB_LOOKUP[dataframe_type]
    release = keep_cached_cells_compatible()
    try:
        assert LAZY_STUB_LOOKUP[dataframe_type] == "pickle"
    finally:
        release()
    assert LAZY_STUB_LOOKUP[dataframe_type] == original


def test_polars_cache_hashes_with_native_serialization() -> None:
    import polars as pl

    original = encode._contiguous_tensor_bytes
    release = keep_cached_cells_compatible()
    try:
        first = data_to_buffer(pl.DataFrame({"objectid": [1, 2]}))
        same = data_to_buffer(pl.DataFrame({"objectid": [1, 2]}))
        changed = data_to_buffer(pl.DataFrame({"objectid": [1, 3]}))
        assert first == same
        assert first != changed
    finally:
        release()
    assert encode._contiguous_tensor_bytes is original
