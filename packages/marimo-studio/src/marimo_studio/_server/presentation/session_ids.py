"""Allocate presentation session IDs and Marimo runtime session IDs.

Each presentation document receives a presentation session ID and a distinct
Marimo runtime session ID. The allocator checks Marimo's current sessions
before issuing either value, then tracks which pair Studio may admit or replay.
This prevents a new document from claiming a runtime session owned by another
server context.

Authority records are process-local and bounded. Expired pending or abandoned
claims are discarded before new bindings are added, current Marimo owners
remain eligible, and closing the allocator rejects new work.
"""

from __future__ import annotations

import hashlib
import secrets
import string
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from threading import RLock
from time import monotonic
from typing import Literal

from marimo_studio._server.ports import SessionOwner, SessionState
from marimo_studio._server.records import ServerContext

_MAX_SESSION_ID_ATTEMPTS = 32
_SESSION_ID_ALPHABET = string.ascii_lowercase + string.digits
_SESSION_ID_SPACE = len(_SESSION_ID_ALPHABET) ** 6
_SESSION_ID_HALF_SPACE = len(_SESSION_ID_ALPHABET) ** 3
_MAX_SESSION_AUTHORITIES = 1024
_SESSION_AUTHORITY_TTL_SECONDS = 300.0


@dataclass
class _SessionAuthority:
    context: ServerContext
    deadline: float
    phase: Literal["pending", "admitting", "active"]
    runtime_session_id: str


