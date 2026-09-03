"""Coordinate agent operations against the live Studio client registry."""

from __future__ import annotations

import asyncio

from marimo_studio._server.agent.activation import (
    ActivationAckOutcome,
    ActivationCoordinator,
)
from marimo_studio._server.agent.clients import PeerTarget, StudioClientRegistry
from marimo_studio._server.agent.events import (
    AgentOperations,
    ObservationRequest,
    ViewActivation,
)
from marimo_studio._server.agent.observation import ObservationCoordinator
from marimo_studio._server.agent.store import (
    AcknowledgedActivation,
    AgentOperationStore,
    RetainedActivation,
    coordinator_closed_error,
)
from marimo_studio._validation.evidence import BrowserObservation
from marimo_studio._workspace.ownership import ObservedViewOwner
from marimo_studio.errors import MarimoStudioError


class AgentCoordinator:
    """Own targeted activation and rendered-observation operations."""

    def __init__(self, clients: StudioClientRegistry) -> None:
        self._store = AgentOperationStore(clients)
        self._activations = ActivationCoordinator(self._store)
        self._observations = ObservationCoordinator(self._store)
        self._stop_clients = clients.subscribe(self._client_changed)
        self._notification_tasks: set[asyncio.Task[None]] = set()
        self._closed = False

    async def close(self) -> None:
        async with self._store.condition:
            if self._store.closed:
                return
            self._store.closed = True
            self._closed = True
            self._store.activation_operations.clear()
            self._store.observation_requests.clear()
            self._store.observations.clear()
            self._store.observation_sequences.clear()
            self._store.condition.notify_all()
        self._stop_clients()
        tasks = tuple(self._notification_tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def activate(
        self,
        target: PeerTarget,
        view: str,
        *,
        owner: ObservedViewOwner | None = None,
    ) -> ViewActivation:
        self._require_open()
        return await self._activations.activate(
            target,
            view,
            owner=owner,
        )

    async def acknowledge_activation(
        self,
        client_id: str,
        generation: int,
        view: str,
        *,
        owner: ObservedViewOwner | None = None,
    ) -> ActivationAckOutcome:
        self._require_open()
        return await self._activations.acknowledge(
            client_id,
            generation,
            view,
            owner=owner,
        )

    async def reject_activation(
        self,
        client_id: str,
        generation: int,
        view: str,
        error: MarimoStudioError,
        *,
        owner: ObservedViewOwner | None = None,
    ) -> ActivationAckOutcome:
        self._require_open()
        return await self._activations.reject(
            client_id,
            generation,
            view,
            error,
            owner=owner,
        )

    async def wait_for_activation(
        self,
        activation: ViewActivation,
        timeout: float,
    ) -> None:
        self._require_open()
        await self._activations.wait(activation, timeout)

    async def request_observation(
        self,
        target: PeerTarget,
        view: str,
        runtime: str,
        runtime_instance: str,
        revision: str,
        *,
        active_view_generation: int | None = None,
    ) -> ObservationRequest:
        self._require_open()
        return await self._observations.request(
            target,
            view,
            runtime,
            runtime_instance,
            revision,
            active_view_generation=active_view_generation,
        )

    async def record(self, observation: BrowserObservation) -> bool:
        self._require_open()
        return await self._observations.record(observation)

    async def wait_for_observation(
        self,
        request: ObservationRequest,
        timeout: float,
    ) -> BrowserObservation:
        self._require_open()
        return await self._observations.wait(request, timeout)

    async def pending_operations(
        self,
        target: PeerTarget,
        delivered_activation: int | None,
        delivered_observation: str | None,
    ) -> AgentOperations:
        self._require_open()
        async with self._store.condition:
            self._store.require_open()
            activation = self._activations.pending_for(
                target.client_id,
                delivered_activation,
            )
            if (
                activation is not None
                and activation.binding_generation != target.binding_generation
            ):
                activation = None
            observations = tuple(
                request
                for request in self._observations.pending_for(
                    target.client_id,
                    delivered_observation,
                )
                if request.binding_generation == target.binding_generation
            )
            return AgentOperations(
                activation=activation,
                observations=observations,
            )

    def _client_changed(self) -> None:
        if self._closed:
            return
        task = asyncio.get_running_loop().create_task(self._notify_client_change())
        self._notification_tasks.add(task)
        task.add_done_callback(self._notification_tasks.discard)

    async def _notify_client_change(self) -> None:
        async with self._store.condition:
            if self._store.closed:
                return
            acknowledgements = {
                client_id: operation
                for client_id, operation in self._store.activation_operations.items()
                if isinstance(
                    operation,
                    (AcknowledgedActivation, RetainedActivation),
                )
            }
        retained = await self._store.clients.retained_binding_generations()
        async with self._store.condition:
            if self._store.closed:
                return
            for client_id, acknowledged in acknowledgements.items():
                if (
                    self._store.activation_operations.get(client_id) is acknowledged
                    and retained.get(client_id)
                    != acknowledged.activation.binding_generation
                ):
                    self._store.activation_operations.pop(client_id)
            self._store.condition.notify_all()

    def _require_open(self) -> None:
        if self._closed:
            raise coordinator_closed_error()
