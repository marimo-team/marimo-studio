"""Resolve permitted notebook selectors into bounded browser values."""

from __future__ import annotations

import json
from collections.abc import Collection, Iterable, Mapping

from marimo_export.values import ValueSelector

from marimo_studio._compat.kernel_values.representations import (
    JSON_CODEC,
    EncodedValue,
    ValueEncoder,
)
from marimo_studio._projections.runtime_records import (
    VALUE_LIMITS,
    ValueLimits,
    ValueReadError,
    ValueReadResult,
)


def _read_values(
    namespace: Mapping[str, object],
    selectors: Mapping[str, ValueSelector],
    active: Iterable[str] | None = None,
    *,
    limits: ValueLimits = VALUE_LIMITS,
    consumer_id: str = "",
    revision: str = "",
    encoder: ValueEncoder | None = None,
    rows: Collection[str] = (),
) -> ValueReadResult:
    """Read ``selectors`` as JSON, or as Arrow for tables outside ``rows``."""
    owned_encoder = encoder is None
    if encoder is None:
        encoder = ValueEncoder()
    active_selectors = set(selectors if active is None else active)
    encoder.release_other_revisions(consumer_id, revision)
    encoder.release_inactive(
        consumer_id=consumer_id,
        revision=revision,
        active_selectors=active_selectors,
    )
    values: dict[str, object] = {}
    errors: dict[str, ValueReadError] = {}
    prepared: list[tuple[str, EncodedValue]] = []
    json_read = 0
    arrow_read = 0

    def fail(selector: str, error: ValueReadError) -> None:
        encoder.release_selector(
            consumer_id=consumer_id,
            revision=revision,
            selector=selector,
        )
        errors[selector] = error

    for selector, parsed in selectors.items():
        if selector not in active_selectors:
            fail(
                selector,
                ValueReadError(
                    "inactive-selector",
                    f"Selector {selector!r} is not mounted in the presentation.",
                ),
            )
            continue
        if parsed.root not in namespace:
            fail(
                selector,
                ValueReadError(
                    "missing-variable",
                    f"Variable {parsed.root!r} is not defined",
                ),
            )
            continue
        try:
            value = parsed.resolve(namespace)
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
            limits=limits,
            json_read=json_read,
            arrow_read=arrow_read,
            rows=selector in rows,
        )
        if error is not None:
            fail(selector, error)
            continue
        assert encoded is not None
        if encoded.payload["codec"] == JSON_CODEC:
            json_read += encoded.byte_length
        else:
            arrow_read += encoded.byte_length
        values[selector] = encoded.payload
        prepared.append((selector, encoded))
    result = ValueReadResult(values, errors)
    payload = json.dumps(
        result.to_dict(),
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    if len(payload.encode("utf-8")) <= limits.response_bytes:
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
    for selector in selectors:
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
