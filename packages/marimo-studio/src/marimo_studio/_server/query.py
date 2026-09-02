"""Canonicalize notebook query values shared across server adapters."""

from __future__ import annotations

from collections.abc import Iterable

from marimo_studio._delivery.urls import PRIVATE_QUERY_KEYS

CanonicalPublicQuery = tuple[tuple[str, tuple[str, ...]], ...]


def canonical_public_query(
    query: Iterable[tuple[str, str]],
) -> CanonicalPublicQuery:
    """Group public query values in stable key order."""
    values: dict[str, list[str]] = {}
    for key, value in query:
        if key not in PRIVATE_QUERY_KEYS:
            values.setdefault(key, []).append(value)
    return tuple((key, tuple(values[key])) for key in sorted(values))
