"""Records returned after Studio shows a view in the browser."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class PreviewAutomationTarget:
    """Browser-owned addressing for one ready preview."""

    preview_url: str
    frame_selector: str


@dataclass(frozen=True)
class ShowResult(PreviewAutomationTarget):
    """The connected Studio tab selected and rendered a view."""

    notebook: Path
    view: str
    generation: int
    session_id: str
    client_id: str

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": 1,
            "notebook": str(self.notebook),
            "view": self.view,
            "generation": self.generation,
            "client_id": self.client_id,
            "session_id": self.session_id,
            "preview_url": self.preview_url,
            "frame_selector": self.frame_selector,
        }
