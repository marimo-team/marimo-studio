"""Provider and starter identities shared by discovery consumers."""

from __future__ import annotations


def starter_id(provider: str, key: str) -> str:
    """Qualify one provider-local starter key."""
    return f"{provider}:{key}"
