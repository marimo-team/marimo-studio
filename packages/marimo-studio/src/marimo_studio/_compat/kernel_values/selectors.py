"""Resolve permitted notebook selectors into bounded browser values."""

from __future__ import annotations

import json
from collections.abc import Mapping

from marimo_studio._compat.kernel_values.models import DEFAULT_MAX_VALUE_BYTES
from marimo_studio._compat.kernel_values.representations import (
    EncodedValue,
    ValueEncoder,
)
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


def _read_values(
    namespace: Mapping[str, object],
    specifications: Mapping[str, SelectorSpec],
    active_specifications: Mapping[str, SelectorSpec] | None = None,
    *,
    max_value_bytes: int,
    max_response_bytes: int = DEFAULT_MAX_VALUE_BYTES,
    consumer_id: str = "",
    revision: str = "",
    encoder: ValueEncoder | None = None,
) -> ValueReadResult:
    owned_encoder = encoder is None
    if encoder is None:
        encoder = ValueEncoder()
    active_selectors = set(
        specifications if active_specifications is None else active_specifications
    )
    encoder.release_other_revisions(consumer_id, revision)
    encoder.release_inactive(
        consumer_id=consumer_id,
        revision=revision,
        active_selectors=active_selectors,
    )
    values: dict[str, object] = {}
    errors: dict[str, ValueReadError] = {}
    prepared: list[tuple[str, EncodedValue]] = []
    total = 0

    def fail(selector: str, error: ValueReadError) -> None:
        encoder.release_selector(
            consumer_id=consumer_id,
            revision=revision,
            selector=selector,
        )
        errors[selector] = error

    for selector, specification in specifications.items():
        if selector not in active_selectors:
            fail(
                selector,
                ValueReadError(
                    "inactive-selector",
                    f"Selector {selector!r} is not mounted in the presentation.",
                ),
            )
            continue
        reference = parse_value_reference(selector)
        assert specification[0] == reference.variable
        if reference.variable not in namespace:
            fail(
                selector,
                ValueReadError(
                    "missing-variable",
                    f"Variable {reference.variable!r} is not defined",
                ),
            )
            continue
        try:
            value = resolve_value_reference(namespace, reference)
        except Exception as error:
            fail(
                selector,
                ValueReadError(
                    "value-path-unavailable",
                    f"Selector {selector!r} could not be resolved: {error}",
                ),
            )
            continue
        encoded, error = encoder.prepare(
            value,
            consumer_id=consumer_id,
            revision=revision,
            selector=selector,
            max_value_bytes=max_value_bytes,
        )
        if error is not None:
            fail(selector, error)
            continue
        assert encoded is not None
        if total + encoded.byte_length > max_response_bytes:
            encoder.discard(encoded)
            fail(
                selector,
                ValueReadError(
                    "response-too-large",
                    "The value response exceeds the aggregate byte limit.",
                ),
            )
            continue
        total += encoded.byte_length
        values[selector] = encoded.payload
        prepared.append((selector, encoded))
    result = ValueReadResult(values, errors)
    payload = json.dumps(
        result.to_dict(),
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    if len(payload.encode("utf-8")) <= max_response_bytes:
        for index, (selector, encoded) in enumerate(prepared):
            try:
                if encoded.resource is None:
                    encoder.release_selector(
                        consumer_id=consumer_id,
                        revision=revision,
                        selector=selector,
                    )
                else:
                    encoder.commit(encoded)
            except BaseException as error:
                cleanup_errors: list[BaseException] = []
                for _pending_selector, pending in prepared[index:]:
                    try:
                        encoder.discard(pending)
                    except BaseException as cleanup_error:
                        cleanup_errors.append(cleanup_error)
                if owned_encoder:
                    try:
                        encoder.close()
                    except BaseException as cleanup_error:
                        cleanup_errors.append(cleanup_error)
                if cleanup_errors:
                    raise cleanup_errors[0] from error
                raise
        if owned_encoder:
            encoder.close()
        return result
    for _selector, encoded in prepared:
        encoder.discard(encoded)
    for selector in specifications:
        encoder.release_selector(
            consumer_id=consumer_id,
            revision=revision,
            selector=selector,
        )
    if owned_encoder:
        encoder.close()
    return ValueReadResult(
        {},
        {
            "*": ValueReadError(
                "response-too-large",
                "The value response exceeds the aggregate byte limit.",
            )
        },
    )
