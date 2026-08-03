"""Parse and resolve the restricted selectors used by ``mo-value``."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any, cast

from marimo_studio.types import ValuePathStep, ValueReference

_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_INDEX = re.compile(r"(?:0|[1-9][0-9]*)")
_JSON_DECODER = json.JSONDecoder()


def _parse_attribute(value: str, position: int) -> tuple[ValuePathStep, int]:
    selected = _IDENTIFIER.match(value, position + 1)
    if selected is None:
        raise ValueError("dot selection requires an object key")
    return ValuePathStep("attribute", selected.group()), selected.end()


def _parse_item(value: str, position: int) -> tuple[ValuePathStep, int]:
    position += 1
    selected_index = _INDEX.match(value, position)
    if selected_index is not None:
        step = ValuePathStep("item", int(selected_index.group()))
        position = selected_index.end()
    elif position < len(value) and value[position] == '"':
        try:
            selected_key, consumed = _JSON_DECODER.raw_decode(value[position:])
        except json.JSONDecodeError as error:
            raise ValueError("bracket object keys must be JSON strings") from error
        if not isinstance(selected_key, str):
            raise ValueError("bracket object keys must be JSON strings")
        step = ValuePathStep("item", selected_key)
        position += consumed
    else:
        raise ValueError("brackets require a non-negative integer or JSON string")
    if position >= len(value) or value[position] != "]":
        raise ValueError("bracket selection requires a closing ]")
    return step, position + 1


def parse_value_reference(source: str) -> ValueReference:
    """Parse a kernel variable followed by attribute or item selectors."""
    value = source.strip()
    if not value:
        raise ValueError("reference must not be empty")

    root = _IDENTIFIER.match(value)
    if root is None:
        raise ValueError("reference must start with a variable name")
    variable = root.group()
    path: list[ValuePathStep] = []
    position = root.end()

    while position < len(value):
        token = value[position]
        if token == ".":
            step, position = _parse_attribute(value, position)
        elif token == "[":
            step, position = _parse_item(value, position)
        else:
            raise ValueError("reference may contain dot selection and bracket indexing")
        path.append(step)

    return ValueReference(source=value, variable=variable, path=tuple(path))


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
