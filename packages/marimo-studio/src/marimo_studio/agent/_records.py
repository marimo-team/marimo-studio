"""Records returned by Studio's agent-facing activation API."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ViewActivationResult:
    """The browser selected a view and its preview receiver accepted it."""

    notebook: Path
    view: str
    generation: int
    session_id: str
    client_id: str

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": 2,
            "notebook": str(self.notebook),
            "view": self.view,
            "generation": self.generation,
            "client_id": self.client_id,
            "session_id": self.session_id,
        }
