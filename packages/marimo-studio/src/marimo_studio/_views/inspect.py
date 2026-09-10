"""Inspect one view against provider, artifact, and notebook state."""

from __future__ import annotations

import asyncio

from marimo_studio._artifacts.inputs import project_input_state, project_source_snapshot
from marimo_studio._artifacts.repository import read_artifact_state
from marimo_studio._processes.provider_operation import raise_process_cleanup
from marimo_studio._projections.resolved import ProjectionDiagnostic
from marimo_studio._views.inspection import inspect_view_project
from marimo_studio._views.publication_hold import read_publication_hold
from marimo_studio._views.records import (
    StudioDiagnostic,
    ViewBuild,
    ViewFreshness,
    ViewInspection,
    ViewSourceFile,
)
from marimo_studio._workspace.generation import view_generation
from marimo_studio._workspace.models import StudioDefinition, StudioWorkspace
from marimo_studio._workspace.project_manifest import (
    VIEW_MANIFEST_DOCUMENT,
    load_view_project,
)
from marimo_studio.errors import (
    ConfigurationError,
    MarimoStudioError,
    ViewGenerationConflictError,
    WorkspaceGenerationConflictError,
)
from marimo_studio.view_providers import (
    ProjectDiagnostic,
    ProjectInput,
    ProjectInspection,
)


def inspect_view_manifest(
    studio: StudioDefinition, name: str, error: Exception
) -> ViewInspection:
    """Inspect the manifest repair document and retained publication receipts."""
    from marimo_studio._artifacts.codec import decode_profile_state, read_json
    from marimo_studio._artifacts.paths import assert_secure_path
    from marimo_studio._artifacts.records import ViewBuildState
    from marimo_studio._views.sources import read_view_manifest_with_owner

    observed = read_view_manifest_with_owner(studio, name)
    root = studio.view_root / name
    pointer = root / ".artifacts" / "development.json"
    assert_secure_path(root, pointer, "Artifact profile receipt")
    receipt = (
        decode_profile_state(
            read_json(root, pointer, "artifact profile receipt"), "development"
        )
        if pointer.exists() or pointer.is_symlink()
        else None
    )
    current = read_view_manifest_with_owner(studio, name)
    if current.view_generation != observed.view_generation:
        raise ViewGenerationConflictError(name, current.view_generation)
    if current.catalog_generation != observed.catalog_generation:
        raise WorkspaceGenerationConflictError()
    if current.document.revision != observed.document.revision:
        raise ConfigurationError(
            "View configuration changed during inspection. Inspect again."
        )
    published = receipt.published if receipt is not None else None
    return ViewInspection(
        view=name,
        provider=None,
        documents=(VIEW_MANIFEST_DOCUMENT,),
        diagnostics=(
            StudioDiagnostic(
                code="view-manifest-invalid",
                severity="error",
                message=str(error),
                hint="Repair view.toml, then inspect the view again.",
                path="view.toml",
            ),
        ),
        freshness="stale" if published is not None else "failed",
        build=ViewBuild(
            name, "development", published.artifact_revision, published.diagnostics
        )
        if published is not None
        else None,
        root=root,
        generation=observed.view_generation,
        catalog_generation=observed.catalog_generation,
        project_revision=None,
        published_project_revision=published.project_revision
        if published is not None
        else None,
        latest_build=receipt.build
        if receipt is not None
        else ViewBuildState("development", "unbuilt", None, None, ()),
        files=(
            ViewSourceFile(VIEW_MANIFEST_DOCUMENT.path, observed.document.revision),
        ),
        files_complete=False,
        publication_hold=read_publication_hold(root),
    )


async def inspect_view(studio: StudioWorkspace, name: str) -> ViewInspection:
    """Inspect one provider project against the current notebook graph."""
    from marimo_studio._views.resolve import resolve_studio
    from marimo_studio.view_providers._host import provider_registry

    project = studio.view(name)
    generation = await asyncio.to_thread(view_generation, project)
    if generation != studio.view_generations[name]:
        raise ViewGenerationConflictError(name, generation)
    source = None
    files_complete = False
    try:
        project = await asyncio.to_thread(load_view_project, project.root)
        project = provider_registry().validate_project(project)
        inspection = await inspect_view_project(project)
        source = await asyncio.to_thread(
            project_source_snapshot,
            project,
            inspection,
            provider_registry().get(project.provider).provenance(inspection)
            if not any(item.severity == "error" for item in inspection.diagnostics)
            else None,
        )
        # Reinspect within the captured input state so source-derived mounts and
        # document discovery describe the same files as the returned revisions.
        confirmed = await inspect_view_project(project)
        if inspection != confirmed:
            raise ConfigurationError(
                "View source changed during inspection. Inspect again."
            )
        files_complete = not any(
            item.severity == "error" for item in inspection.diagnostics
        )
    except (MarimoStudioError, OSError, UnicodeError, ValueError) as error:
        raise_process_cleanup(error)
        inspection = ProjectInspection(
            editor_documents=(),
            input_scope=(ProjectInput(VIEW_MANIFEST_DOCUMENT.path, "file"),),
            mounts=(),
            diagnostics=(
                ProjectDiagnostic(
                    code="source-inspection-failed",
                    severity="error",
                    message=str(error),
                    hint="Repair the view source or view.toml, then inspect again.",
                ),
            ),
            build_fingerprint="",
        )
        source = await asyncio.to_thread(
            project_source_snapshot, project, inspection, None
        )
    state = await asyncio.to_thread(read_artifact_state, project, "development")
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
    current_generation = await asyncio.to_thread(view_generation, project)
    if generation != current_generation:
        raise ViewGenerationConflictError(name, current_generation)
    if source.state != await asyncio.to_thread(
        project_input_state, project, source.inspection, allow_missing_manifest=True
    ):
        raise ConfigurationError(
            "View source changed during inspection. Inspect again."
        )
    if files_complete and project != await asyncio.to_thread(
        load_view_project, project.root
    ):
        raise ConfigurationError(
            "View configuration changed during inspection. Inspect again."
        )
    artifact = state.artifact
    published = state.state.published if state.state is not None else None
    revision = source.revision
    freshness: ViewFreshness
    if artifact is not None and revision == artifact.project_revision:
        freshness = "current"
    elif state.build.phase == "building":
        freshness = "building"
    elif artifact is not None:
        freshness = "stale"
    elif state.build.phase == "failed" or any(
        item.severity == "error" for item in diagnostics
    ):
        freshness = "failed"
    else:
        freshness = "unbuilt"
    return ViewInspection(
        view=project.name,
        provider=project.provider,
        documents=(VIEW_MANIFEST_DOCUMENT, *inspection.editor_documents),
        diagnostics=diagnostics,
        freshness=freshness,
        build=(
            ViewBuild(
                view=project.name,
                profile=artifact.profile,
                revision=artifact.artifact_revision,
                issues=published.diagnostics,
            )
            if artifact is not None and published is not None
            else None
        ),
        root=project.root,
        generation=generation,
        catalog_generation=studio.catalog_generation,
        project_revision=revision,
        published_project_revision=artifact.project_revision
        if artifact is not None
        else None,
        latest_build=state.build,
        files=tuple(
            ViewSourceFile(path, revision)
            for path, revision in sorted(source.files.items())
        ),
        files_complete=files_complete,
        publication_hold=await asyncio.to_thread(read_publication_hold, project.root),
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
