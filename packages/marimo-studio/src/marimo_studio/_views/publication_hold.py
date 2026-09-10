"""Coordinate bounded publication holds across filesystem editing processes."""

from __future__ import annotations

import json
import math
import secrets
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal

from marimo_studio._filesystem.io import atomic_write_text, read_text
from marimo_studio._workspace.generation import view_name_generation
from marimo_studio._workspace.mutation_lock import view_mutation_lock
from marimo_studio.errors import ConfigurationError, ViewGenerationConflictError

DEFAULT_PUBLICATION_HOLD_SECONDS = 300.0
MAX_PUBLICATION_HOLD_SECONDS = 3_600.0


@dataclass(frozen=True)
class PublicationHold:
    """One owner's finite publication hold for a view incarnation."""

    token: str
    owner: str
    generation: str
    expires_at: float
    released: bool = False

    @property
    def status(self) -> Literal["active", "expired", "released"]:
        if self.released:
            return "released"
        return "active" if time.time() < self.expires_at else "expired"

    def to_dict(self) -> dict[str, object]:
        return {
            "token": self.token,
            "owner": self.owner,
            "generation": self.generation,
            "expires_at": self.expires_at,
            "status": self.status,
        }


def publication_hold_path(root: Path) -> Path:
    """Return the control record outside the replaceable view project."""
    return root.parent / ".locks" / f"{root.name}.publication.json"


def read_publication_hold(root: Path) -> PublicationHold | None:
    """Read current, expired, or released coordination for this incarnation."""
    path = publication_hold_path(root)
    try:
        text = read_text(path, root=root.parent)
    except FileNotFoundError:
        return None
    except UnicodeDecodeError as error:
        raise ConfigurationError(f"Invalid publication hold: {path}") from error
    try:
        record = json.loads(text)
        if not isinstance(record, dict) or set(record) != {
            "schema",
            "token",
            "owner",
            "generation",
            "expires_at",
            "released",
        }:
            raise ValueError("unexpected fields")
        if type(record["schema"]) is not int or record["schema"] != 1:
            raise ValueError("invalid schema")
        for key in ("token", "owner", "generation"):
            if not isinstance(record[key], str) or not record[key]:
                raise ValueError(f"invalid {key}")
        expires_at = record["expires_at"]
        if (
            type(expires_at) not in (float, int)
            or not math.isfinite(expires_at)
            or expires_at <= 0
            or type(record["released"]) is not bool
        ):
            raise ValueError("invalid expiry or release state")
        hold = PublicationHold(
            record["token"],
            record["owner"],
            record["generation"],
            float(expires_at),
            record["released"],
        )
    except (ValueError, TypeError, KeyError) as error:
        raise ConfigurationError(f"Invalid publication hold: {path}") from error
    return (
        hold
        if hold.generation == view_name_generation(root.parent, root.name)
        else None
    )


def _write_hold(root: Path, hold: PublicationHold) -> None:
    atomic_write_text(
        publication_hold_path(root),
        json.dumps(
            {
                "schema": 1,
                "token": hold.token,
                "owner": hold.owner,
                "generation": hold.generation,
                "expires_at": hold.expires_at,
                "released": hold.released,
            }
        )
        + "\n",
        root=root.parent,
    )


def _require_generation(root: Path, expected: str | None) -> str:
    try:
        current = view_name_generation(root.parent, root.name)
    except FileNotFoundError as error:
        raise ViewGenerationConflictError(root.name, None) from error
    if expected is not None and current != expected:
        raise ViewGenerationConflictError(root.name, current)
    return current


def acquire_publication_hold(
    root: Path,
    *,
    owner: str,
    ttl: float = DEFAULT_PUBLICATION_HOLD_SECONDS,
    expected_generation: str | None = None,
) -> PublicationHold:
    """Hold replacement publication until token release or a finite expiry."""
    if not isinstance(owner, str) or not owner.strip() or len(owner) > 256:
        raise ValueError("Publication hold owner must contain 1 to 256 characters")
    if (
        isinstance(ttl, bool)
        or not isinstance(ttl, (int, float))
        or not math.isfinite(ttl)
        or not 0 < ttl <= MAX_PUBLICATION_HOLD_SECONDS
    ):
        raise ValueError(
            "Publication hold ttl must be greater than 0 and at most 3600 seconds"
        )
    with view_mutation_lock(root.parent, root.name):
        generation = _require_generation(root, expected_generation)
        current = read_publication_hold(root)
        if current is not None and current.status == "active":
            raise ConfigurationError(
                f"Publication is held by {current.owner!r} until {current.expires_at}. "
                "Release that hold with its token or wait for expiry."
            )
        hold = PublicationHold(
            secrets.token_hex(32), owner, generation, time.time() + ttl
        )
        _write_hold(root, hold)
        return hold


def release_publication_hold(
    root: Path,
    token: str,
    *,
    expected_generation: str | None = None,
) -> PublicationHold | None:
    """Release matching ownership and preserve its idempotent receipt."""
    with view_mutation_lock(root.parent, root.name):
        _require_generation(root, expected_generation)
        current = read_publication_hold(root)
        if current is None:
            return None
        if not secrets.compare_digest(current.token.encode(), token.encode()):
            raise ConfigurationError("Publication hold token belongs to another owner")
        if current.released:
            return current
        released = replace(current, released=True)
        _write_hold(root, released)
        return released
