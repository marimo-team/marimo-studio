"""Model one observed view name and its workspace owner."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TypeAlias

from marimo_studio._workspace.models import StudioWorkspace
from marimo_studio.errors import (
    ViewGenerationConflictError,
    WorkspaceGenerationConflictError,
)


@dataclass(frozen=True)
class AbsentViewOwner:
    """A catalog generation in which the observed view name was absent."""

    catalog_generation: str

    @property
    def view_generation(self) -> None:
        return None


@dataclass(frozen=True)
class PresentViewOwner:
    """The catalog and view generations for one observed view incarnation."""

    catalog_generation: str
    view_generation: str


ObservedViewOwner: TypeAlias = AbsentViewOwner | PresentViewOwner


def observed_view_owner(
    catalog_generation: str,
    view_generation: str | None,
) -> ObservedViewOwner:
    """Return the owner for a view name observed in one catalog generation."""
    if view_generation is None:
        return AbsentViewOwner(catalog_generation)
    return PresentViewOwner(catalog_generation, view_generation)


def workspace_view_owner(studio: StudioWorkspace, name: str) -> ObservedViewOwner:
    """Capture whether one view name is present in the current workspace."""
    return observed_view_owner(
        studio.catalog_generation,
        studio.view_generations.get(name),
    )


def require_view_owner(
    studio: StudioWorkspace,
    name: str,
    owner: ObservedViewOwner | None,
) -> None:
    """Require a view name to retain the captured presence and generations."""
    if owner is None:
        return
    current_generation = studio.view_generations.get(name)
    if current_generation != owner.view_generation:
        raise ViewGenerationConflictError(name, current_generation)
    if studio.catalog_generation != owner.catalog_generation:
        raise WorkspaceGenerationConflictError()
