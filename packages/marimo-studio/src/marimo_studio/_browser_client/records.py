"""Records returned after Studio shows a view in the browser."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ShowResult:
    """The connected Studio tab selected and rendered a view."""

    notebook: Path
    view: str
    generation: int
    session_id: str
    client_id: str
    preview_url: str | None = None

    @property
    def frame_selector(self) -> str:
        return (
            f'iframe[data-preview-frame][data-preview-view-frame="{self.view}"]'
            ":not([hidden]):not([inert])"
        )

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
