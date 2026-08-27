"""Identify the Marimo server process that owns browser connections."""

from __future__ import annotations

import hashlib


def server_instance_id(server_token: str) -> str:
    """Return a public identifier derived from one process token."""
    return hashlib.sha256(server_token.encode()).hexdigest()
