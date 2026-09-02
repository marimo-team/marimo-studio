"""State records for targeted Studio browser operations."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ViewActivation:
    generation: int
    binding_generation: int
    active_view_generation: int
    client_id: str
    session_id: str
    view: str


@dataclass(frozen=True)
class ObservationRequest:
    request_id: str
    binding_generation: int
    client_id: str
    binding_session_id: str | None
    runtime_session_id: str | None
    view: str
    runtime: str
    runtime_instance: str
    revision: str
    active_view_generation: int | None = None


@dataclass(frozen=True)
class AgentOperations:
    activation: ViewActivation | None
    observations: tuple[ObservationRequest, ...]
