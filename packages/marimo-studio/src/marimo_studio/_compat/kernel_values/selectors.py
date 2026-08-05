"""Resolve permitted notebook selectors into bounded JSON values."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

from marimo_studio._compat.kernel_values.models import DEFAULT_MAX_VALUE_BYTES
from marimo_studio._workspace.config import discover_studio
from marimo_studio._workspace.templates import TemplateParser
from marimo_studio.errors import ConfigurationError
from marimo_studio.types import ValueReadError, ValueReadResult
from marimo_studio.values import parse_value_reference, resolve_value_reference


def _template_selectors(notebook: Path) -> tuple[str, ...] | None:
    studio = discover_studio(notebook)
    if studio is None:
        return None
    selectors: list[str] = []
    for view in studio.views.values():
        parser = TemplateParser()
        try:
            parser.feed(view.template.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ConfigurationError):
            continue
        selectors.extend(ref.source for ref in parser.value_references)
    return tuple(dict.fromkeys(selectors))


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
    selectors: tuple[str, ...],
    allowed: set[str],
    *,
    max_value_bytes: int,
    max_response_bytes: int = DEFAULT_MAX_VALUE_BYTES,
) -> ValueReadResult:
    values: dict[str, object] = {}
    errors: dict[str, ValueReadError] = {}
    total = 0
    for selector in selectors:
        if selector not in allowed:
            errors[selector] = ValueReadError(
                "unknown-selector",
                f"Selector {selector!r} is not present in a configured view.",
            )
            continue
        try:
            reference = parse_value_reference(selector)
        except ValueError as error:
            errors[selector] = ValueReadError("invalid-selector", str(error))
            continue
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
