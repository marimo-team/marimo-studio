from __future__ import annotations

import base64
import io
import json
import math
import sys
from typing import Any, cast

import pytest

from marimo_studio._compat.kernel_values.representations import (
    ValueEncoder,
    inspection_value,
)
from marimo_studio._compat.kernel_values.selectors import (
    _read_values,
    normalize_selector_spec,
)
from marimo_studio._projections.records import ValuePathStep
from marimo_studio._projections.values import (
    parse_value_reference,
    resolve_value_reference,
)

from .values_test_support import (
    _encoded_json,
    _native_output_context,
    _selector_spec,
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


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        (r'context["a\/b"]', "a/b"),
        (r'context["\ud83d\ude00"]', "😀"),
    ],
)
def test_value_reference_uses_json_string_escape_semantics(
    source: str,
    expected: str,
) -> None:
    reference = parse_value_reference(source)

    assert reference.path == (ValuePathStep("item", expected),)


def test_kernel_value_reads_use_json_string_escape_semantics() -> None:
    selectors = (r'context["a\/b"]', r'context["\ud83d\ude00"]')
    result = _read_values(
        {"context": {"a/b": "slash", "😀": "emoji"}},
        {selector: _selector_spec(selector) for selector in selectors},
        max_value_bytes=1_000,
    )

    assert result.values == {
        selectors[0]: _encoded_json("slash"),
        selectors[1]: _encoded_json("emoji"),
    }


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


def test_kernel_selector_specs_must_match_their_targets() -> None:
    assert normalize_selector_spec(
        "report.rows[0]",
        ("report", (("attribute", "rows"), ("item", 0))),
    ) == ("report", (("attribute", "rows"), ("item", 0)))
    with pytest.raises(ValueError, match="does not match"):
        normalize_selector_spec("report.rows", ("other", ()))


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
    )
    specifications = {
        selector: (
            reference.variable,
            tuple((step.kind, step.value) for step in reference.path),
        )
        for selector in selectors
        for reference in (parse_value_reference(selector),)
    }

    result = _read_values(
        namespace,
        specifications,
        max_value_bytes=1_000,
    )

    assert result.values == {
        "context.label": _encoded_json("July 29, 2026"),
        "context.rows[0].ticker": _encoded_json("HTMX"),
    }
    errors = cast(dict[str, object], result.to_dict()["errors"])
    assert cast(dict[str, str], errors["context.missing"])["code"] == (
        "value-path-unavailable"
    )
    assert cast(dict[str, str], errors["infinite"])["code"] == ("not-json-serializable")
    assert cast(dict[str, str], errors["opaque"])["code"] == ("not-json-serializable")
    assert cast(dict[str, str], errors["absent"])["code"] == "missing-variable"


def test_kernel_projection_bounds_each_selected_leaf() -> None:
    references = {
        selector: parse_value_reference(selector)
        for selector in ("context.small", "context.large")
    }
    result = _read_values(
        {"context": {"small": {"count": 3}, "large": "x" * 100}},
        {
            selector: (
                reference.variable,
                tuple((step.kind, step.value) for step in reference.path),
            )
            for selector, reference in references.items()
        },
        max_value_bytes=32,
    )

    assert result.values == {"context.small": _encoded_json({"count": 3})}
    assert result.errors["context.large"].code == "value-too-large"


def test_kernel_projection_bounds_the_aggregate_response() -> None:
    references = {
        selector: parse_value_reference(selector)
        for selector in ("context.first", "context.second")
    }
    result = _read_values(
        {"context": {"first": "x" * 400, "second": "y" * 700}},
        {
            selector: (
                reference.variable,
                tuple((step.kind, step.value) for step in reference.path),
            )
            for selector, reference in references.items()
        },
        max_value_bytes=800,
        max_response_bytes=1_000,
    )

    assert result.values == {"context.first": _encoded_json("x" * 400)}
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
        {selector: _selector_spec(selector) for selector in selectors},
        max_value_bytes=10_000,
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


@pytest.mark.parametrize("kind", ["table", "record-batch"])
def test_kernel_projection_encodes_pyarrow_tables_and_batches(kind: str) -> None:
    import pyarrow as pa

    table = pa.table({"name": ["Ada", "Grace"], "score": [3, None]})
    value = table if kind == "table" else table.to_batches()[0]
    result = _read_values(
        {"frame": value},
        {"frame": _selector_spec("frame")},
        max_value_bytes=10_000,
    )

    payload = cast(dict[str, object], result.values["frame"])
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
        {"frame": _selector_spec("frame")},
        max_value_bytes=10_000,
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
        {"frame": _selector_spec("frame")},
        max_value_bytes=10_000,
    )

    assert result.values == {}
    assert result.errors["frame"].code == expected_code


