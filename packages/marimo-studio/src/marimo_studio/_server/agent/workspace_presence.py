"""Own serialized Studio browser presence and active-view state."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from marimo_studio.errors import AgentRequestError

from .query_operations import QueryOperationState
from .session_bindings import SessionBindingLease


@dataclass(frozen=True)
class PeerTarget:
    client_id: str
    session_id: str | None
    binding_generation: int
    active_view: str | None
    active_view_generation: int


@dataclass(frozen=True)
class PeerSnapshot:
    target: PeerTarget
    binding_replaced: bool


@dataclass(frozen=True)
class WorkspaceStreamLease:
    client_id: str
    stream_generation: int
    lease_id: int


@dataclass(frozen=True)
class _WorkspaceStream:
    generation: int
    active_view: str | None


@dataclass(frozen=True)
class _ActiveViewHandoff:
    operation_id: str
    from_view: str
    to_view: str
    binding_generation: int
    active_view_generation: int
    stream_generation: int


class PeerStatus(str, Enum):
    CURRENT = "current"
    UNAVAILABLE = "unavailable"
    REBOUND = "rebound"


@dataclass
class LiveClient:
    disconnected_at: float | None = None
    disconnect_expired: bool = False
    session_id: str | None = None
    active_view: str | None = None
    active_view_generation: int = 0
    binding_generation: int = 0
    binding_count: int = 0
    binding_lease: SessionBindingLease | None = None
    highest_stream_generation: int = -1
    active_stream: int | None = None
    active_view_handoff: _ActiveViewHandoff | None = None
    terminal_handoffs: dict[str, None] = field(default_factory=dict)
    streams: dict[int, _WorkspaceStream] = field(default_factory=dict)
    query_operations: QueryOperationState = field(default_factory=QueryOperationState)


class WorkspacePresence:
    """Apply browser stream, handoff, view, and target transitions."""

    def __init__(
        self,
        session_clients: dict[str, str],
        *,
        terminal_handoff_limit: int,
    ) -> None:
        self.clients: dict[str, LiveClient] = {}
        self._session_clients = session_clients
        self._terminal_handoff_limit = terminal_handoff_limit
        self._stream_lease_id = 0

    def client(self, client_id: str) -> LiveClient:
        return self.clients.setdefault(client_id, LiveClient())

    def discard(self, client_id: str) -> None:
        self.clients.pop(client_id, None)

    def clear(self) -> None:
        self.clients.clear()

    def reserve_stream(
        self,
        client_id: str,
        stream_generation: int,
        active_view: str | None,
    ) -> WorkspaceStreamLease | None:
        client = self.client(client_id)
        if stream_generation < client.highest_stream_generation:
            return None
        if stream_generation > client.highest_stream_generation:
            client.highest_stream_generation = stream_generation
            for lease_id in tuple(client.streams):
                if lease_id != client.active_stream:
                    client.streams.pop(lease_id)
        self._stream_lease_id += 1
        lease = WorkspaceStreamLease(
            client_id,
            stream_generation,
            self._stream_lease_id,
        )
        client.streams[lease.lease_id] = _WorkspaceStream(
            stream_generation,
            active_view,
        )
        client.disconnected_at = None
        return lease

    def promote_stream(self, lease: WorkspaceStreamLease) -> bool:
        client = self.clients.get(lease.client_id)
        stream = client.streams.get(lease.lease_id) if client is not None else None
        handoff = client.active_view_handoff if client is not None else None
        if (
            client is None
            or stream is None
            or stream.generation != lease.stream_generation
            or stream.generation != client.highest_stream_generation
            or (
                handoff is not None
                and stream.active_view != handoff.to_view
                and not (
                    stream.active_view == handoff.from_view
                    and stream.generation > handoff.stream_generation
                )
            )
        ):
            return False
        client.streams = {lease.lease_id: stream}
        client.active_stream = lease.lease_id
        client.disconnected_at = None
        client.disconnect_expired = False
        if client.active_view != stream.active_view:
            client.active_view = stream.active_view
            client.active_view_generation += 1
        self.terminalize_handoff(client)
        return True

    def release_stream(self, lease: WorkspaceStreamLease) -> LiveClient | None:
        client = self.clients.get(lease.client_id)
        if client is None:
            return None
        stream = client.streams.get(lease.lease_id)
        if stream is None or stream.generation != lease.stream_generation:
            return None
        client.streams.pop(lease.lease_id)
        if client.active_stream == lease.lease_id:
            client.active_stream = None
        if not client.streams:
            self.terminalize_handoff(client)
        return client

    def begin_handoff(
        self,
        client_id: str,
        operation_id: str,
        from_view: str,
        to_view: str,
    ) -> bool:
        client = self.clients.get(client_id)
        if client is None or operation_id in client.terminal_handoffs:
            return False
        active_stream = (
            client.streams.get(client.active_stream)
            if client.active_stream is not None
            else None
        )
        existing = client.active_view_handoff
        if existing is not None:
            return existing == _ActiveViewHandoff(
                operation_id,
                from_view,
                to_view,
                client.binding_generation,
                client.active_view_generation,
                existing.stream_generation,
            )
        if (
            not self.is_connected(client)
            or active_stream is None
            or from_view == to_view
            or client.active_view != from_view
        ):
            return False
        client.active_view_handoff = _ActiveViewHandoff(
            operation_id,
            from_view,
            to_view,
            client.binding_generation,
            client.active_view_generation,
            active_stream.generation,
        )
        return True

    def rollback_handoff(self, client_id: str, operation_id: str) -> tuple[bool, bool]:
        client = self.clients.get(client_id)
        if client is None or operation_id in client.terminal_handoffs:
            return True, False
        handoff = client.active_view_handoff
        self.record_terminal_handoff(client, operation_id)
        if handoff is None:
            return True, True
        if handoff.operation_id != operation_id:
            return False, True
        client.active_view_handoff = None
        return True, True

    def snapshot_for_stream(self, lease: WorkspaceStreamLease) -> PeerSnapshot | None:
        client = self.clients.get(lease.client_id)
        stream = client.streams.get(lease.lease_id) if client is not None else None
        if (
            client is None
            or stream is None
            or client.active_stream != lease.lease_id
            or stream.generation != lease.stream_generation
        ):
            return None
        target = self.target(lease.client_id)
        return (
            PeerSnapshot(target=target, binding_replaced=client.binding_count > 1)
            if target is not None
            else None
        )

    def select_target(
        self,
        *,
        session_id: str | None,
        client_id: str | None,
    ) -> PeerTarget:
        if client_id is not None:
            target = self.target(client_id)
            if target is not None and (
                session_id is None or target.session_id == session_id
            ):
                return target
            raise AgentRequestError(
                "browser-client-unavailable",
                "The selected Studio browser client is not connected.",
                status_code=409,
            )
        if session_id is not None:
            selected = self._session_clients.get(session_id)
            target = self.target(selected) if selected is not None else None
            if target is not None and target.session_id == session_id:
                return target
            raise AgentRequestError(
                "browser-client-unavailable",
                "The Studio browser for this Marimo session is not connected.",
                status_code=409,
            )
        connected = sorted(key for key in self.clients if self.target(key) is not None)
        if not connected:
            raise AgentRequestError(
                "browser-client-unavailable",
                "No Studio browser is connected for this notebook.",
                status_code=409,
            )
        if len(connected) > 1:
            raise AgentRequestError(
                "browser-client-ambiguous",
                "More than one Studio browser is connected for this notebook.",
                status_code=409,
            )
        target = self.target(connected[0])
        assert target is not None
        return target

    def matches(
        self,
        target: PeerTarget,
        *,
        require_connected: bool,
        active_view: str | None,
        active_view_generation: int | None,
    ) -> bool:
        client = self.clients.get(target.client_id)
        return (
            self.status(target, require_connected=require_connected)
            is PeerStatus.CURRENT
            and client is not None
            and (
                active_view_generation is None
                or (
                    client.active_view == active_view
                    and client.active_view_generation == active_view_generation
                )
            )
        )

    def status(
        self,
        target: PeerTarget,
        *,
        require_connected: bool,
    ) -> PeerStatus:
        client = self.clients.get(target.client_id)
        if (
            client is None
            or client.disconnect_expired
            or (require_connected and not self.is_connected(client))
        ):
            return PeerStatus.UNAVAILABLE
        if (
            client.binding_generation != target.binding_generation
            or self._effective_session(target.client_id, client) != target.session_id
        ):
            return PeerStatus.REBOUND
        return (
            PeerStatus.UNAVAILABLE
            if client.active_view_handoff is not None
            else PeerStatus.CURRENT
        )

    def commit_active_view(self, target: PeerTarget, view: str) -> PeerTarget | None:
        client = self.clients.get(target.client_id)
        handoff = client.active_view_handoff if client is not None else None
        if (
            client is None
            or not self.is_connected(client)
            or client.binding_generation != target.binding_generation
            or self._effective_session(target.client_id, client) != target.session_id
            or (
                client.active_view_generation != target.active_view_generation
                and client.active_view != view
            )
            or (handoff is not None and handoff.to_view != view)
        ):
            return None
        if client.active_view != view:
            client.active_view = view
            client.active_view_generation += 1
            if client.active_stream is not None:
                stream = client.streams.get(client.active_stream)
                if stream is not None:
                    client.streams[client.active_stream] = _WorkspaceStream(
                        stream.generation,
                        view,
                    )
        self.terminalize_handoff(client)
        return self.target(target.client_id)

    def activation_matches(
        self,
        target: PeerTarget,
        view: str,
        *,
        require_connected: bool,
    ) -> bool:
        client = self.clients.get(target.client_id)
        return (
            self.matches(
                target,
                require_connected=require_connected,
                active_view=None,
                active_view_generation=None,
            )
            and client is not None
            and (
                client.active_view_generation == target.active_view_generation
                or client.active_view == view
            )
        )

    def target(self, client_id: str | None) -> PeerTarget | None:
        if client_id is None:
            return None
        client = self.clients.get(client_id)
        if (
            client is None
            or not self.is_connected(client)
            or client.active_view_handoff is not None
        ):
            return None
        session_id = self._effective_session(client_id, client)
        return PeerTarget(
            client_id=client_id,
            session_id=session_id,
            binding_generation=client.binding_generation,
            active_view=client.active_view,
            active_view_generation=client.active_view_generation,
        )

    def connected_session(self, session_id: str) -> bool:
        target = self.target(self._session_clients.get(session_id))
        return target is not None and target.session_id == session_id

    def terminalize_handoff(self, client: LiveClient) -> None:
        if client.active_view_handoff is not None:
            self.record_terminal_handoff(
                client,
                client.active_view_handoff.operation_id,
            )
        client.active_view_handoff = None

    @staticmethod
    def expire_disconnect(client: LiveClient) -> None:
        client.disconnect_expired = True

    def record_terminal_handoff(self, client: LiveClient, operation_id: str) -> None:
        client.terminal_handoffs.pop(operation_id, None)
        client.terminal_handoffs[operation_id] = None
        if len(client.terminal_handoffs) > self._terminal_handoff_limit:
            client.terminal_handoffs.pop(next(iter(client.terminal_handoffs)))

    @staticmethod
    def is_connected(client: LiveClient) -> bool:
        return (
            client.active_stream is not None and client.active_stream in client.streams
        )

    def _effective_session(self, client_id: str, client: LiveClient) -> str | None:
        return (
            client.session_id
            if client.session_id is not None
            and client.binding_lease is not None
            and client.binding_lease.current
            and client.binding_lease.native_claim is not None
            and self._session_clients.get(client.session_id) == client_id
            else None
        )
