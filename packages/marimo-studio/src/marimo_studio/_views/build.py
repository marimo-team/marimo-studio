"""Turn one current view project into a verified published artifact.

Studio checks provider availability, inspects the live project, captures the
declared inputs into an immutable snapshot, and runs the provider with bounded
commands and cancellation. Provider output stays in staging until artifact
validation succeeds.

Immediately before publication, Studio confirms that the live source still
matches the snapshot that was built. Matching published output may be reused
after the same check. A failed, cancelled, or superseded build records its
diagnostics while preserving the last successful publication when one exists.
This service backs direct builds, live development, presentation capture, and
static export.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from functools import partial
from pathlib import Path
from typing import Protocol

from marimo_studio._artifacts.inputs import (
    ProjectInputState,
    project_input_state,
    project_revision_snapshot,
    snapshot_revision,
)
from marimo_studio._artifacts.lock import build_lock
from marimo_studio._artifacts.publication import (
    ArtifactCommitRejected,
    capture_artifact_candidate,
    prepare_artifact_build,
    prepare_artifact_publication,
    publish_artifact_candidate,
    record_build_failure,
    record_build_started,
    restore_cached_artifact,
)
from marimo_studio._artifacts.retention import ArtifactLease, prune_artifacts
from marimo_studio._processes.cancellation import (
    current_provider_cancellation,
    provider_cancellation,
)
from marimo_studio._processes.provider_operation import (
    raise_process_cleanup,
    run_provider_operation,
)
from marimo_studio._processes.provider_runner import (
    DEFAULT_PROVIDER_COMMAND_TIMEOUT,
    create_provider_runner,
)
from marimo_studio._processes.supervisor import ProcessCleanupError
from marimo_studio._views.inspection import inspection_request
from marimo_studio._views.records import ViewBuild
from marimo_studio._workspace.mutation_lock import view_build_lock, view_mutation_lock
from marimo_studio._workspace.project_manifest import load_view_project
from marimo_studio.errors import ConfigurationError, ViewProjectError
from marimo_studio.view_providers import (
    BuildProfile,
    BuildRequest,
    BuildResult,
    InspectionRequest,
    ProjectDiagnostic,
    ProjectInspection,
    ProviderAvailability,
    ProviderCancellation,
    ViewProject,
)
from marimo_studio.view_providers._host import provider_registry
from marimo_studio.view_providers._host.records import ProviderProvenance


class BuildProvider(Protocol):
    def availability(
        self,
        project: ViewProject | None = None,
    ) -> ProviderAvailability: ...

    def inspect(self, request: InspectionRequest) -> ProjectInspection: ...

    def build(self, request: BuildRequest) -> BuildResult: ...

    def provenance(self, inspection: ProjectInspection) -> ProviderProvenance: ...


def _inspection_failures(
    inspection: ProjectInspection,
) -> tuple[ProjectDiagnostic, ...]:
    return tuple(
        diagnostic
        for diagnostic in inspection.diagnostics
        if diagnostic.severity == "error"
    )


def _require_buildable_inspection(
    project: ViewProject,
    profile: BuildProfile,
    inspection: ProjectInspection,
    started: float,
    project_revision: str | None = None,
) -> ProjectInspection:
    failures = _inspection_failures(inspection)
    if failures:
        record_build_failure(
            project,
            profile,
            failures,
            started,
            project_revision,
        )
    return inspection


def _inspect_provider(
    project: ViewProject,
    profile: BuildProfile,
    provider: BuildProvider,
    started: float,
) -> ProjectInspection:
    availability = provider.availability(project)
    if not availability.available:
        detail = f": {availability.reason}" if availability.reason else ""
        action = f" {availability.action}" if availability.action else ""
        message = (
            f"View provider {project.provider!r} is unavailable{detail}.{action}"
        ).strip()
        record_build_failure(
            project,
            profile,
            (
                ProjectDiagnostic(
                    code="provider-unavailable",
                    severity="error",
                    message=message,
                    hint=availability.action or "",
                ),
            ),
            started,
        )
    try:
        inspection = provider.inspect(inspection_request(project))
    except Exception as error:
        raise_process_cleanup(error)
        record_build_failure(
            project,
            profile,
            (
                ProjectDiagnostic(
                    code="provider-inspection-failed",
                    severity="error",
                    message=f"View provider inspection failed: {error}",
                    hint="Fix the provider project or reinstall its dependencies.",
                ),
            ),
            started,
        )
    return _require_buildable_inspection(
        project,
        profile,
        inspection,
        started,
    )


def _inspect_snapshot(
    project: ViewProject,
    snapshot: ViewProject,
    profile: BuildProfile,
    provider: BuildProvider,
    started: float,
    cache_root: Path,
) -> ProjectInspection:
    try:
        inspection = provider.inspect(
            inspection_request(snapshot, cache_root=cache_root)
        )
    except Exception as error:
        raise_process_cleanup(error)
        record_build_failure(
            project,
            profile,
            (
                ProjectDiagnostic(
                    code="provider-snapshot-inspection-failed",
                    severity="error",
                    message=f"View input snapshot inspection failed: {error}",
                    hint="Restore provider-declared inputs, then build the view again.",
                ),
            ),
            started,
        )
    return _require_buildable_inspection(
        project,
        profile,
        inspection,
        started,
    )


def _project_stability_failure(
    project: ViewProject,
    inspection: ProjectInspection,
    expected_state: ProjectInputState,
) -> ProjectDiagnostic | None:
    try:
        actual_state = project_input_state(
            project,
            inspection,
            input_paths=expected_state.paths,
        )
    except Exception as error:
        return ProjectDiagnostic(
            code="project-stability-check-failed",
            severity="error",
            message=f"View project stability check failed: {error}",
        )
    if actual_state != expected_state:
        return ProjectDiagnostic(
            code="project-changed-during-build",
            severity="error",
            message=(
                "View project changed while its artifact was built. Build it again."
            ),
        )
    return None


def _capture_commit_state(
    project: ViewProject,
    profile: BuildProfile,
    inspection: ProjectInspection,
    expected_revision: str,
    started: float,
    provider: BuildProvider,
) -> ProjectInputState:
    """Hash live inputs outside the mutation lock and retain cheap identities."""
    try:
        captured = project_revision_snapshot(
            project,
            inspection,
            provider.provenance(inspection),
        )
    except Exception as error:
        record_build_failure(
            project,
            profile,
            (
                ProjectDiagnostic(
                    code="project-stability-check-failed",
                    severity="error",
                    message=f"View project stability check failed: {error}",
                ),
            ),
            started,
            expected_revision,
        )
    if captured.revision != expected_revision:
        record_build_failure(
            project,
            profile,
            (
                ProjectDiagnostic(
                    code="project-changed-during-build",
                    severity="error",
                    message=(
                        "View project changed while its artifact was built. "
                        "Build it again."
                    ),
                ),
            ),
            started,
            expected_revision,
        )
    return captured.state


@contextmanager
def _stable_artifact_commit(
    project: ViewProject,
    profile: BuildProfile,
    inspection: ProjectInspection,
    expected_revision: str,
    expected_state: ProjectInputState,
    started: float,
) -> Iterator[Callable[[], ProjectDiagnostic | None]]:
    """Keep Studio source writes out of the final identity and receipt transaction."""
    with view_mutation_lock(project.root.parent, project.name):
        try:
            yield lambda: _project_stability_failure(
                project,
                inspection,
                expected_state,
            )
        except ArtifactCommitRejected as rejection:
            record_build_failure(
                project,
                profile,
                (rejection.diagnostic,),
                started,
                expected_revision,
            )


def _finish_artifact_commit(
    project: ViewProject,
    lease: ArtifactLease,
) -> ArtifactLease:
    try:
        prune_artifacts(project)
    except BaseException:
        lease.close()
        raise
    return lease


def _load_build_owner(
    project: ViewProject,
    profile: BuildProfile,
) -> tuple[ViewProject, BuildProfile, BuildProvider]:
    registry = provider_registry()
    with view_mutation_lock(project.root.parent, project.name):
        selected = registry.validate_project(load_view_project(project.root))
        selected_profile = registry.validate_profile(selected.provider, profile)
        provider = registry.get(selected.provider)
        current = registry.validate_project(load_view_project(selected.root))
        if current != selected:
            raise ConfigurationError(
                f"View project {selected.name!r} changed before its build started"
            )
    return current, selected_profile, provider


def publish_view(
    project: ViewProject,
    profile: BuildProfile,
    *,
    inspection: ProjectInspection | None = None,
    input_id: str | None = None,
) -> ArtifactLease:
    """Build one profile through provider and artifact owners."""
    if (inspection is None) != (input_id is None):
        raise ConfigurationError(
            "Prepared view builds require both inspection and input_id"
        )
    with view_build_lock(project.root.parent, project.name):
        current, profile, provider = _load_build_owner(project, profile)
        with build_lock(current) as acquired:
            if not acquired:
                raise RuntimeError("Blocking artifact build lock was not acquired")
            return _publish_locked(
                current,
                profile,
                provider,
                inspection=inspection,
                input_id=input_id,
            )


def _publish_locked(
    project: ViewProject,
    profile: BuildProfile,
    provider: BuildProvider,
    *,
    inspection: ProjectInspection | None,
    input_id: str | None,
) -> ArtifactLease:
    started = time.monotonic()
    failures = _inspection_failures(inspection) if inspection is not None else ()
    if failures:
        prepare_artifact_build(project, profile)
        record_build_failure(
            project,
            profile,
            failures,
            started,
            input_id,
        )
    preparation = prepare_artifact_build(project, profile)
    discovered = (
        inspection
        if inspection is not None
        else _inspect_provider(project, profile, provider, started)
    )
    if (
        input_id is not None
        and preparation.current is not None
        and preparation.current.project_revision == input_id
        and preparation.current_snapshot is not None
    ):
        commit_state = _capture_commit_state(
            project,
            profile,
            discovered,
            input_id,
            started,
            provider,
        )
        with _stable_artifact_commit(
            project,
            profile,
            discovered,
            input_id,
            commit_state,
            started,
        ) as confirm_current:
            cached = restore_cached_artifact(
                project,
                profile,
                input_id,
                preparation.current,
                preparation.current_snapshot,
                confirm_current=confirm_current,
            )
        if cached is not None:
            return _finish_artifact_commit(project, cached)
    try:
        candidate_owner = capture_artifact_candidate(project, discovered)
        with candidate_owner as candidate:
            snapshot = candidate.snapshot.project
            snapshot_inspection = (
                inspection
                if inspection is not None
                else _inspect_snapshot(
                    project,
                    snapshot,
                    profile,
                    provider,
                    started,
                    candidate.cache_root,
                )
            )
            provenance = provider.provenance(snapshot_inspection)
            revision = snapshot_revision(
                candidate.snapshot,
                provenance,
            )
            if inspection is not None and (input_id is None or revision != input_id):
                record_build_failure(
                    project,
                    profile,
                    (
                        ProjectDiagnostic(
                            code="project-snapshot-changed",
                            severity="error",
                            message=(
                                "View inputs changed before the build snapshot "
                                "completed."
                            ),
                            hint="Build the view again.",
                        ),
                    ),
                    started,
                    input_id,
                )

            if (
                preparation.current is not None
                and preparation.current.project_revision == revision
                and preparation.current_snapshot is not None
            ):
                commit_state = _capture_commit_state(
                    project,
                    profile,
                    discovered,
                    revision,
                    started,
                    provider,
                )
                with _stable_artifact_commit(
                    project,
                    profile,
                    discovered,
                    revision,
                    commit_state,
                    started,
                ) as confirm_current:
                    cached = restore_cached_artifact(
                        project,
                        profile,
                        revision,
                        preparation.current,
                        preparation.current_snapshot,
                        confirm_current=confirm_current,
                    )
                if cached is not None:
                    return _finish_artifact_commit(project, cached)

            record_build_started(
                project,
                profile,
                revision,
                preparation.recovery_diagnostic,
            )
            cancellation = current_provider_cancellation() or ProviderCancellation()
            command_timeout = DEFAULT_PROVIDER_COMMAND_TIMEOUT
            request = BuildRequest(
                project=snapshot,
                inspection=snapshot_inspection,
                inputs=tuple(candidate.snapshot.input_digests),
                project_revision=revision,
                profile=profile,
                staging_root=candidate.files_root,
                cache_root=candidate.cache_root,
                cancellation=cancellation,
                runner=create_provider_runner(
                    snapshot,
                    cancellation,
                    command_timeout,
                ),
                command_timeout=command_timeout,
            )
            try:
                report = provider.build(request)
            except Exception as error:
                raise_process_cleanup(error)
                record_build_failure(
                    project,
                    profile,
                    (
                        ProjectDiagnostic(
                            code="provider-build-failed",
                            severity="error",
                            message=f"View provider build failed: {error}",
                            hint=(
                                "Fix the provider diagnostic and build the view again."
                            ),
                        ),
                    ),
                    started,
                    revision,
                )
            failures = tuple(
                diagnostic
                for diagnostic in report.diagnostics
                if diagnostic.severity == "error"
            )
            if failures or report.document is None:
                record_build_failure(
                    project,
                    profile,
                    failures
                    or (
                        ProjectDiagnostic(
                            code="artifact-document-missing",
                            severity="error",
                            message="Provider produced no artifact document.",
                        ),
                    ),
                    started,
                    revision,
                )
            prepared = prepare_artifact_publication(
                project,
                profile,
                candidate,
                snapshot_inspection,
                report,
                revision,
                started,
            )
            commit_state = _capture_commit_state(
                project,
                profile,
                discovered,
                revision,
                started,
                provider,
            )
            with _stable_artifact_commit(
                project,
                profile,
                discovered,
                revision,
                commit_state,
                started,
            ) as confirm_current:
                published = publish_artifact_candidate(
                    project,
                    profile,
                    prepared,
                    provenance,
                    report,
                    revision,
                    started,
                    preparation.recovery_diagnostic,
                    (
                        preparation.current_snapshot
                        if preparation.current is not None
                        and preparation.current.artifact_revision
                        == prepared.manifest.artifact_revision
                        else None
                    ),
                    confirm_current=confirm_current,
                )
            return _finish_artifact_commit(project, published)
    except (ViewProjectError, ProcessCleanupError):
        raise
    except (OSError, ConfigurationError) as error:
        record_build_failure(
            project,
            profile,
            (
                ProjectDiagnostic(
                    code="project-snapshot-failed",
                    severity="error",
                    message=str(error),
                    hint="Restore provider-declared inputs, then build the view again.",
                ),
            ),
            started,
            input_id,
        )


def build_view_project_sync(
    project: ViewProject,
    *,
    profile: BuildProfile = "development",
    cancellation: ProviderCancellation | None = None,
) -> ArtifactLease:
    """Publish one artifact from a synchronous application owner."""
    control = cancellation or current_provider_cancellation() or ProviderCancellation()
    with provider_cancellation(control):
        return publish_view(project, profile)


async def build_view_project(
    project: ViewProject,
    *,
    profile: BuildProfile = "development",
) -> ViewBuild:
    """Build one view and return detached publication metadata."""
    lease = await run_provider_operation(
        partial(
            build_view_project_sync,
            project,
            profile=profile,
        ),
        discard=lambda late_lease: late_lease.close(),
    )
    with lease:
        artifact = lease.artifact
        from marimo_studio._artifacts.repository import read_artifact_state

        build = read_artifact_state(project, profile).build
        return ViewBuild(
            view=project.name,
            profile=profile,
            revision=artifact.artifact_revision,
            issues=build.diagnostics,
        )
