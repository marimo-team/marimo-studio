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


def is_temporary_name(name: str) -> bool:
    """Return whether ``name`` belongs to an in-progress or interrupted operation."""
    if not name.startswith(_PREFIX):
        return False
    kind, separator, token = name.removeprefix(_PREFIX).partition("-")
    return (
        kind in _KINDS
        and separator == "-"
        and len(token) == _TOKEN_BYTES * 2
        and all(character in "0123456789abcdef" for character in token)
    )
