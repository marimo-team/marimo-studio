"""Inspect one view against provider, artifact, and notebook state."""

from __future__ import annotations

import asyncio

from marimo_studio._projections.resolved import ProjectionDiagnostic
from marimo_studio._views.inspection import inspect_view_project, view_project_state
from marimo_studio._views.records import (
    StudioDiagnostic,
    ViewBuild,
    ViewInspection,
)
from marimo_studio._workspace.models import StudioWorkspace
from marimo_studio._workspace.project_manifest import VIEW_MANIFEST_DOCUMENT
from marimo_studio.view_providers import ProjectDiagnostic


async def inspect_view(studio: StudioWorkspace, name: str) -> ViewInspection:
    """Inspect one provider project against the current notebook graph."""
    from marimo_studio._views.resolve import resolve_studio
    from marimo_studio.view_providers._host import provider_registry

    project = provider_registry().validate_project(studio.view(name))
    inspection = await inspect_view_project(project)
    state = await asyncio.to_thread(view_project_state, project, inspection)
    projection_diagnostics: tuple[ProjectionDiagnostic, ...] = ()
    if not any(item.severity == "error" for item in inspection.diagnostics):
        resolved = await asyncio.to_thread(
            resolve_studio,
            studio,
            view_name=name,
            published_mounts={name: inspection.mounts},
        )
        projection_diagnostics = resolved.view(name).diagnostics
    diagnostics = tuple(_inspection_diagnostic(item) for item in inspection.diagnostics)
    diagnostics += tuple(
        _projection_diagnostic(item, studio) for item in projection_diagnostics
    )
    artifact = state.artifact
    published = state.publication
    build = (
        ViewBuild(
            view=project.name,
            profile=artifact.profile,
            revision=artifact.artifact_revision,
            issues=published.diagnostics,
        )
        if artifact is not None and published is not None
        else None
    )
    return ViewInspection(
        view=project.name,
        provider=project.provider,
        documents=(VIEW_MANIFEST_DOCUMENT, *inspection.editor_documents),
        diagnostics=diagnostics,
        freshness=(
            "current"
            if state.artifact is not None
            and state.project_revision == state.artifact.project_revision
            else "current"
            if state.build.phase == "published"
            else state.build.phase
        ),
        build=build,
    )


def _inspection_diagnostic(diagnostic: ProjectDiagnostic) -> StudioDiagnostic:
    source = diagnostic.source
    return StudioDiagnostic(
        code=diagnostic.code,
        severity=diagnostic.severity,
        message=diagnostic.message,
        hint=diagnostic.hint,
        path=source.path.as_posix() if source is not None else None,
        line=source.line if source is not None else None,
        column=source.column if source is not None else None,
    )


def _projection_diagnostic(
    diagnostic: ProjectionDiagnostic,
    studio: StudioWorkspace,
) -> StudioDiagnostic:
    try:
        path = diagnostic.source.relative_to(studio.notebook.parent).as_posix()
    except ValueError:
        path = diagnostic.source.name
    return StudioDiagnostic(
        code=diagnostic.code,
        severity=diagnostic.severity,
        message=diagnostic.message,
        hint=diagnostic.hint,
        path=path,
        line=diagnostic.line,
        column=diagnostic.column,
    )
