"""Select Studio route ownership at ASGI composition time."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

EditRootOwner = Literal["studio", "marimo"]


@dataclass(frozen=True)
class StudioRoutePolicy:
    """Choose which application owns the edit-mode root document."""

    edit_root: EditRootOwner = "studio"

    def __post_init__(self) -> None:
        if self.edit_root not in {"studio", "marimo"}:
            raise ValueError("edit_root must be 'studio' or 'marimo'")


DEFAULT_STUDIO_ROUTE_POLICY = StudioRoutePolicy()