def test_kernel_projection_encodes_empty_eager_dataframes() -> None:
    import polars as pl
    import pyarrow as pa

    frame = pl.DataFrame(schema={"value": pl.Int64, "label": pl.String})
    result = _read_values(
        {"frame": frame},
        {"frame": _selector_spec("frame")},
        max_value_bytes=10_000,
    )

    payload = cast(dict[str, object], result.values["frame"])
    ipc = base64.b64decode(cast(str, payload["dataUrl"]).partition(",")[2])
    decoded = pa.ipc.open_stream(io.BytesIO(ipc)).read_all()
    assert decoded.column_names == ["value", "label"]
    assert decoded.num_rows == 0


def test_kernel_projection_bounds_arrow_ipc_values() -> None:
    import polars as pl

    result = _read_values(
        {"frame": pl.DataFrame({"value": ["x" * 1_000]})},
        {"frame": _selector_spec("frame")},
        max_value_bytes=100,
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
            {"frame": _selector_spec("frame")},
            max_value_bytes=10_000,
            consumer_id="preview",
            revision="revision-1",
            encoder=encoder,
        )
        first_url = cast(dict[str, object], first.values["frame"])["dataUrl"]
        assert cast(str, first_url).startswith("./@file/")
        assert len(tuple(context.virtual_file_registry.filenames())) == 1

        same = _read_values(
            {"frame": pl.DataFrame({"value": [1]})},
            {"frame": _selector_spec("frame")},
            max_value_bytes=10_000,
            consumer_id="preview",
            revision="revision-1",
            encoder=encoder,
        )
        assert cast(dict[str, object], same.values["frame"])["dataUrl"] == first_url
        assert len(tuple(context.virtual_file_registry.filenames())) == 1

        second = _read_values(
            {"frame": pl.DataFrame({"value": [2]})},
            {"frame": _selector_spec("frame")},
            max_value_bytes=10_000,
            consumer_id="preview",
            revision="revision-1",
            encoder=encoder,
        )
        second_url = cast(dict[str, object], second.values["frame"])["dataUrl"]
        assert second_url != first_url
        assert len(tuple(context.virtual_file_registry.filenames())) == 1

        _read_values(
            {"frame": {"value": 2}},
            {"frame": _selector_spec("frame")},
            max_value_bytes=10_000,
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
            {"frame": _selector_spec("frame")},
            max_value_bytes=10_000,
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
    specifications = {
        "first": _selector_spec("first"),
        "second": _selector_spec("second"),
    }
    with context.install():
        _read_values(
            {"first": pl.DataFrame({"value": [1]})},
            {"first": specifications["first"]},
            specifications,
            max_value_bytes=10_000,
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
                max_value_bytes=10_000,
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

    frame = pl.DataFrame({"value": [1]})
    probe = _read_values(
        {"frame": frame},
        {"frame": _selector_spec("frame")},
        max_value_bytes=10_000,
    )
    arrow_bytes = cast(dict[str, object], probe.values["frame"])["byteLength"]
    assert isinstance(arrow_bytes, int)
    labels = {"first": 0, "second": 1}
    specifications = {
        selector: _selector_spec(selector) for selector in ("frame", *labels)
    }
    raw_json_bytes = sum(
        len(json.dumps(value).encode("utf-8")) for value in labels.values()
    )

    context = _native_output_context()
    encoder = ValueEncoder(context)
    with context.install():
        result = _read_values(
            {"frame": frame, **labels},
            specifications,
            max_value_bytes=10_000,
            max_response_bytes=arrow_bytes + raw_json_bytes,
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
        active = {
            "first": _selector_spec("first"),
            "second": _selector_spec("second"),
        }
        _read_values(
            {"first": pl.DataFrame({"value": [1]})},
            {"first": _selector_spec("first")},
            active,
            max_value_bytes=10_000,
            consumer_id="preview",
            revision="revision-1",
            encoder=encoder,
        )
        first_file = tuple(context.virtual_file_registry.filenames())
        assert len(first_file) == 1

        _read_values(
            {"second": pl.DataFrame({"value": [2]})},
            {"second": _selector_spec("second")},
            active,
            max_value_bytes=10_000,
            consumer_id="preview",
            revision="revision-1",
            encoder=encoder,
        )
        second_file = tuple(context.virtual_file_registry.filenames())
        assert len(second_file) == 2

        _read_values(
            {"second": pl.DataFrame({"value": [2]})},
            {"second": _selector_spec("second")},
            {"second": _selector_spec("second")},
            max_value_bytes=10_000,
            consumer_id="preview",
            revision="revision-1",
            encoder=encoder,
        )
        assert len(tuple(context.virtual_file_registry.filenames())) == 1

        failed = _read_values(
            {"second": pl.DataFrame({"value": [2]}).lazy()},
            {"second": _selector_spec("second")},
            {"second": _selector_spec("second")},
            max_value_bytes=10_000,
            consumer_id="preview",
            revision="revision-1",
            encoder=encoder,
        )
        assert failed.errors["second"].code == "arrow-materialization-required"
        assert tuple(context.virtual_file_registry.filenames()) == ()

        encoder.close()
    context.virtual_file_registry.shutdown()
