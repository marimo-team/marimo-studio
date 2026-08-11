"""Compose browser-targeted client and agent events."""

from __future__ import annotations

from dataclasses import dataclass

from marimo_studio._server.agent_coordinator import AgentCoordinator
from marimo_studio._server.live_clients import StudioClientRegistry


@dataclass(frozen=True)
class WorkspaceClientEvent:
    kind: str
    payload: dict[str, object]


class WorkspaceClientEventProducer:
    """Track delivery state for one connected Studio workspace stream."""

    def __init__(
        self,
        clients: StudioClientRegistry,
        agents: AgentCoordinator,
        client_id: str,
        active_view: str | None,
    ) -> None:
        self._clients = clients
        self._agents = agents
        self._client_id = client_id
        self._active_view = active_view
        self._delivered_activation: int | None = None
        self._delivered_observation: str | None = None
        self._delivered_binding: int | None = None
        self._connected = False

    async def connect(self) -> None:
        if self._connected:
            return
        await self._clients.connect(self._client_id, self._active_view)
        self._connected = True

    async def close(self) -> None:
        if not self._connected:
            return
        self._connected = False
        await self._clients.disconnect(self._client_id)

    async def poll(self) -> tuple[WorkspaceClientEvent, ...]:
        peer = await self._clients.snapshot_for_client(self._client_id)
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


__all__ = ["WorkspaceClientEvent", "WorkspaceClientEventProducer"]
