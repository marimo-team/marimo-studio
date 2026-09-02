"""Validate the workspace and view owners captured by validation callers."""

from __future__ import annotations

from collections.abc import Mapping

from marimo_studio._workspace.models import StudioWorkspace
from marimo_studio.errors import (
    ViewGenerationConflictError,
    WorkspaceGenerationConflictError,
)


def require_validation_owner(
    studio: StudioWorkspace,
    *,
    expected_catalog_generation: str | None = None,
    expected_generations: Mapping[str, str] | None = None,
) -> None:
    """Require validation to retain its observed catalog and view owners."""
    for name, expected in (expected_generations or {}).items():
        current = studio.view_generations.get(name)
        if current != expected:
            raise ViewGenerationConflictError(name, current)
    if (
        expected_catalog_generation is not None
        and studio.catalog_generation != expected_catalog_generation
    ):
        raise WorkspaceGenerationConflictError()
