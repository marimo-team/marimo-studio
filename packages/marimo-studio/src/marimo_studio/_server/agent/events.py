"""State records for targeted Studio browser operations."""

from __future__ import annotations

from dataclasses import dataclass

from marimo_studio._workspace.ownership import ObservedViewOwner


@dataclass(frozen=True)
class ViewActivation:
    generation: int
    binding_generation: int
    active_view_generation: int
    client_id: str
    session_id: str
    view: str
    owner: ObservedViewOwner | None = None


@dataclass(frozen=True)
class AgentOperations:
    activation: ViewActivation | None
