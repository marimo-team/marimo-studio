"""Projection inspection ports consumed by pure resolution."""

from __future__ import annotations

from typing import Protocol

from marimo_studio.view_providers import MountDeclaration, ViewProject


class ViewMountInspector(Protocol):
    """Return validated projection sites for one provider project."""

    def __call__(self, project: ViewProject) -> tuple[MountDeclaration, ...]: ...
