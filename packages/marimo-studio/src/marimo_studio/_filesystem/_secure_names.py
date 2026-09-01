"""Allocate bounded sibling names for secure filesystem transactions."""

from __future__ import annotations

import secrets
from typing import Literal

TemporarySiblingKind = Literal[
    "cas",
    "claim",
    "delete",
    "detach",
    "export",
    "export-recovery",
    "restore",
    "rollback",
    "write",
]

_PREFIX = ".marimo-studio-"
_TOKEN_BYTES = 16


def temporary_sibling_prefix(kind: TemporarySiblingKind) -> str:
    """Return the stable prefix for one transaction sibling kind."""
    return f"{_PREFIX}{kind}-"


def temporary_sibling_name(kind: TemporarySiblingKind) -> str:
    """Return a portable transaction sibling independent of the target name."""
    return f"{temporary_sibling_prefix(kind)}{secrets.token_hex(_TOKEN_BYTES)}"
