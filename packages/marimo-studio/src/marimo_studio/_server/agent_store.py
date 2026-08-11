"""Mutable records owned by agent activation and observation operations."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from marimo_studio._server.agent_events import ObservationRequest, ViewActivation
from marimo_studio._server.live_clients import StudioClientRegistry
from marimo_studio.agent_models import BrowserObservation


@dataclass
class AgentOperationStore:
    clients: StudioClientRegistry
    condition: asyncio.Condition = field(default_factory=asyncio.Condition)
    activations: dict[str, ViewActivation] = field(default_factory=dict)
    acknowledged_generations: dict[str, int] = field(default_factory=dict)
    observation_requests: dict[str, dict[str, ObservationRequest]] = field(
        default_factory=dict
    )
    observations: dict[str, BrowserObservation] = field(default_factory=dict)
    observation_sequences: dict[str, int] = field(default_factory=dict)
    generation: int = 0

    def next_generation(self) -> int:
        self.generation += 1
        return self.generation

    def has_operation(self, client_id: str) -> bool:
        return client_id in self.activations or bool(
            self.observation_requests.get(client_id)
        )

    def requests_for(self, client_id: str) -> dict[str, ObservationRequest]:
        return self.observation_requests.setdefault(client_id, {})

    def discard_requests(self, client_id: str) -> None:
        requests = self.observation_requests.pop(client_id, {})
        for request_id in requests:
            self.observations.pop(request_id, None)
            self.observation_sequences.pop(request_id, None)


__all__ = ["AgentOperationStore"]
