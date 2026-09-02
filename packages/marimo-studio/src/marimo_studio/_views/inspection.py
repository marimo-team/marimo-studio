"""Inspect provider projects and join them with publication state."""

from __future__ import annotations

from functools import partial
from pathlib import Path

from marimo_studio._artifacts.inputs import project_revision
from marimo_studio._artifacts.records import ViewBuildState
from marimo_studio._artifacts.repository import read_artifact_state
from marimo_studio._processes.cancellation import (
    current_provider_cancellation,
)
from marimo_studio._processes.provider_operation import (
    raise_process_cleanup,
    run_provider_operation,
)
from marimo_studio._processes.provider_runner import create_provider_runner
from marimo_studio._views.inspection_cache import inspection_cache_root
from marimo_studio._views.records import ViewProjectState
from marimo_studio.errors import MarimoStudioError, ViewProjectError
from marimo_studio.view_providers import (
    BuildProfile,
    InspectionRequest,
    MountDeclaration,
    ProjectInspection,
    ProviderCancellation,
    ProviderRunner,
    ViewProject,
)
from marimo_studio.view_providers._host import provider_registry

DEFAULT_INSPECTION_COMMAND_TIMEOUT = 120.0


def inspection_request(
    project: ViewProject,
    *,
    cache_root: Path | None = None,
    cancellation: ProviderCancellation | None = None,
    runner: ProviderRunner | None = None,
    command_timeout: float = DEFAULT_INSPECTION_COMMAND_TIMEOUT,
) -> InspectionRequest:
    """Construct one supervised provider inspection request."""
    control = cancellation or current_provider_cancellation() or ProviderCancellation()
    selected_cache = cache_root or inspection_cache_root(project.provider)
    return InspectionRequest(
        project=project,
        runner=runner or create_provider_runner(project, control, command_timeout),
        cancellation=control,
        cache_root=selected_cache,
        command_timeout=command_timeout,
    )


async def inspect_view_project(project: ViewProject) -> ProjectInspection:
    """Inspect provider-owned source through Studio's normalized record."""
    return await run_provider_operation(partial(inspect_view_project_sync, project))


def inspect_view_project_sync(
    project: ViewProject,
    *,
    cache_root: Path | None = None,
    cancellation: ProviderCancellation | None = None,
    runner: ProviderRunner | None = None,
    command_timeout: float = DEFAULT_INSPECTION_COMMAND_TIMEOUT,
) -> ProjectInspection:
    """Inspect one project from a synchronous worker or process root."""
    request = inspection_request(
        project,
        cache_root=cache_root,
        cancellation=cancellation,
        runner=runner,
        command_timeout=command_timeout,
    )
    return provider_registry().get(project.provider).inspect(request)


def inspect_view_mounts(project: ViewProject) -> tuple[MountDeclaration, ...]:
    """Return validated mounts for workspace projection resolution."""
    try:
        inspection = inspect_view_project_sync(project)
    except ViewProjectError:
        raise
    except (OSError, UnicodeError, ValueError) as error:
        raise_process_cleanup(error)
        raise ViewProjectError(str(error), source=project.manifest) from error
    failure = next(
        (item for item in inspection.diagnostics if item.severity == "error"),
        None,
    )
    if failure is not None:
        raise ViewProjectError(failure.message, source=project.manifest)
    return inspection.mounts


def view_project_state(
    project: ViewProject,
    inspection: ProjectInspection,
    *,
    profile: BuildProfile = "development",
    input_id: str | None = None,
) -> ViewProjectState:
    """Return current source, build attempt, and last-good artifact state."""
    project = provider_registry().validate_project(project)
    artifact_state = read_artifact_state(project, profile)
    artifact = artifact_state.artifact
    build = artifact_state.build
    errors = tuple(item for item in inspection.diagnostics if item.severity == "error")
    try:
        revision = None if errors else input_id
        if revision is None and not errors:
            provider = provider_registry().get(project.provider)
            revision = project_revision(
                project,
                inspection,
                provider.provenance(inspection),
            )
    except (OSError, MarimoStudioError):
        revision = None
    if errors:
        build = ViewBuildState(
            profile=profile,
            phase="stale" if artifact is not None else "failed",
            project_revision=revision,
            artifact_revision=(
                artifact.artifact_revision if artifact is not None else None
            ),
            diagnostics=errors,
            duration_ms=build.duration_ms,
        )
    elif (build.phase == "failed" and build.project_revision is None) or (
        artifact is not None and revision == artifact.project_revision
    ):
        pass
    elif revision != build.project_revision:
        build = ViewBuildState(
            profile=profile,
            phase="stale" if artifact is not None else "unbuilt",
            project_revision=revision,
            artifact_revision=(
                artifact.artifact_revision if artifact is not None else None
            ),
            diagnostics=inspection.diagnostics,
            duration_ms=build.duration_ms,
        )
    publication = (
        artifact_state.state.published if artifact_state.state is not None else None
    )
    return ViewProjectState(revision, build, artifact, publication)
