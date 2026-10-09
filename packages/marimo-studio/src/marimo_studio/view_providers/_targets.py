"""Validate projection targets at provider and artifact boundaries.

Value and output targets are marimo-export value selectors, such as
``metrics.total`` or ``report.rows[0]["label"]``. Cell targets name a notebook
cell.
"""

from __future__ import annotations

import re

from marimo_export.values import MAX_SELECTOR_BYTES, ValueSelector

_CELL_ALIAS = re.compile(r"[A-Za-z][A-Za-z0-9_-]*")

MAX_CELL_TARGETS = 256
MAX_VALUE_TARGETS = 100
# A projection target holds at most one selector, and cell names are shorter.
MAX_TARGET_BYTES = MAX_SELECTOR_BYTES


class UnpairedUTF16SurrogateError(ValueError):
    """Text contains a UTF-16 surrogate without its required pair."""


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


def validate_projection_target(kind: str, target: object) -> str:
    """Return one canonical target for its declared projection kind."""
    if not isinstance(target, str) or not target or target != target.strip():
        raise ValueError("Targets must be non-empty with no surrounding whitespace")
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
        return ValueSelector(target).source
    raise ValueError("Projection site kind is invalid")
