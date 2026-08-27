"""Compose browser-targeted client and agent events."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from marimo_studio._processes.ownership import (
    propagate_cancellation,
    settle_ownership,
)
from marimo_studio._server.agent.clients import (
    StudioClientRegistry,
    WorkspaceStreamLease,
)
from marimo_studio._server.agent.coordinator import AgentCoordinator


@dataclass(frozen=True)
class WorkspaceClientEvent:
    kind: str
    payload: dict[str, object]


class _WorkspaceClientLease:
    def __init__(
        self,
        clients: StudioClientRegistry,
        client_id: str,
        stream_generation: int,
        active_view: str | None,
    ) -> None:
        self._clients = clients
        self._client_id = client_id
        self._stream_generation = stream_generation
        self._active_view = active_view
        self._lock = asyncio.Lock()
        self._lease: WorkspaceStreamLease | None = None
        self._promoted = False
        self._closed = False

    @property
    def lease(self) -> WorkspaceStreamLease | None:
        return self._lease if self._promoted else None

    async def reserve(self) -> bool:
        cancellation: asyncio.CancelledError | None = None
        async with self._lock:
            if self._lease is not None:
                return True
            if self._closed:
                raise RuntimeError("Workspace client lease is closed")
            lease, cancellation = await settle_ownership(
                self._clients.reserve_stream(
                    self._client_id,
                    self._stream_generation,
                    self._active_view,
                )
            )
            self._lease = lease
        propagate_cancellation(cancellation)
        return lease is not None

    async def promote(self) -> bool:
        cancellation: asyncio.CancelledError | None = None
        async with self._lock:
            if self._promoted:
                return True
            if self._closed:
                raise RuntimeError("Workspace client lease is closed")
            lease = self._lease
            if lease is None:
                return False
            promoted, cancellation = await settle_ownership(
                self._clients.promote_stream(lease)
            )
            self._promoted = promoted
        propagate_cancellation(cancellation)
        return promoted

    async def close(self) -> None:
        cancellation: asyncio.CancelledError | None = None
        async with self._lock:
            if self._closed:
                return
            if self._lease is not None:
                _result, cancellation = await settle_ownership(
                    self._clients.release_stream(self._lease)
                )
                self._lease = None
                self._promoted = False
            self._closed = True
        propagate_cancellation(cancellation)


class WorkspaceClientEventProducer:
    """Track delivery state for one connected Studio workspace stream."""

    def __init__(
        self,
        clients: StudioClientRegistry,
        agents: AgentCoordinator,
        client_id: str,
        stream_generation: int,
        active_view: str | None,
    ) -> None:
        self._clients = clients
        self._agents = agents
        self._client_id = client_id
        self._active_view = active_view
        self._lease = _WorkspaceClientLease(
            clients,
            client_id,
            stream_generation,
            active_view,
        )
        self._delivered_activation: int | None = None
        self._delivered_observation: str | None = None
        self._delivered_binding: int | None = None

    async def reserve(self) -> bool:
        return await self._lease.reserve()

    async def connect(self) -> bool:
        if not await self._lease.reserve():
            return False
        return await self._lease.promote()

    async def close(self) -> None:
        await self._lease.close()

    async def poll(self) -> tuple[WorkspaceClientEvent, ...]:
        lease = self._lease.lease
        if lease is None:
            return ()
        peer = await self._clients.snapshot_for_stream(lease)
        if peer is None:
            return ()
        target = peer.target
        operations = await self._agents.pending_operations(
            target,
            self._delivered_activation,
            self._delivered_observation,
        )
        emitted: list[WorkspaceClientEvent] = []
        if operations.activation is not None:
            activation = operations.activation
            self._delivered_activation = activation.generation
            emitted.append(
                WorkspaceClientEvent(
                    "activate",
                    {
                        "schema": 1,
                        "generation": activation.generation,
                        "view": activation.view,
                    },
                )
            )
        for observation in operations.observations:
            self._delivered_observation = observation.request_id
            emitted.append(
                WorkspaceClientEvent(
                    "observe",
                    {
                        "schema": 1,
                        "requestId": observation.request_id,
                        "view": observation.view,
                        "runtime": observation.runtime,
                        "runtimeInstance": observation.runtime_instance,
                        "revision": observation.revision,
                        **(
                            {
                                "activeViewGeneration": (
                                    observation.active_view_generation
                                )
                            }
                            if observation.active_view_generation is not None
                            else {}
                        ),
                    },
                )
            )
        if (
            target.session_id is not None
            and target.binding_generation != self._delivered_binding
        ):
            self._delivered_binding = target.binding_generation
            emitted.append(
                WorkspaceClientEvent(
                    "session",
                    {
                        "schema": 1,
                        "generation": target.binding_generation,
                        "sessionId": target.session_id,
                        "replaced": peer.binding_replaced,
                    },
                )
            )
        return tuple(emitted)
