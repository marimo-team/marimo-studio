from __future__ import annotations

import math
from typing import cast

import pytest

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
        selectors[0]: "slash",
        selectors[1]: "emoji",
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

    assert result.values == {"context.small": {"count": 3}}
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

    assert result.values == {"context.first": "x" * 400}
    assert result.errors["context.second"].code == "response-too-large"
