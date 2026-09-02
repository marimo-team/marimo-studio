"""Publish one revision-bound presentation artifact."""

from __future__ import annotations

from marimo_studio._artifacts.repository import read_build_state
from marimo_studio._processes.provider_operation import raise_process_cleanup
from marimo_studio._validation.ownership import require_validation_owner
from marimo_studio._views.revisions import PreparedViewProject, capture_presentations
from marimo_studio._workspace import load_studio
from marimo_studio._workspace.models import StudioWorkspace
from marimo_studio.errors import MarimoStudioError, ViewGenerationConflictError
from marimo_studio.view_providers import BuildProfile

PresentationPublication = tuple[dict[str, object], str | None, str | None]


def publish_presentation(
    studio: StudioWorkspace,
    view_name: str,
    prepared: PreparedViewProject | None = None,
    *,
    profile: BuildProfile = "development",
    expected_catalog_generation: str | None = None,
    expected_generation: str | None = None,
) -> PresentationPublication:
    """Publish one artifact and return its build and revision identity."""
    try:
        current = load_studio(studio.config_path)
    except MarimoStudioError:
        project = studio.views.get(view_name)
        return (
            (
                read_build_state(project, profile).to_dict()
                if project is not None
                else _missing_build(profile)
            ),
            None,
            None,
        )
    project = current.views.get(view_name)
    if project is None:
        return _missing_build(profile), None, None
    require_validation_owner(
        current,
        expected_catalog_generation=expected_catalog_generation,
        expected_generations=(
            {view_name: expected_generation}
            if expected_generation is not None
            else None
        ),
    )
    try:
        snapshot = capture_presentations(
            current,
            (view_name,),
            profile=profile,
            prepared={view_name: prepared} if prepared is not None else None,
            expected_generations=(
                {view_name: expected_generation}
                if expected_generation is not None
                else None
            ),
        )
    except ViewGenerationConflictError:
        raise
    except (MarimoStudioError, OSError) as error:
        raise_process_cleanup(error)
        return read_build_state(project, profile).to_dict(), None, None
    with snapshot:
        artifact = snapshot.artifacts[view_name]
        return (
            read_build_state(project, profile).to_dict(),
            snapshot.revision(view_name),
            artifact.artifact_revision,
        )


def _missing_build(profile: BuildProfile) -> dict[str, object]:
    return {
        "schema": 1,
        "profile": profile,
        "phase": "failed",
        "project_revision": None,
        "artifact_revision": None,
        "diagnostics": [],
        "duration_ms": None,
    }
