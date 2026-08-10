"""Hold transient browser evidence and agent view requests."""

from __future__ import annotations

from dataclasses import dataclass
from threading import RLock

from marimo_studio.types import BrowserObservation


@dataclass(frozen=True)
class ViewActivation:
    generation: int
    view: str


class StudioAgentState:
    """Share transient agent state across Studio support requests."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._activation = ViewActivation(0, "")
        self._observations: dict[tuple[str, str], BrowserObservation] = {}
        self._workspace_clients = 0

    def activate(self, view: str) -> ViewActivation:
        with self._lock:
            self._activation = ViewActivation(
                self._activation.generation + 1,
                view,
            )
            return self._activation

    def activation(self) -> ViewActivation:
        with self._lock:
            return self._activation

    def connect_workspace(self) -> None:
        with self._lock:
            self._workspace_clients += 1

    def disconnect_workspace(self) -> None:
        with self._lock:
            self._workspace_clients = max(0, self._workspace_clients - 1)

    def has_workspace_client(self) -> bool:
        with self._lock:
            return self._workspace_clients > 0

    def record(self, observation: BrowserObservation) -> None:
        if observation.runtime is None:
            raise ValueError("A browser observation requires a runtime")
        with self._lock:
            self._observations[(observation.view, observation.runtime)] = observation

    def observation(self, view: str, runtime: str) -> BrowserObservation | None:
        with self._lock:
            return self._observations.get((view, runtime))


__all__ = ["StudioAgentState", "ViewActivation"]
