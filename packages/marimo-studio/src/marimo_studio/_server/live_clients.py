"""Track live Studio browsers and their Marimo session bindings."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass, field
from enum import Enum

from marimo_studio.errors import AgentRequestError


@dataclass(frozen=True)
class ClientBinding:
    client_id: str
    session_id: str
    connected: bool


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


class PeerStatus(str, Enum):
    CURRENT = "current"
    UNAVAILABLE = "unavailable"
    REBOUND = "rebound"


@dataclass
class LiveClient:
    connections: int = 0
    disconnected_at: float | None = None
    session_id: str | None = None
    active_view: str | None = None
    active_view_generation: int = 0
    binding_generation: int = 0
    binding_count: int = 0
    query_operations: list[str] = field(default_factory=list)


class StudioClientRegistry:
    """Own Studio browser presence, session identity, and query idempotency."""

    def __init__(self, *, disconnect_grace: float = 10.0) -> None:
        self._condition = asyncio.Condition()
        self._clients: dict[str, LiveClient] = {}
        self._session_clients: dict[str, str] = {}
        self._binding_generation = 0
        self._disconnect_grace = disconnect_grace
        self._cleanup_tasks: set[asyncio.Task[None]] = set()
        self._listeners: set[Callable[[], None]] = set()

    def subscribe(self, listener: Callable[[], None]) -> Callable[[], None]:
        self._listeners.add(listener)
        return lambda: self._listeners.discard(listener)

    async def close(self) -> None:
        tasks = tuple(self._cleanup_tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        async with self._condition:
            self._clients.clear()
            self._session_clients.clear()
            self._condition.notify_all()
        self._listeners.clear()

    async def connect(
        self,
        client_id: str,
        active_view: str | None = None,
    ) -> None:
        async with self._condition:
            client = self._clients.setdefault(client_id, LiveClient())
            client.connections += 1
            client.disconnected_at = None
            if active_view is not None and client.active_view != active_view:
                client.active_view = active_view
                client.active_view_generation += 1
            self._condition.notify_all()
        self._publish()

    async def disconnect(self, client_id: str) -> None:
        async with self._condition:
            client = self._clients.get(client_id)
            if client is None:
                return
            client.connections = max(0, client.connections - 1)
            if client.connections == 0:
                client.disconnected_at = time.monotonic()
                self._schedule_cleanup(client_id, client.disconnected_at)
            self._condition.notify_all()
        self._publish()

    async def bind_session(self, session_id: str, client_id: str) -> None:
        async with self._condition:
            client = self._clients.setdefault(client_id, LiveClient())
            if (
                client.session_id == session_id
                and self._session_clients.get(session_id) == client_id
            ):
                self._mark_disconnected(client_id, client)
                return
            if (
                client.session_id is not None
                and self._session_clients.get(client.session_id) == client_id
            ):
                self._session_clients.pop(client.session_id)
            previous_client_id = self._session_clients.get(session_id)
            if previous_client_id is not None and previous_client_id != client_id:
                previous = self._clients.get(previous_client_id)
                if previous is not None:
                    previous.query_operations.clear()
                    if previous.connections == 0:
                        self._discard_locked(previous_client_id)
                    else:
                        previous.session_id = None
                        previous.binding_generation = self._next_binding_generation()
            client.session_id = session_id
            client.binding_generation = self._next_binding_generation()
            client.binding_count += 1
            client.query_operations.clear()
            self._session_clients[session_id] = client_id
            self._mark_disconnected(client_id, client)
            self._condition.notify_all()
        self._publish()

    async def binding_for_session(self, session_id: str) -> ClientBinding | None:
        async with self._condition:
            client_id = self._session_clients.get(session_id)
            client = self._clients.get(client_id) if client_id is not None else None
            if client_id is None or client is None or client.session_id != session_id:
                return None
            return ClientBinding(
                client_id=client_id,
                session_id=session_id,
                connected=client.connections > 0,
            )

    async def session_for_client(self, client_id: str) -> str | None:
        async with self._condition:
            client = self._clients.get(client_id)
            if (
                client is not None
                and client.connections > 0
                and client.session_id is not None
                and self._session_clients.get(client.session_id) == client_id
            ):
                return client.session_id
            return None

    async def target_for_client(self, client_id: str) -> PeerTarget | None:
        async with self._condition:
            return self._target_locked(client_id)

    async def snapshot_for_client(self, client_id: str) -> PeerSnapshot | None:
        async with self._condition:
            target = self._target_locked(client_id)
            client = self._clients.get(client_id)
            if target is None or client is None:
                return None
            return PeerSnapshot(
                target=target,
                binding_replaced=client.binding_count > 1,
            )

    async def claim_query_operation(
        self,
        client_id: str,
        operation_id: str,
        expected_session_id: str,
    ) -> bool | None:
        async with self._condition:
            client = self._clients.get(client_id)
            if (
                client is None
                or client.connections == 0
                or client.session_id != expected_session_id
                or self._session_clients.get(expected_session_id) != client_id
            ):
                return None
            if operation_id in client.query_operations:
                return False
            client.query_operations.append(operation_id)
            if len(client.query_operations) > 256:
                del client.query_operations[:-256]
            return True

    async def release_query_operation(
        self,
        client_id: str,
        operation_id: str,
    ) -> None:
        async with self._condition:
            client = self._clients.get(client_id)
            if client is not None:
                with suppress(ValueError):
                    client.query_operations.remove(operation_id)

    async def wait_for_session_target(
        self,
        session_id: str,
        timeout: float,
    ) -> PeerTarget | None:
        async with self._condition:
            try:
                await asyncio.wait_for(
                    self._condition.wait_for(
                        lambda: self._connected_session_locked(session_id)
                    ),
                    timeout,
                )
            except asyncio.TimeoutError:
                return None
            return self._target_locked(self._session_clients[session_id])

    async def select_target(
        self,
        *,
        session_id: str | None = None,
        client_id: str | None = None,
    ) -> PeerTarget:
        async with self._condition:
            if client_id is not None:
                target = self._target_locked(client_id)
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
                target = self._target_locked(selected) if selected is not None else None
                if target is not None:
                    return target
                raise AgentRequestError(
                    "browser-client-unavailable",
                    "The Studio browser for this Marimo session is not connected.",
                    status_code=409,
                )
            connected = sorted(
                key for key, value in self._clients.items() if value.connections > 0
            )
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
            target = self._target_locked(connected[0])
            assert target is not None
            return target

    def matches(
        self,
        target: PeerTarget,
        *,
        require_connected: bool = False,
        active_view: str | None = None,
        active_view_generation: int | None = None,
    ) -> bool:
        client = self._clients.get(target.client_id)
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
        require_connected: bool = False,
    ) -> PeerStatus:
        client = self._clients.get(target.client_id)
        if client is None or (require_connected and client.connections == 0):
            return PeerStatus.UNAVAILABLE
        if (
            client.binding_generation != target.binding_generation
            or client.session_id != target.session_id
            or (
                target.session_id is not None
                and self._session_clients.get(target.session_id) != target.client_id
            )
        ):
            return PeerStatus.REBOUND
        return PeerStatus.CURRENT

    async def commit_active_view(self, target: PeerTarget, view: str) -> bool:
        async with self._condition:
            client = self._clients.get(target.client_id)
            if (
                not self.matches(target, require_connected=True)
                or client is None
                or (
                    client.active_view_generation != target.active_view_generation
                    and client.active_view != view
                )
            ):
                return False
            if client.active_view != view:
                client.active_view = view
                client.active_view_generation += 1
            self._condition.notify_all()
        self._publish()
        return True

    def activation_matches(
        self,
        target: PeerTarget,
        view: str,
        *,
        require_connected: bool = False,
    ) -> bool:
        client = self._clients.get(target.client_id)
        return (
            self.matches(target, require_connected=require_connected)
            and client is not None
            and (
                client.active_view_generation == target.active_view_generation
                or client.active_view == view
            )
        )

    def _connected_locked(self, client_id: str) -> bool:
        client = self._clients.get(client_id)
        return client is not None and client.connections > 0

    def _target_locked(self, client_id: str) -> PeerTarget | None:
        client = self._clients.get(client_id)
        if client is None or client.connections == 0:
            return None
        session_id = (
            client.session_id
            if client.session_id is not None
            and self._session_clients.get(client.session_id) == client_id
            else None
        )
        return PeerTarget(
            client_id=client_id,
            session_id=session_id,
            binding_generation=client.binding_generation,
            active_view=client.active_view,
            active_view_generation=client.active_view_generation,
        )

    def _connected_session_locked(self, session_id: str) -> bool:
        client_id = self._session_clients.get(session_id)
        return client_id is not None and self._connected_locked(client_id)

    def _next_binding_generation(self) -> int:
        self._binding_generation += 1
        return self._binding_generation

    def _schedule_cleanup(self, client_id: str, disconnected_at: float) -> None:
        task = asyncio.create_task(
            self._cleanup_disconnected_client(client_id, disconnected_at)
        )
        self._cleanup_tasks.add(task)
        task.add_done_callback(self._cleanup_tasks.discard)

    def _mark_disconnected(self, client_id: str, client: LiveClient) -> None:
        if client.connections > 0:
            return
        client.disconnected_at = time.monotonic()
        self._schedule_cleanup(client_id, client.disconnected_at)

    async def _cleanup_disconnected_client(
        self,
        client_id: str,
        disconnected_at: float,
    ) -> None:
        await asyncio.sleep(self._disconnect_grace)
        async with self._condition:
            client = self._clients.get(client_id)
            if (
                client is None
                or client.connections > 0
                or client.disconnected_at != disconnected_at
            ):
                return
            self._discard_locked(client_id)
            self._condition.notify_all()
        self._publish()

    def _discard_locked(self, client_id: str) -> None:
        client = self._clients.pop(client_id, None)
        if client is None:
            return
        if (
            client.session_id is not None
            and self._session_clients.get(client.session_id) == client_id
        ):
            self._session_clients.pop(client.session_id)

    def _publish(self) -> None:
        for listener in tuple(self._listeners):
            listener()


__all__ = [
    "ClientBinding",
    "LiveClient",
    "PeerSnapshot",
    "PeerStatus",
    "PeerTarget",
    "StudioClientRegistry",
]
