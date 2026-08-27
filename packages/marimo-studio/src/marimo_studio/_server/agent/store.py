"""Mutable records owned by agent activation and observation operations."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from marimo_studio._server.agent.clients import StudioClientRegistry
from marimo_studio._server.agent.events import ObservationRequest, ViewActivation
from marimo_studio._validation.evidence import BrowserObservation
from marimo_studio.errors import AgentRequestError


def coordinator_closed_error() -> AgentRequestError:
    """Return the terminal outcome for work interrupted by scope shutdown."""
    return AgentRequestError(
        "browser-coordinator-closed",
        "Studio browser coordination stopped before the request completed.",
        status_code=503,
    )


@dataclass(frozen=True)
class ActivationAcknowledgement:
    activation: ViewActivation
    active_view_generation: int


@dataclass
class AgentOperationStore:
    clients: StudioClientRegistry
    condition: asyncio.Condition = field(default_factory=asyncio.Condition)
    activations: dict[str, ViewActivation] = field(default_factory=dict)
    acknowledged_activations: dict[str, ActivationAcknowledgement] = field(
        default_factory=dict
    )
    observation_requests: dict[str, dict[str, ObservationRequest]] = field(
        default_factory=dict
    )
    observations: dict[str, BrowserObservation] = field(default_factory=dict)
    observation_sequences: dict[str, int] = field(default_factory=dict)
    generation: int = 0
    closed: bool = False

    def require_open(self) -> None:
        """Reject work while the condition-protected store is terminal."""
        if self.closed:
            raise coordinator_closed_error()

    def next_generation(self) -> int:
        self.generation += 1
        return self.generation

    def has_operation(self, client_id: str) -> bool:
        return client_id in self.activations or bool(
            self.observation_requests.get(client_id)
        )

    def requests_for(self, client_id: str) -> dict[str, ObservationRequest]:
        return self.observation_requests.setdefault(client_id, {})
