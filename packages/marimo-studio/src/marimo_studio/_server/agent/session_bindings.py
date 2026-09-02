"""Own fixed Studio client-to-native-session binding transitions."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Generic, Protocol, TypeVar


@dataclass(frozen=True)
class ClientBinding:
    client_id: str
    session_id: str
    connected: bool


@dataclass
class SessionBindingLease:
    client_id: str
    session_id: str
    binding_generation: int
    native_claim: object | None = None
    current: bool = True
    rejection_task: asyncio.Task[None] | None = None


@dataclass(frozen=True)
class BindingUpdate:
    lease: SessionBindingLease | None
    changed: bool = False
    replaced: bool = False


class BindingClient(Protocol):
    session_id: str | None
    binding_generation: int
    binding_count: int
    binding_lease: SessionBindingLease | None

    @property
    def active_stream(self) -> int | None: ...

    @property
    def streams(self) -> Mapping[int, object]: ...


BindingClientT = TypeVar("BindingClientT", bound=BindingClient)


class SessionBindings(Generic[BindingClientT]):
    """Mutate binding records while the registry owns serialization."""

    def __init__(
        self,
        clients: dict[str, BindingClientT],
        session_clients: dict[str, str],
    ) -> None:
        self._clients = clients
        self._session_clients = session_clients
        self._generation = 0

    def close(self) -> None:
        for client in self._clients.values():
            if client.binding_lease is not None:
                client.binding_lease.current = False

    def bind(
        self,
        session_id: str,
        client_id: str,
        client: BindingClientT,
        *,
        new_incarnation: bool,
    ) -> BindingUpdate:
        current = client.binding_lease
        if (
            client.session_id == session_id
            and self._session_clients.get(session_id) == client_id
            and current is not None
            and current.current
        ):
            if not new_incarnation or current.native_claim is None:
                return BindingUpdate(current)
            current.current = False
            client.binding_generation = self._next_generation()
            client.binding_count += 1
            client.binding_lease = SessionBindingLease(
                client_id,
                session_id,
                client.binding_generation,
            )
            return BindingUpdate(client.binding_lease, changed=True, replaced=True)
        if (
            client.session_id is not None
            and self._session_clients.get(client.session_id) == client_id
        ) or (
            (owner := self._session_clients.get(session_id)) is not None
            and owner != client_id
        ):
            return BindingUpdate(None)
        client.session_id = session_id
        client.binding_generation = self._next_generation()
        client.binding_count += 1
        client.binding_lease = SessionBindingLease(
            client_id,
            session_id,
            client.binding_generation,
        )
        self._session_clients[session_id] = client_id
        return BindingUpdate(client.binding_lease, changed=True)

    def reject(self, lease: SessionBindingLease) -> bool:
        client = self._exact_client(lease)
        if client is None:
            return False
        lease.current = False
        self._session_clients.pop(lease.session_id)
        client.session_id = None
        client.binding_lease = None
        client.binding_generation = self._next_generation()
        return True

    def current(self, lease: SessionBindingLease) -> bool:
        return self._exact_client(lease) is not None

    def accept(
        self,
        lease: SessionBindingLease,
        native_claim: object,
    ) -> BindingUpdate:
        client = self._exact_client(lease)
        if client is None:
            return BindingUpdate(None)
        if lease.native_claim is native_claim:
            return BindingUpdate(lease)
        if lease.native_claim is None:
            lease.native_claim = native_claim
            return BindingUpdate(lease, changed=True)
        lease.current = False
        client.binding_generation = self._next_generation()
        client.binding_count += 1
        client.binding_lease = SessionBindingLease(
            lease.client_id,
            lease.session_id,
            client.binding_generation,
            native_claim=native_claim,
        )
        return BindingUpdate(client.binding_lease, changed=True, replaced=True)

    def native_closed(self, lease: SessionBindingLease) -> bool:
        client = self._exact_client(lease)
        if client is None:
            return False
        lease.current = False
        self._session_clients.pop(lease.session_id)
        client.session_id = None
        client.binding_lease = None
        client.binding_generation = self._next_generation()
        return True

    def for_session(self, session_id: str) -> ClientBinding | None:
        client_id = self._session_clients.get(session_id)
        client = self._clients.get(client_id) if client_id is not None else None
        if (
            client_id is None
            or client is None
            or client.session_id != session_id
            or client.binding_lease is None
            or not client.binding_lease.current
            or client.binding_lease.native_claim is None
        ):
            return None
        return ClientBinding(
            client_id=client_id,
            session_id=session_id,
            connected=self._is_connected(client),
        )

    def for_client(self, client_id: str) -> ClientBinding | None:
        client = self._clients.get(client_id)
        if (
            client is None
            or client.session_id is None
            or client.binding_lease is None
            or not client.binding_lease.current
            or self._session_clients.get(client.session_id) != client_id
        ):
            return None
        return ClientBinding(
            client_id=client_id,
            session_id=client.session_id,
            connected=self._is_connected(client),
        )

    def session_for_client(self, client_id: str) -> str | None:
        client = self._clients.get(client_id)
        if (
            client is not None
            and self._is_connected(client)
            and client.session_id is not None
            and client.binding_lease is not None
            and client.binding_lease.current
            and client.binding_lease.native_claim is not None
            and self._session_clients.get(client.session_id) == client_id
        ):
            return client.session_id
        return None

    def retained_generations(self) -> dict[str, int]:
        return {
            client_id: client.binding_generation
            for client_id, client in self._clients.items()
        }

    def discard(self, client_id: str) -> None:
        client = self._clients.get(client_id)
        if client is None:
            return
        if client.binding_lease is not None:
            client.binding_lease.current = False
            client.binding_lease = None
        if (
            client.session_id is not None
            and self._session_clients.get(client.session_id) == client_id
        ):
            self._session_clients.pop(client.session_id)

    @staticmethod
    def _is_connected(client: BindingClient) -> bool:
        return (
            client.active_stream is not None and client.active_stream in client.streams
        )

    def _exact_client(self, lease: SessionBindingLease) -> BindingClientT | None:
        client = self._clients.get(lease.client_id)
        return (
            client
            if lease.current
            and client is not None
            and client.binding_lease is lease
            and client.session_id == lease.session_id
            and self._session_clients.get(lease.session_id) == lease.client_id
            else None
        )

    def _next_generation(self) -> int:
        self._generation += 1
        return self._generation