class SessionIdAllocator:
    """Issue presentation and Marimo runtime IDs and track their authority."""

    def __init__(
        self,
        *,
        key: bytes | None = None,
        start: int = 0,
        clock: Callable[[], float] = monotonic,
        authority_ttl_seconds: float = _SESSION_AUTHORITY_TTL_SECONDS,
        max_authorities: int = _MAX_SESSION_AUTHORITIES,
    ) -> None:
        if not 0 <= start < _SESSION_ID_SPACE:
            raise ValueError("Session ID allocator start is outside its namespace")
        secret = secrets.token_bytes(32) if key is None else key
        if not secret or len(secret) > 32:
            raise ValueError("Session ID allocator key must contain 1 to 32 bytes")
        if authority_ttl_seconds <= 0:
            raise ValueError("Session authority TTL must be positive")
        if max_authorities <= 0:
            raise ValueError("Session authority capacity must be positive")
        self._key = secret
        self._cursor = start
        self._issued = 0
        self._clock = clock
        self._authority_ttl_seconds = authority_ttl_seconds
        self._max_authorities = max_authorities
        self._authorities: OrderedDict[tuple[str, ...], _SessionAuthority] = (
            OrderedDict()
        )
        self._lock = RLock()
        self._closed = False

    def allocate(
        self,
        context: ServerContext,
        sessions: SessionState,
        *,
        excluded: frozenset[str] = frozenset(),
    ) -> str:
        """Issue one ID outside globally claimed and sibling identities."""
        for _attempt in range(_MAX_SESSION_ID_ATTEMPTS):
            with self._lock:
                self._require_open()
                candidate = self._next()
            if (
                candidate not in excluded
                and sessions.ownership(context, candidate) == "unclaimed"
            ):
                with self._lock:
                    self._require_open()
                    return candidate
        raise RuntimeError("Unable to allocate a distinct Studio session ID")

    def allocate_pair(
        self,
        context: ServerContext,
        sessions: SessionState,
    ) -> tuple[str, str]:
        """Issue one collision-free presentation/runtime pair."""
        presentation_session_id = self.allocate(context, sessions)
        runtime_session_id = self.allocate(
            context,
            sessions,
            excluded=frozenset((presentation_session_id,)),
        )
        return presentation_session_id, runtime_session_id

    def assign_pair(
        self,
        context: ServerContext,
        sessions: SessionState,
        view_name: str,
    ) -> tuple[str, str]:
        """Issue and bind one fresh document/runtime pair."""
        presentation_session_id, runtime_session_id = self.allocate_pair(
            context,
            sessions,
        )
        self._bind_owner(
            context,
            sessions,
            view_name,
            presentation_session_id,
            runtime_session_id,
            phase="pending",
        )
        return presentation_session_id, runtime_session_id

    def assign_runtime(
        self,
        context: ServerContext,
        sessions: SessionState,
        view_name: str,
        presentation_session_id: str,
    ) -> str:
        """Issue and bind a native runtime to an existing presentation ID."""
        runtime_session_id = self.allocate(
            context,
            sessions,
            excluded=frozenset((presentation_session_id,)),
        )
        self._bind_owner(
            context,
            sessions,
            view_name,
            presentation_session_id,
            runtime_session_id,
            phase="pending",
        )
        return runtime_session_id

    def assign_existing(
        self,
        context: ServerContext,
        sessions: SessionState,
        view_name: str,
        runtime_session_id: str,
    ) -> str:
        """Bind a verified replay session to a fresh presentation ID."""
        presentation_session_id = self.allocate(
            context,
            sessions,
            excluded=frozenset((runtime_session_id,)),
        )
        self._bind_owner(
            context,
            sessions,
            view_name,
            presentation_session_id,
            runtime_session_id,
            phase="active",
        )
        return presentation_session_id

    def allows(
        self,
        context: ServerContext,
        sessions: SessionState,
        view_name: str,
        presentation_session_id: str,
        runtime_session_id: str,
    ) -> bool:
        """Check signed owner state without changing its admission phase."""
        ownership = sessions.ownership(context, runtime_session_id)
        with self._lock:
            self._require_open()
            authority = self._authorities.get(
                self._authority_key(
                    context,
                    view_name,
                    presentation_session_id,
                    runtime_session_id,
                )
            )
            if ownership == "foreign":
                return False
            return ownership == "unclaimed" or (
                authority is not None and authority.phase in {"admitting", "active"}
            )

    def authorize(
        self,
        context: ServerContext,
        sessions: SessionState,
        view_name: str,
        presentation_session_id: str,
        runtime_session_id: str,
        *,
        native_admission: bool,
        expected_owner: SessionOwner | None = None,
    ) -> bool:
        """Authorize one signed owner and reject preclaimed native sessions."""
        if expected_owner is None:
            ownership = sessions.ownership(context, runtime_session_id)
        else:
            observed_owner = sessions.owner(context, runtime_session_id)
            if (
                observed_owner.state != expected_owner.state
                or observed_owner.claim is not expected_owner.claim
            ):
                return False
            ownership = expected_owner.state
        authority_ownership = self._authority_ownership(sessions)
        with self._lock:
            self._require_open()
            now = self._clock()
            self._sweep_authorities(authority_ownership, now)
            key = self._authority_key(
                context,
                view_name,
                presentation_session_id,
                runtime_session_id,
            )
            authority = self._authorities.get(key)
            if ownership == "foreign":
                return False
            if authority is None:
                if ownership != "unclaimed":
                    return False
                authority = self._bind(
                    context,
                    view_name,
                    presentation_session_id,
                    runtime_session_id,
                    phase="pending",
                    ownership=authority_ownership,
                    now=now,
                )
            elif ownership == "current" and authority.phase == "pending":
                return False
            if native_admission:
                if authority.phase == "admitting":
                    return False
                authority.phase = "admitting"
            elif authority.phase == "active" and ownership == "unclaimed":
                authority.phase = "pending"
            authority.deadline = now + self._authority_ttl_seconds
            self._authorities.move_to_end(key)
            return True

    def settle_admission(
        self,
        context: ServerContext,
        sessions: SessionState,
        view_name: str,
        presentation_session_id: str,
        runtime_session_id: str,
    ) -> None:
        """Retain a completed native owner or release an aborted admission."""
        ownership = sessions.ownership(context, runtime_session_id)
        with self._lock:
            key = self._authority_key(
                context,
                view_name,
                presentation_session_id,
                runtime_session_id,
            )
            authority = self._authorities.get(key)
            if authority is None:
                return
            if ownership == "current":
                authority.phase = "active"
                authority.deadline = self._clock() + self._authority_ttl_seconds
                self._authorities.move_to_end(key)
            else:
                self._authorities.pop(key, None)

    def cancel_admission(
        self,
        context: ServerContext,
        view_name: str,
        presentation_session_id: str,
        runtime_session_id: str,
    ) -> None:
        """Release a connector-rejected native admission."""
        with self._lock:
            self._authorities.pop(
                self._authority_key(
                    context,
                    view_name,
                    presentation_session_id,
                    runtime_session_id,
                ),
                None,
            )

    def close(self) -> None:
        with self._lock:
            self._closed = True
            self._authorities.clear()

    def _bind_owner(
        self,
        context: ServerContext,
        sessions: SessionState,
        view_name: str,
        presentation_session_id: str,
        runtime_session_id: str,
        *,
        phase: Literal["pending", "admitting", "active"],
    ) -> None:
        ownership = self._authority_ownership(sessions)
        with self._lock:
            self._require_open()
            now = self._clock()
            self._sweep_authorities(ownership, now)
            self._bind(
                context,
                view_name,
                presentation_session_id,
                runtime_session_id,
                phase=phase,
                ownership=ownership,
                now=now,
            )

    def _authority_ownership(
        self,
        sessions: SessionState,
    ) -> dict[tuple[str, ...], Literal["unclaimed", "current", "foreign"]]:
        with self._lock:
            snapshot = tuple(
                (key, authority.context, authority.runtime_session_id)
                for key, authority in self._authorities.items()
            )
        return {
            key: sessions.ownership(context, runtime_session_id)
            for key, context, runtime_session_id in snapshot
        }

    def _bind(
        self,
        context: ServerContext,
        view_name: str,
        presentation_session_id: str,
        runtime_session_id: str,
        *,
        phase: Literal["pending", "admitting", "active"],
        ownership: dict[
            tuple[str, ...],
            Literal["unclaimed", "current", "foreign"],
        ],
        now: float,
    ) -> _SessionAuthority:
        key = self._authority_key(
            context,
            view_name,
            presentation_session_id,
            runtime_session_id,
        )
        authority = _SessionAuthority(
            context=context,
            deadline=now + self._authority_ttl_seconds,
            phase=phase,
            runtime_session_id=runtime_session_id,
        )
        if (
            key not in self._authorities
            and len(self._authorities) >= self._max_authorities
        ):
            inactive = next(
                (
                    candidate
                    for candidate, item in self._authorities.items()
                    if item.phase == "pending"
                    or (item.deadline <= now and ownership.get(candidate) != "current")
                ),
                None,
            )
            if inactive is None:
                raise RuntimeError("Studio session authority capacity was reached")
            self._authorities.pop(inactive)
        self._authorities[key] = authority
        self._authorities.move_to_end(key)
        return authority

    @staticmethod
    def _authority_key(
        context: ServerContext,
        view_name: str,
        presentation_session_id: str,
        runtime_session_id: str,
    ) -> tuple[str, ...]:
        del view_name
        return (
            context.file_key,
            str(context.notebook),
            context.mode,
            context.base_url,
            presentation_session_id,
            runtime_session_id,
        )

    def _sweep_authorities(
        self,
        ownership: dict[
            tuple[str, ...],
            Literal["unclaimed", "current", "foreign"],
        ],
        now: float,
    ) -> None:
        released = [
            key
            for key, authority in self._authorities.items()
            if (
                authority.phase in {"admitting", "active"}
                and authority.deadline <= now
                and ownership.get(key) != "current"
            )
            or (authority.phase == "pending" and authority.deadline <= now)
        ]
        for key in released:
            self._authorities.pop(key, None)

    def _next(self) -> str:
        if self._issued >= _SESSION_ID_SPACE:
            raise RuntimeError("Studio session ID namespace was exhausted")
        value = self._permute(self._cursor)
        self._cursor = (self._cursor + 1) % _SESSION_ID_SPACE
        self._issued += 1
        encoded = ""
        for _digit in range(6):
            value, remainder = divmod(value, len(_SESSION_ID_ALPHABET))
            encoded = _SESSION_ID_ALPHABET[remainder] + encoded
        return f"s_{encoded}"

    def _permute(self, value: int) -> int:
        # A keyed Feistel PRP covers the full six-character base36 domain as two
        # three-character halves. Each counter maps to one collision-free ID while
        # observed IDs do not reveal the next value, without retaining every issued ID.
        left, right = divmod(value, _SESSION_ID_HALF_SPACE)
        for round_index in range(6):
            digest = hashlib.blake2s(
                round_index.to_bytes(1, "big") + right.to_bytes(2, "big"),
                key=self._key,
                digest_size=8,
            ).digest()
            left, right = (
                right,
                (left + int.from_bytes(digest, "big")) % _SESSION_ID_HALF_SPACE,
            )
        return left * _SESSION_ID_HALF_SPACE + right

    def _require_open(self) -> None:
        if self._closed:
            raise RuntimeError("Session ID allocator is closed")
