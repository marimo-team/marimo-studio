"""Own the private projection capability key shared with kernel processes."""

from __future__ import annotations

import os
import secrets
from threading import Lock

_KEY_ENV = "_MARIMO_STUDIO_PROJECTION_AUTHORIZATION_KEY"
_KEY_BYTES = 32
_LOCK = Lock()
_owned_key: bytes | None = None


def initialize_projection_authorization_key() -> None:
    """Create the parent key before Marimo starts any notebook kernel."""
    global _owned_key
    with _LOCK:
        if _owned_key is not None:
            return
        _owned_key = secrets.token_bytes(_KEY_BYTES)
        os.environ[_KEY_ENV] = _owned_key.hex()


def projection_authorization_key() -> bytes:
    """Return the parent key or its inherited child-process copy."""
    if _owned_key is not None:
        return _owned_key
    encoded = os.environ.get(_KEY_ENV)
    if encoded is None:
        raise RuntimeError(
            "The projection authorization key was not initialized before "
            "kernel startup."
        )
    try:
        key = bytes.fromhex(encoded)
    except ValueError as error:
        raise RuntimeError(
            "The inherited projection authorization key is invalid."
        ) from error
    if len(key) != _KEY_BYTES or key.hex() != encoded:
        raise RuntimeError("The inherited projection authorization key is invalid.")
    return key
