"""Parse and resolve the restricted selectors used by ``mo-value``."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

from marimo_studio._projections.records import ValuePathStep, ValueReference
from marimo_studio.view_providers import _targets

MAX_OUTPUT_SELECTORS = 100
MAX_SAFE_SELECTOR_INDEX = _targets.MAX_SAFE_TARGET_INDEX
MAX_VALUE_REFERENCE_BYTES = _targets.MAX_TARGET_BYTES
MAX_VALUE_PATH_STEPS = _targets.MAX_TARGET_PATH_STEPS
UnpairedUTF16SurrogateError = _targets.UnpairedUTF16SurrogateError
normalize_utf16_surrogate_pairs = _targets.normalize_utf16_surrogate_pairs


def parse_value_reference(source: str) -> ValueReference:
    """Parse a kernel variable followed by attribute or item selectors."""
    parsed = _targets.parse_value_target(source)
    return ValueReference(
        source=parsed.source,
        variable=parsed.variable,
        path=tuple(ValuePathStep(step.kind, step.value) for step in parsed.path),
    )


def resolve_value_path(root: object, path: tuple[ValuePathStep, ...]) -> object:
    """Resolve a parsed selector with Python attribute and item semantics."""
    current = root
    for step in path:
        if step.kind == "attribute":
            key = step.value
            assert isinstance(key, str)
            if isinstance(current, Mapping) and key in current:
                current = cast(Mapping[object, object], current)[key]
                continue
            try:
                current = getattr(current, key)
            except AttributeError as error:
                raise ValueError(f"Attribute {key!r} is unavailable") from error
            continue
        try:
            current = cast(Any, current)[step.value]
        except (IndexError, KeyError, TypeError) as error:
            raise ValueError(f"Item {step.value!r} is unavailable") from error
    return current


def resolve_value_reference(
    namespace: Mapping[str, object],
    reference: ValueReference,
) -> object:
    """Resolve one permitted selector from a kernel namespace."""
    if reference.variable not in namespace:
        raise ValueError(f"Variable {reference.variable!r} is unavailable")
    return resolve_value_path(namespace[reference.variable], reference.path)
