"""Mutable records owned by agent activation operations."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import TypeAlias

from marimo_studio._browser_client.records import PreviewAutomationTarget
from marimo_studio._server.agent.clients import StudioClientRegistry
from marimo_studio._server.agent.events import ViewActivation
from marimo_studio.errors import AgentRequestError, MarimoStudioError


def coordinator_closed_error() -> AgentRequestError:
    """Return the terminal outcome for work interrupted by scope shutdown."""
    return AgentRequestError(
        "browser-coordinator-closed",
        "Studio browser coordination stopped before the request completed.",
        status_code=503,
    )


@dataclass(frozen=True)
class PendingActivation:
    """An activation awaiting a browser acknowledgement."""

    activation: ViewActivation


@dataclass(frozen=True)
class AcknowledgedActivation:
    """An applied activation awaiting its request waiter."""

    activation: ViewActivation
    active_view_generation: int
    preview: PreviewAutomationTarget


@dataclass(frozen=True)
class RetainedActivation:
    """An applied activation retained for acknowledgement replay."""

    activation: ViewActivation
    active_view_generation: int
    preview: PreviewAutomationTarget


@dataclass(frozen=True)
class RejectedActivation:
    """A rejected activation awaiting its request waiter."""

    activation: ViewActivation
    error: MarimoStudioError


ActivationOperation: TypeAlias = (
    PendingActivation | AcknowledgedActivation | RetainedActivation | RejectedActivation
)


@dataclass
class AgentOperationStore:
    clients: StudioClientRegistry
    condition: asyncio.Condition = field(default_factory=asyncio.Condition)
    activation_operations: dict[str, ActivationOperation] = field(default_factory=dict)
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
        return isinstance(
            self.activation_operations.get(client_id),
            (PendingActivation, AcknowledgedActivation, RejectedActivation),
        )
