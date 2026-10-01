"""Model one observed view name and its workspace owner."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TypeAlias

from marimo_studio._workspace.models import StudioWorkspace
from marimo_studio.errors import (
    ViewGenerationConflictError,
    ViewNotFoundError,
    WorkspaceGenerationConflictError,
)
from marimo_studio.view_providers import ViewProject


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


def require_owned_view(
    studio: StudioWorkspace,
    name: str,
    owner: PresentViewOwner | None,
) -> ViewProject:
    """Return the named view for a catalog change its caller still owns.

    A catalog change checks the catalog generation first, so a stale handle
    reports a workspace conflict and the client reloads the whole catalog.
    Without an owner the change acts on the current catalog.
    """
    if owner is not None:
        if studio.catalog_generation != owner.catalog_generation:
            raise WorkspaceGenerationConflictError()
        generation = studio.view_generations.get(name)
        if generation != owner.view_generation:
            raise ViewGenerationConflictError(name, generation)
    project = studio.views.get(name)
    if project is None:
        raise ViewNotFoundError(name, available=tuple(studio.views))
    return project
