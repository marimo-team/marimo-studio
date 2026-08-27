"""Resolve permitted notebook selectors into bounded JSON values."""

from __future__ import annotations

import json
from collections.abc import Mapping

from marimo_studio._compat.kernel_values.models import DEFAULT_MAX_VALUE_BYTES
from marimo_studio._projections.runtime_records import ValueReadError, ValueReadResult
from marimo_studio._projections.values import (
    parse_value_reference,
    resolve_value_reference,
)
from marimo_studio._server.presentation.ports import SelectorSpec


def normalize_selector_spec(selector: str, value: object) -> SelectorSpec:
    """Validate a serialized selector spec against its canonical target."""
    if (
        not isinstance(value, (list, tuple))
        or len(value) != 2
        or not isinstance(value[0], str)
        or not isinstance(value[1], (list, tuple))
    ):
        raise ValueError("selector spec must contain a variable and path")
    path: list[tuple[str, str | int]] = []
    for raw_step in value[1]:
        if (
            not isinstance(raw_step, (list, tuple))
            or len(raw_step) != 2
            or raw_step[0] not in {"attribute", "item"}
            or not isinstance(raw_step[1], (str, int))
            or isinstance(raw_step[1], bool)
            or (raw_step[0] == "attribute" and not isinstance(raw_step[1], str))
        ):
            raise ValueError("selector spec contains an invalid path step")
        path.append((raw_step[0], raw_step[1]))
    reference = parse_value_reference(selector)
    expected: SelectorSpec = (
        reference.variable,
        tuple((step.kind, step.value) for step in reference.path),
    )
    normalized: SelectorSpec = (value[0], tuple(path))
    if normalized != expected:
        raise ValueError("selector spec does not match its target")
    return normalized


def _encode_value(
    selector: str,
    value: object,
    *,
    max_value_bytes: int,
) -> tuple[object | None, ValueReadError | None, int]:
    try:
        encoded = json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
        )
    except (TypeError, ValueError, OverflowError, RecursionError) as error:
        return (
            None,
            ValueReadError(
                "not-json-serializable",
                (
                    f"Selector {selector!r} resolved to {type(value).__name__}, "
                    f"which cannot be serialized as JSON: {error}"
                ),
            ),
            0,
        )
    size = len(encoded.encode("utf-8"))
    if size > max_value_bytes:
        return (
            None,
            ValueReadError(
                "value-too-large",
                f"Selector {selector!r} exceeds the {max_value_bytes}-byte limit.",
            ),
            0,
        )
    return json.loads(encoded), None, size


def _read_values(
    namespace: Mapping[str, object],
    specifications: Mapping[str, SelectorSpec],
    *,
    max_value_bytes: int,
    max_response_bytes: int = DEFAULT_MAX_VALUE_BYTES,
) -> ValueReadResult:
    values: dict[str, object] = {}
    errors: dict[str, ValueReadError] = {}
    total = 0
    for selector, specification in specifications.items():
        reference = parse_value_reference(selector)
        assert specification[0] == reference.variable
        if reference.variable not in namespace:
            errors[selector] = ValueReadError(
                "missing-variable",
                f"Variable {reference.variable!r} is not defined",
            )
            continue
        try:
            value = resolve_value_reference(namespace, reference)
        except Exception as error:
            errors[selector] = ValueReadError(
                "value-path-unavailable",
                f"Selector {selector!r} could not be resolved: {error}",
            )
            continue
        encoded, error, size = _encode_value(
            selector,
            value,
            max_value_bytes=max_value_bytes,
        )
        if error is not None:
            errors[selector] = error
            continue
        if total + size > max_response_bytes:
            errors[selector] = ValueReadError(
                "response-too-large",
                "The value response exceeds the aggregate byte limit.",
            )
            continue
        total += size
        values[selector] = encoded
    result = ValueReadResult(values, errors)
    payload = json.dumps(
        result.to_dict(),
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    if len(payload.encode("utf-8")) <= max_response_bytes:
        return result
    return ValueReadResult(
        {},
        {
            "*": ValueReadError(
                "response-too-large",
                "The value response exceeds the aggregate byte limit.",
            )
        },
    )
