"""Canonicalize notebook query values shared across server adapters."""

from __future__ import annotations

import re
from collections.abc import Iterable

from marimo_studio._delivery.urls import PRIVATE_QUERY_KEYS

CanonicalPublicQuery = tuple[tuple[str, tuple[str, ...]], ...]

MAX_SAFE_INTEGER = 9_007_199_254_740_991
_POSITIVE_INTEGER = re.compile(r"[1-9][0-9]{0,15}")


def positive_safe_integer(value: str | None) -> int | None:
    """Parse a positive integer that browser JavaScript represents exactly."""
    if value is None or _POSITIVE_INTEGER.fullmatch(value) is None:
        return None
    parsed = int(value)
    return parsed if parsed <= MAX_SAFE_INTEGER else None


def canonical_public_query(
    query: Iterable[tuple[str, str]],
) -> CanonicalPublicQuery:
    """Group public query values in stable key order."""
    values: dict[str, list[str]] = {}
    for key, value in query:
        if key not in PRIVATE_QUERY_KEYS:
            values.setdefault(key, []).append(value)
    return tuple((key, tuple(values[key])) for key in sorted(values))
