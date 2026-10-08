from __future__ import annotations

import base64
import io
import math
import sys
from types import SimpleNamespace
from typing import Any, cast

import pytest

from marimo_studio._compat.kernel_values import representations
from marimo_studio._compat.kernel_values.representations import (
    ValueEncoder,
    inspection_value,
)
from marimo_studio._compat.kernel_values.selectors import _read_values
from marimo_studio._projections.runtime_records import ValueLimits

from .values_test_support import (
    _encoded_json,
    _native_output_context,
    _selectors,
)


def test_kernel_value_reads_use_json_string_escape_semantics() -> None:
    selectors = (r'context["a\/b"]', r'context["\ud83d\ude00"]')
    result = _read_values(
        {"context": {"a/b": "slash", "😀": "emoji"}},
        _selectors(*selectors),
    )

    assert result.values == {
        selectors[0]: _encoded_json("slash"),
        selectors[1]: _encoded_json("emoji"),
    }


def test_kernel_projection_returns_exact_json_leaves_and_local_errors() -> None:
    namespace = {
        "context": {
            "label": "July 29, 2026",
            "rows": [{"ticker": "MARS"}],
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
    )
    result = _read_values(
        namespace,
        _selectors(*selectors),
    )

    assert result.values == {
        "context.label": _encoded_json("July 29, 2026"),
        "context.rows[0].ticker": _encoded_json("MARS"),
    }
    errors = cast(dict[str, object], result.to_dict()["errors"])
    assert cast(dict[str, str], errors["context.missing"])["code"] == (
        "value-path-unavailable"
    )
    assert cast(dict[str, str], errors["infinite"])["code"] == ("not-json-serializable")
    assert cast(dict[str, str], errors["opaque"])["code"] == ("not-json-serializable")
    assert cast(dict[str, str], errors["absent"])["code"] == "missing-variable"


def test_kernel_projection_bounds_each_selected_leaf() -> None:
    result = _read_values(
        {"context": {"small": {"count": 3}, "large": "x" * 100}},
        _selectors("context.small", "context.large"),
        limits=ValueLimits(json_value_bytes=32),
    )

    assert result.values == {"context.small": _encoded_json({"count": 3})}
    assert result.errors["context.large"].code == "value-too-large"


def test_kernel_projection_bounds_json_values_per_read() -> None:
    result = _read_values(
        {"context": {"first": "x" * 600_000, "second": "y" * 600_000}},
        _selectors("context.first", "context.second"),
    )

    assert result.values == {"context.first": _encoded_json("x" * 600_000)}
    assert result.errors["context.second"].code == "response-too-large"


def test_kernel_projection_encodes_mixed_values_independently() -> None:
    import polars as pl

    selectors = ("bundle.frame", "bundle.rows", "opaque")
    result = _read_values(
        {
            "bundle": {
                "frame": pl.DataFrame({"value": [1, None]}),
                "rows": [{"id": 1}, {"id": 2}],
            },
            "opaque": object(),
        },
        _selectors(*selectors),
    )

    frame = cast(dict[str, object], result.values["bundle.frame"])
    assert frame["codec"] == "arrow-ipc-v1"
    assert cast(str, frame["fingerprint"]).startswith("sha256:")
    data_url = cast(str, frame["dataUrl"])
    assert data_url.startswith("data:")
    assert result.values["bundle.rows"] == _encoded_json([{"id": 1}, {"id": 2}])
    assert result.errors["opaque"].code == "not-json-serializable"
    ipc = base64.b64decode(data_url.partition(",")[2])
    assert frame["byteLength"] == len(ipc)
    assert pl.read_ipc_stream(io.BytesIO(ipc)).to_dict(as_series=False) == {
        "value": [1, None]
    }


def test_kernel_projection_encodes_pyarrow_tables_and_batches() -> None:
    import pyarrow as pa

    table = pa.table({"name": ["Ada", "Grace"], "score": [3, None]})
    values = {"table": table, "record_batch": table.to_batches()[0]}
    result = _read_values(
        values,
        _selectors(*values),
    )

    for name in values:
        payload = cast(dict[str, object], result.values[name])
        ipc = base64.b64decode(cast(str, payload["dataUrl"]).partition(",")[2])
        assert payload["codec"] == "arrow-ipc-v1"
        assert pa.ipc.open_stream(io.BytesIO(ipc)).read_all().to_pydict() == {
            "name": ["Ada", "Grace"],
            "score": [3, None],
        }


def test_kernel_projection_encodes_pandas_dataframe_types() -> None:
    import pandas as pd
    import pyarrow as pa

    frame = pd.DataFrame(
        {
            "count": pd.Series([1, pd.NA], dtype="Int64"),
            "segment": pd.Series(["retail", "enterprise"], dtype="category"),
            "observed_at": pd.to_datetime(
                ["2026-08-28T12:00:00Z", "2026-08-29T12:00:00Z"]
            ),
        }
    )
    result = _read_values(
        {"frame": frame},
        _selectors("frame"),
    )

    payload = cast(dict[str, object], result.values["frame"])
    ipc = base64.b64decode(cast(str, payload["dataUrl"]).partition(",")[2])
    decoded = pa.ipc.open_stream(io.BytesIO(ipc)).read_all()
    assert payload["codec"] == "arrow-ipc-v1"
    assert decoded.column_names == ["count", "segment", "observed_at"]
    assert decoded.to_pydict()["count"] == [1, None]
    assert decoded.to_pydict()["segment"] == ["retail", "enterprise"]


@pytest.mark.parametrize(
    ("kind", "expected_code"),
    [
        ("lazy", "arrow-materialization-required"),
        ("object", "arrow-serialization-error"),
        ("pandas-no-pyarrow", "arrow-codec-unavailable"),
    ],
)
def test_kernel_projection_reports_dataframe_conversion_errors(
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
    expected_code: str,
) -> None:
    import polars as pl

    if kind == "lazy":
        frame: object = pl.DataFrame({"value": [1]}).lazy()
    elif kind == "object":
        frame = pl.DataFrame({"value": pl.Series("value", [object()], dtype=pl.Object)})
    else:
        import pandas as pd

        frame = pd.DataFrame({"value": [1]})
        monkeypatch.setitem(sys.modules, "pyarrow", None)
    result = _read_values(
        {"frame": frame},
        _selectors("frame"),
    )

    assert result.values == {}
    assert result.errors["frame"].code == expected_code


def test_kernel_projection_encodes_empty_eager_dataframes() -> None:
    import polars as pl
    import pyarrow as pa

    frame = pl.DataFrame(schema={"value": pl.Int64, "label": pl.String})
    result = _read_values(
        {"frame": frame},
        _selectors("frame"),
    )

    payload = cast(dict[str, object], result.values["frame"])
    ipc = base64.b64decode(cast(str, payload["dataUrl"]).partition(",")[2])
    decoded = pa.ipc.open_stream(io.BytesIO(ipc)).read_all()
    assert decoded.column_names == ["value", "label"]
    assert decoded.num_rows == 0


def test_kernel_projection_sends_dataframes_beyond_the_json_limit() -> None:
    import polars as pl

    frame = pl.DataFrame({"value": range(250_000)})
    context = _native_output_context()
    encoder = ValueEncoder(context)
    with context.install():
        result = _read_values(
            {"frame": frame, "rows": frame.to_dicts()},
            _selectors("frame", "rows"),
            encoder=encoder,
        )
        encoder.close()
    context.virtual_file_registry.shutdown()

    descriptor = cast(dict[str, object], result.values["frame"])
    assert descriptor["codec"] == "arrow-ipc-v1"
    assert cast(int, descriptor["byteLength"]) > 2_000_000
    assert result.errors["rows"].code == "value-too-large"


def test_kernel_projection_inlines_arrow_values_that_exceed_free_shared_memory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import polars as pl
    from marimo._runtime.virtual_file.storage import SharedMemoryStorage

    monkeypatch.setattr(
        representations.os,
        "statvfs",
        lambda _path: SimpleNamespace(f_bavail=1, f_frsize=4_096),
        raising=False,
    )
    context = _native_output_context()
    context.virtual_file_registry.storage = SharedMemoryStorage()
    encoder = ValueEncoder(context)
    with context.install():
        result = _read_values(
            {"frame": pl.DataFrame({"value": range(1_000)})},
            _selectors("frame"),
            encoder=encoder,
        )

        descriptor = cast(dict[str, object], result.values["frame"])
        assert cast(str, descriptor["dataUrl"]).startswith("data:")
        assert tuple(context.virtual_file_registry.filenames()) == ()
        encoder.close()
    context.virtual_file_registry.shutdown()


def test_kernel_projection_budgets_arrow_values_apart_from_json() -> None:
    import polars as pl

    frame = pl.DataFrame({"value": range(1_000)})
    context = _native_output_context()
    encoder = ValueEncoder(context)
    with context.install():
        result = _read_values(
            {"first": frame, "second": frame, "label": "x" * 900_000},
            _selectors("first", "second", "label"),
            limits=ValueLimits(arrow_read_bytes=12_000),
            encoder=encoder,
        )

        assert set(result.values) == {"first", "label"}
        assert result.errors["second"].code == "response-too-large"
        assert "Arrow values read from one cell" in result.errors["second"].message
        assert len(tuple(context.virtual_file_registry.filenames())) == 1
        encoder.close()
    context.virtual_file_registry.shutdown()


def test_kernel_projection_bounds_arrow_ipc_values() -> None:
    import polars as pl

    result = _read_values(
        {"frame": pl.DataFrame({"value": ["x" * 1_000]})},
        _selectors("frame"),
        limits=ValueLimits(arrow_value_bytes=100),
    )

    assert result.values == {}
    assert result.errors["frame"].code == "value-too-large"


def test_runtime_inspection_unwraps_json_and_hides_arrow_resource_urls() -> None:
    json_value = _encoded_json({"count": 2})
    arrow_value = {
        "codec": "arrow-ipc-v1",
        "fingerprint": f"sha256:{'1' * 64}",
        "dataUrl": "./@file/10-frame.arrow",
        "byteLength": 10,
    }

    assert inspection_value(json_value) == {"count": 2}
    assert inspection_value(arrow_value) == {
        "codec": "arrow-ipc-v1",
        "fingerprint": f"sha256:{'1' * 64}",
        "byteLength": 10,
    }


def test_kernel_projection_replaces_and_releases_arrow_resources() -> None:
    import polars as pl

    context = _native_output_context()
    encoder = ValueEncoder(context)
    with context.install():
        first = _read_values(
            {"frame": pl.DataFrame({"value": [1]})},
            _selectors("frame"),
            consumer_id="preview",
            revision="revision-1",
            encoder=encoder,
        )
        first_url = cast(dict[str, object], first.values["frame"])["dataUrl"]
        assert cast(str, first_url).startswith("./@file/")
        assert len(tuple(context.virtual_file_registry.filenames())) == 1

        same = _read_values(
            {"frame": pl.DataFrame({"value": [1]})},
            _selectors("frame"),
            consumer_id="preview",
            revision="revision-1",
            encoder=encoder,
        )
        assert cast(dict[str, object], same.values["frame"])["dataUrl"] == first_url
        assert len(tuple(context.virtual_file_registry.filenames())) == 1

        second = _read_values(
            {"frame": pl.DataFrame({"value": [2]})},
            _selectors("frame"),
            consumer_id="preview",
            revision="revision-1",
            encoder=encoder,
        )
        second_url = cast(dict[str, object], second.values["frame"])["dataUrl"]
        assert second_url != first_url
        assert len(tuple(context.virtual_file_registry.filenames())) == 1

        _read_values(
            {"frame": {"value": 2}},
            _selectors("frame"),
            consumer_id="preview",
            revision="revision-1",
            encoder=encoder,
        )
        assert tuple(context.virtual_file_registry.filenames()) == ()

        encoder.close()
    context.virtual_file_registry.shutdown()


def test_kernel_projection_isolates_arrow_resources_by_consumer_and_revision() -> None:
    import polars as pl

    context = _native_output_context()
    encoder = ValueEncoder(context)

    def read(consumer_id: str, revision: str, value: int) -> str:
        result = _read_values(
            {"frame": pl.DataFrame({"value": [value]})},
            _selectors("frame"),
            consumer_id=consumer_id,
            revision=revision,
            encoder=encoder,
        )
        return cast(str, cast(dict[str, object], result.values["frame"])["dataUrl"])

    with context.install():
        first_a = read("preview-a", "revision-1", 1)
        first_b = read("preview-b", "revision-1", 1)
        assert first_a != first_b
        assert len(tuple(context.virtual_file_registry.filenames())) == 2

        second_a = read("preview-a", "revision-2", 2)
        assert second_a not in {first_a, first_b}
        assert len(tuple(context.virtual_file_registry.filenames())) == 2

        encoder.release_consumer("preview-a")
        assert len(tuple(context.virtual_file_registry.filenames())) == 1
        encoder.close()
        assert tuple(context.virtual_file_registry.filenames()) == ()
    context.virtual_file_registry.shutdown()


def test_kernel_projection_discards_uncommitted_resources_after_commit_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import polars as pl

    context = _native_output_context()
    encoder = ValueEncoder(context)
    specifications = _selectors("first", "second")
    with context.install():
        _read_values(
            {"first": pl.DataFrame({"value": [1]})},
            {"first": specifications["first"]},
            specifications,
            consumer_id="preview",
            revision="revision-1",
            encoder=encoder,
        )
        initial_files = tuple(context.virtual_file_registry.filenames())
        assert len(initial_files) == 1

        original_remove = context.virtual_file_registry.remove
        remove_calls = 0

        def fail_once(resource: Any) -> None:
            nonlocal remove_calls
            remove_calls += 1
            if remove_calls == 1:
                raise OSError("resource removal failed")
            original_remove(resource)

        monkeypatch.setattr(context.virtual_file_registry, "remove", fail_once)
        with pytest.raises(OSError, match="resource removal failed"):
            _read_values(
                {
                    "first": pl.DataFrame({"value": [2]}),
                    "second": pl.DataFrame({"value": [2]}),
                },
                specifications,
                specifications,
                consumer_id="preview",
                revision="revision-1",
                encoder=encoder,
            )

        assert tuple(context.virtual_file_registry.filenames()) == initial_files
        encoder.close()
        assert tuple(context.virtual_file_registry.filenames()) == ()
    context.virtual_file_registry.shutdown()


def test_kernel_projection_discards_resources_when_envelope_too_large() -> None:
    import polars as pl

    missing = tuple(f"missing_{index}" for index in range(10))
    context = _native_output_context()
    encoder = ValueEncoder(context)
    with context.install():
        result = _read_values(
            {"frame": pl.DataFrame({"value": [1]}), "label": 1},
            _selectors("frame", "label", *missing),
            limits=ValueLimits(json_read_bytes=10, arrow_read_bytes=400),
            consumer_id="preview",
            revision="revision-1",
            encoder=encoder,
        )

        assert result.values == {}
        assert result.errors["*"].code == "response-too-large"
        assert tuple(context.virtual_file_registry.filenames()) == ()
        encoder.close()
    context.virtual_file_registry.shutdown()


def test_kernel_projection_retires_inactive_and_failed_arrow_resources() -> None:
    import polars as pl

    context = _native_output_context()
    encoder = ValueEncoder(context)
    with context.install():
        active = _selectors("first", "second")
        _read_values(
            {"first": pl.DataFrame({"value": [1]})},
            _selectors("first"),
            active,
            consumer_id="preview",
            revision="revision-1",
            encoder=encoder,
        )
        first_file = tuple(context.virtual_file_registry.filenames())
        assert len(first_file) == 1

        _read_values(
            {"second": pl.DataFrame({"value": [2]})},
            _selectors("second"),
            active,
            consumer_id="preview",
            revision="revision-1",
            encoder=encoder,
        )
        second_file = tuple(context.virtual_file_registry.filenames())
        assert len(second_file) == 2

        _read_values(
            {"second": pl.DataFrame({"value": [2]})},
            _selectors("second"),
            _selectors("second"),
            consumer_id="preview",
            revision="revision-1",
            encoder=encoder,
        )
        assert len(tuple(context.virtual_file_registry.filenames())) == 1

        failed = _read_values(
            {"second": pl.DataFrame({"value": [2]}).lazy()},
            _selectors("second"),
            _selectors("second"),
            consumer_id="preview",
            revision="revision-1",
            encoder=encoder,
        )
        assert failed.errors["second"].code == "arrow-materialization-required"
        assert tuple(context.virtual_file_registry.filenames()) == ()

        encoder.close()
    context.virtual_file_registry.shutdown()
