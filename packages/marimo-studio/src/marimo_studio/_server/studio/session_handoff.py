"""Authorize a browser-tab handoff into a Studio editor session."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from threading import RLock
from time import monotonic
from typing import Literal

from starlette.types import ASGIApp, Receive, Scope, Send

from marimo_studio._delivery.urls import (
    DOCUMENT_REPLAY_QUERY_PARAM,
    HOST_SESSION_HANDOFF_QUERY_PARAM,
)
from marimo_studio._server.agent.clients import StudioClientRegistry
from marimo_studio._server.agent.session_bindings import SessionBindingLease
from marimo_studio._server.ports import EditorSessionIdentity, SessionState
from marimo_studio._server.presentation.admission import (
    NATIVE_SESSION_ADMISSION_SCOPE_KEY,
    NativeSessionAdmission,
)
from marimo_studio._server.query import canonical_public_query
from marimo_studio._server.records import ServerContext
from marimo_studio._server.server_instance import server_instance_id

_CAPABILITY_PATTERN = re.compile(r"[0-9a-f]{64}")
_PURPOSE = "marimo-studio-host-session-handoff-v1"
_AUTHORIZATION_TTL_SECONDS = 60.0
HostSessionTransition = Literal["native", "studio", "complete", "reset"]


@dataclass
class _HandoffAuthorization:
    claim: object
    expires_at: float
    active: bool = False


class HostSessionHandoffRegistry:
    """Retain signed native-session takeovers until their transport connects."""

    def __init__(self) -> None:
        self._handoffs: dict[tuple[str, ...], _HandoffAuthorization] = {}
        self._lock = RLock()
        self._closed = False

    def authorize(
        self,
        context: ServerContext,
        session_id: str,
        claim: object,
    ) -> None:
        with self._lock:
            if self._closed:
                raise RuntimeError("Host session handoff registry is closed")
            self._prune()
            self._handoffs[_handoff_key(context, session_id)] = _HandoffAuthorization(
                claim,
                monotonic() + _AUTHORIZATION_TTL_SECONDS,
            )

    def consume(
        self,
        context: ServerContext,
        session_id: str,
        claim: object,
    ) -> bool:
        with self._lock:
            if self._closed:
                return False
            self._prune()
            key = _handoff_key(context, session_id)
            handoff = self._handoffs.get(key)
            if handoff is None or handoff.active or handoff.claim is not claim:
                return False
            handoff.active = True
            return True

    def active(self, context: ServerContext, session_id: str) -> bool:
        """Return whether native admission currently owns this handoff."""
        with self._lock:
            handoff = self._handoffs.get(_handoff_key(context, session_id))
            return handoff is not None and handoff.active

    def settle(
        self,
        context: ServerContext,
        session_id: str,
        claim: object,
    ) -> None:
        """Finish one exact native admission attempt."""
        with self._lock:
            key = _handoff_key(context, session_id)
            handoff = self._handoffs.get(key)
            if handoff is not None and handoff.active and handoff.claim is claim:
                self._handoffs.pop(key)

    def contains(
        self,
        context: ServerContext,
        session_id: str,
        claim: object,
    ) -> bool:
        """Return whether an exact takeover is waiting for its transport."""
        with self._lock:
            if self._closed:
                return False
            self._prune()
            handoff = self._handoffs.get(_handoff_key(context, session_id))
            return handoff is not None and not handoff.active and handoff.claim is claim

    def close(self) -> None:
        with self._lock:
            self._closed = True
            self._handoffs.clear()

    def _prune(self) -> None:
        now = monotonic()
        self._handoffs = {
            key: handoff
            for key, handoff in self._handoffs.items()
            if handoff.active or handoff.expires_at > now
        }


@dataclass(frozen=True)
class HostSessionTicket:
    """Bind one browser session to an exact notebook mount."""

    session_id: str
    capability: str

    @classmethod
    def issue(
        cls,
        context: ServerContext,
        session_id: str,
        query: Sequence[tuple[str, str]],
        *,
        public_base_url: str | None = None,
    ) -> HostSessionTicket:
        base_url = context.base_url if public_base_url is None else public_base_url
        audience = json.dumps(
            (
                _PURPOSE,
                context.mode,
                server_instance_id(context.server_token),
                str(context.notebook.resolve()),
                context.file_key,
                base_url,
                session_id,
                canonical_public_query(query),
            ),
            separators=(",", ":"),
        ).encode()
        return cls(
            session_id,
            hmac.new(
                context.server_token.encode(),
                audience,
                hashlib.sha256,
            ).hexdigest(),
        )

    def browser_config(
        self,
        transition: HostSessionTransition,
    ) -> dict[str, str | int]:
        return {
            "schema": 1,
            "capability": self.capability,
            "handoff": HOST_SESSION_HANDOFF_QUERY_PARAM,
            "resume": DOCUMENT_REPLAY_QUERY_PARAM,
            "session": self.session_id,
            "transition": transition,
        }


@dataclass
class HostSessionTransfer:
    """Own one reversible Studio-to-native session transfer."""

    context: ServerContext
    session_id: str
    native_claim: object
    editor_identity: EditorSessionIdentity | None
    studio_owned: bool
    clients: StudioClientRegistry | None
    sessions: SessionState
    handoffs: HostSessionHandoffRegistry
    binding: SessionBindingLease | None = None

    @classmethod
    async def begin(
        cls,
        context: ServerContext,
        session_id: str,
        native_claim: object,
        editor_identity: EditorSessionIdentity | None,
        *,
        studio_owned: bool,
        clients: StudioClientRegistry | None,
        sessions: SessionState,
        handoffs: HostSessionHandoffRegistry,
    ) -> HostSessionTransfer:
        transfer = cls(
            context,
            session_id,
            native_claim,
            editor_identity,
            studio_owned,
            clients,
            sessions,
            handoffs,
        )
        try:
            if studio_owned and clients is not None:
                transfer.binding = await clients.suspend_session_for_host(session_id)
        except BaseException:
            handoffs.settle(context, session_id, native_claim)
            raise
        return transfer

    async def serve(
        self,
        app: ASGIApp,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        admission = NativeSessionAdmission(
            expected_claim=self.native_claim,
            file_key=self.context.file_key,
            mode="current",
            notebook=str(self.context.notebook),
            runtime_session_id=self.session_id,
            replay_on_reconnect=True,
            on_accept=self.commit,
            on_reject=self.rollback,
        )
        try:
            await app(
                {**scope, NATIVE_SESSION_ADMISSION_SCOPE_KEY: admission},
                receive,
                send,
            )
        finally:
            if not admission.settled:
                admission.settled = True
                admission.rejected = True
                self.rollback()

    def commit(self, _native_claim: object) -> None:
        try:
            if self.binding is not None:
                assert self.clients is not None
                self.clients.commit_session_to_host(self.binding)
        finally:
            self._settle()

    def rollback(self) -> None:
        try:
            owner = self.sessions.owner(self.context, self.session_id)
            if (
                self.binding is not None
                and owner.state == "current"
                and owner.claim is self.native_claim
                and self.sessions.editor_identity(self.context, self.session_id)
                == self.editor_identity
            ):
                assert self.clients is not None
                self.clients.restore_session_after_host_failure(self.binding)
        finally:
            self._settle()

    def _settle(self) -> None:
        self.handoffs.settle(self.context, self.session_id, self.native_claim)


def _handoff_key(context: ServerContext, session_id: str) -> tuple[str, ...]:
    return (
        str(context.notebook),
        context.file_key,
        context.base_url,
        server_instance_id(context.server_token),
        session_id,
    )


def host_session_handoff_capability_matches(
    token: str | None,
    context: ServerContext,
    session_id: str,
    query: Sequence[tuple[str, str]],
) -> bool:
    """Validate a server-selected session for this notebook request."""
    if (
        context.mode != "edit"
        or token is None
        or _CAPABILITY_PATTERN.fullmatch(token) is None
    ):
        return False
    expected = HostSessionTicket.issue(
        context,
        session_id,
        query,
    ).capability
    return hmac.compare_digest(token, expected)
