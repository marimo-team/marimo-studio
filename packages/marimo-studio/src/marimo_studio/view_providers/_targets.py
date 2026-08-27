"""Validate projection targets at provider and artifact boundaries."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Literal

_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_CELL_ALIAS = re.compile(r"[A-Za-z][A-Za-z0-9_-]*")
_INDEX = re.compile(r"(?:0|[1-9][0-9]*)")
_JSON_DECODER = json.JSONDecoder()

MAX_CELL_TARGETS = 256
MAX_VALUE_TARGETS = 100
MAX_TARGET_BYTES = 4_096
MAX_TARGET_PATH_STEPS = 64
MAX_SAFE_TARGET_INDEX = (1 << 53) - 1


class UnpairedUTF16SurrogateError(ValueError):
    """Text contains a UTF-16 surrogate without its required pair."""


@dataclass(frozen=True)
class TargetPathStep:
    kind: Literal["attribute", "item"]
    value: str | int


@dataclass(frozen=True)
class ParsedValueTarget:
    source: str
    variable: str
    path: tuple[TargetPathStep, ...]


def normalize_utf16_surrogate_pairs(value: str) -> str:
    """Return Unicode scalar text and reject unpaired UTF-16 surrogates."""
    normalized: list[str] = []
    index = 0
    while index < len(value):
        codepoint = ord(value[index])
        if 0xD800 <= codepoint <= 0xDBFF:
            if index + 1 >= len(value):
                raise UnpairedUTF16SurrogateError(
                    "text contains an unpaired UTF-16 surrogate"
                )
            trailing = ord(value[index + 1])
            if not 0xDC00 <= trailing <= 0xDFFF:
                raise UnpairedUTF16SurrogateError(
                    "text contains an unpaired UTF-16 surrogate"
                )
            normalized.append(
                chr(0x10000 + ((codepoint - 0xD800) << 10) + (trailing - 0xDC00))
            )
            index += 2
            continue
        if 0xDC00 <= codepoint <= 0xDFFF:
            raise UnpairedUTF16SurrogateError(
                "text contains an unpaired UTF-16 surrogate"
            )
        normalized.append(value[index])
        index += 1
    return "".join(normalized)


def _parse_attribute(value: str, position: int) -> tuple[TargetPathStep, int]:
    selected = _IDENTIFIER.match(value, position + 1)
    if selected is None:
        raise ValueError("dot selection requires an object key")
    if selected.group().startswith("_"):
        raise ValueError("private attribute selection is unavailable")
    return TargetPathStep("attribute", selected.group()), selected.end()


def _parse_item(value: str, position: int) -> tuple[TargetPathStep, int]:
    position += 1
    selected_index = _INDEX.match(value, position)
    if selected_index is not None:
        index = int(selected_index.group())
        if index > MAX_SAFE_TARGET_INDEX:
            raise ValueError("bracket indexes must be JavaScript safe integers")
        step = TargetPathStep("item", index)
        position = selected_index.end()
    elif position < len(value) and value[position] == '"':
        try:
            selected_key, consumed = _JSON_DECODER.raw_decode(value[position:])
        except json.JSONDecodeError as error:
            raise ValueError("bracket object keys must be JSON strings") from error
        if not isinstance(selected_key, str):
            raise ValueError("bracket object keys must be JSON strings")
        step = TargetPathStep(
            "item",
            normalize_utf16_surrogate_pairs(selected_key),
        )
        position += consumed
    else:
        raise ValueError("brackets require a non-negative integer or JSON string")
    if position >= len(value) or value[position] != "]":
        raise ValueError("bracket selection requires a closing ]")
    return step, position + 1


def parse_value_target(source: str) -> ParsedValueTarget:
    """Parse a kernel variable followed by attribute or item selectors."""
    value = normalize_utf16_surrogate_pairs(source.strip())
    if not value:
        raise ValueError("reference must not be empty")
    if len(value.encode("utf-8")) > MAX_TARGET_BYTES:
        raise ValueError(f"reference exceeds the {MAX_TARGET_BYTES}-byte limit")
    root = _IDENTIFIER.match(value)
    if root is None:
        raise ValueError("reference must start with a variable name")
    path: list[TargetPathStep] = []
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
        if len(path) > MAX_TARGET_PATH_STEPS:
            raise ValueError(
                f"reference contains more than {MAX_TARGET_PATH_STEPS} path steps"
            )
    return ParsedValueTarget(value, root.group(), tuple(path))


def validate_projection_target(kind: str, target: object) -> str:
    """Return one canonical target for its declared projection kind."""
    if not isinstance(target, str) or not target or target != target.strip():
        raise ValueError("Mount targets must be canonical non-empty strings")
    if kind == "cell":
        value = normalize_utf16_surrogate_pairs(target)
        if len(value.encode("utf-8")) > MAX_TARGET_BYTES:
            raise ValueError(f"cell target exceeds the {MAX_TARGET_BYTES}-byte limit")
        if (
            value != target
            or value == "_"
            or not (value.isidentifier() or _CELL_ALIAS.fullmatch(value) is not None)
        ):
            raise ValueError("Cell targets must be canonical notebook cell names")
        return value
    if kind in {"value", "output"}:
        parsed = parse_value_target(target)
        if parsed.source != target:
            raise ValueError("Mount targets must be canonical non-empty strings")
        return parsed.source
    raise ValueError("Projection site kind is invalid")
