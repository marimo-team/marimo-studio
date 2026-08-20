"""Validate opaque Studio browser client identities."""

from __future__ import annotations

import re

_CLIENT_ID = re.compile(r"[A-Za-z0-9_-]{16,128}")


def parse_studio_client_id(value: object) -> str | None:
    if not isinstance(value, str) or _CLIENT_ID.fullmatch(value) is None:
        return None
    return value


__all__ = ["parse_studio_client_id"]
