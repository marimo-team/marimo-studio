"""Name the temporary siblings that file operations create beside their targets."""

from __future__ import annotations

import secrets
from typing import Literal

TemporaryKind = Literal["write", "aside", "stage"]

_PREFIX = ".marimo-studio-"
_KINDS: tuple[TemporaryKind, ...] = ("write", "aside", "stage")
_TOKEN_BYTES = 16


def temporary_name(kind: TemporaryKind) -> str:
    """Return a portable sibling name that no target name can collide with."""
    return f"{_PREFIX}{kind}-{secrets.token_hex(_TOKEN_BYTES)}"


def temporary_kind(name: str) -> TemporaryKind | None:
    """Return the operation kind a temporary sibling name records, or ``None``."""
    if not name.startswith(_PREFIX):
        return None
    kind, separator, token = name.removeprefix(_PREFIX).partition("-")
    if (
        kind in _KINDS
        and separator == "-"
        and len(token) == _TOKEN_BYTES * 2
        and all(character in "0123456789abcdef" for character in token)
    ):
        return kind
    return None


def is_temporary_name(name: str) -> bool:
    """Return whether ``name`` belongs to an in-progress or interrupted operation."""
    return temporary_kind(name) is not None
