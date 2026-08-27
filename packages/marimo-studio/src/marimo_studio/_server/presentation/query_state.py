"""Canonical identity for one public notebook query state."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence

_QUERY_OPERATION_PATTERN = re.compile(r"[A-Za-z0-9_-]{1,128}")


def valid_query_operation_id(operation_id: str) -> bool:
    """Return whether an operation ID is safe for bounded kernel retention."""
    return _QUERY_OPERATION_PATTERN.fullmatch(operation_id) is not None


def query_fingerprint(
    query: Mapping[str, str | Sequence[str]],
) -> str:
    """Hash query semantics independently of mapping insertion order."""
    payload = json.dumps(
        query,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()
