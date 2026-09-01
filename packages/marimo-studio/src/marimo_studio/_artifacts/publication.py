"""Convert provider-built browser files into a current immutable publication.

Provider output is a candidate, not trusted application state. Studio detaches
its files from provider scratch space, enforces file and path limits, validates
the entry document and complete manifest, and computes a content-addressed
revision from the browser files and notebook mount declarations.

Studio makes the candidate current for the selected build profile only after it
is complete and the caller confirms that the live project still matches the
source that was built. Build-start and failure records remain separate from the
successful publication, so a later failed attempt can report diagnostics while
the last working page remains available.
"""

from __future__ import annotations

import secrets
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from pathlib import Path
from typing import NoReturn

from marimo_studio._artifacts.codec import (
    artifact_manifest,
    artifact_manifest_dict,
    encode_json,
    profile_state,
)
from marimo_studio._artifacts.inputs import ProjectSnapshot, snapshot_project
from marimo_studio._artifacts.lock import artifact_lock
from marimo_studio._artifacts.paths import (
    artifact_files,
    artifact_root,
    assert_secure_path,
    ensure_secure_directory,
    normalized_artifact_path,
)
from marimo_studio._artifacts.records import (
    ArtifactManifest,
    ArtifactPublication,
    ArtifactRevision,
    ArtifactRevisionSnapshot,
    ArtifactTreeIdentity,
    ViewArtifact,
    ViewBuildState,
)
from marimo_studio._artifacts.repository import (
    artifact_from_publication,
    artifact_tree_identity,
    detach_public_files,
    prepare_control_directories,
    prepare_publication_candidate,
    profile_pointer,
    read_artifact_revision_snapshot,
    read_profile_state,
    revision_root,
    validate_document,
    write_profile_state,
    write_profile_state_if_active,
)
from marimo_studio._artifacts.retention import (
    ArtifactLease,
    lease_artifact_locked,
    prune_artifacts,
    prune_artifacts_locked,
    quarantine_artifact_revision_locked,
)
from marimo_studio._filesystem.io import atomic_write_text
from marimo_studio._filesystem.secure import secure_directory
from marimo_studio._processes.cancellation import ProviderOperationControl
from marimo_studio.errors import ConfigurationError, ViewProjectError
from marimo_studio.view_providers import (
    BuildProfile,
    BuildResult,
    ProjectDiagnostic,
    ProjectInspection,
    ViewProject,
)
from marimo_studio.view_providers._host.records import ProviderProvenance


@dataclass(frozen=True)
class ArtifactBuildPreparation:
    current: ViewArtifact | None
    recovery_diagnostic: ProjectDiagnostic | None
    current_snapshot: ArtifactRevisionSnapshot | None


@dataclass(frozen=True)
class ArtifactCandidate:
    generation_root: Path
    snapshot: ProjectSnapshot
    files_root: Path
    cache_root: Path


@dataclass(frozen=True)
class PreparedArtifactPublication:
    publication_root: Path
    manifest: ArtifactManifest
    identity: ArtifactTreeIdentity


class ArtifactCommitRejected(Exception):
    """Reject a receipt when its live project identity is no longer current."""

    def __init__(self, diagnostic: ProjectDiagnostic) -> None:
        super().__init__(diagnostic.message)
        self.diagnostic = diagnostic


def _remove_profile_pointer(project: ViewProject, profile: BuildProfile) -> None:
    pointer = profile_pointer(project, profile)
    with (
        secure_directory(project.root) as filesystem,
        suppress(FileNotFoundError),
    ):
        filesystem.unlink(pointer)


def _cancelled_commit() -> ArtifactCommitRejected:
    return ArtifactCommitRejected(
        ProjectDiagnostic(
            code="build-cancelled",
            severity="error",
            message="The view build was cancelled before publication.",
            hint="Build the view again.",
        )
    )


def record_build_failure(
    project: ViewProject,
    profile: BuildProfile,
    diagnostics: tuple[ProjectDiagnostic, ...],
    started: float,
    project_revision: str | None = None,
) -> NoReturn:
    """Persist a failed attempt while retaining the last-good publication."""
    with artifact_lock(project) as acquired:
        if not acquired:
            raise RuntimeError("Blocking artifact lock was not acquired")
        state = read_profile_state(project, profile)
        published = state.published if state is not None else None
        build = ViewBuildState(
            profile=profile,
            phase="failed",
            project_revision=project_revision,
            artifact_revision=(
                published.artifact_revision if published is not None else None
            ),
            diagnostics=diagnostics,
            duration_ms=round((time.monotonic() - started) * 1_000),
        )
        write_profile_state(project, profile_state(profile, published, build))
    diagnostic = diagnostics[0]
    raise ViewProjectError(
        diagnostic.message,
        source=(
            project.root / diagnostic.source.path
            if diagnostic.source is not None
            else project.manifest
        ),
        line=diagnostic.source.line if diagnostic.source is not None else None,
        column=diagnostic.source.column if diagnostic.source is not None else None,
        hint=diagnostic.hint or None,
    )


def prepare_artifact_build(
    project: ViewProject,
    profile: BuildProfile,
) -> ArtifactBuildPreparation:
    """Recover generated state and return the verified current publication."""
    prepare_control_directories(project)
    recovery: ProjectDiagnostic | None = None
    with artifact_lock(project) as acquired:
        if not acquired:
            raise RuntimeError("Blocking artifact lock was not acquired")
        try:
            state = read_profile_state(project, profile)
            if state is None or state.published is None:
                current_snapshot = None
                current = None
            else:
                current_snapshot = read_artifact_revision_snapshot(
                    project,
                    state.published.artifact_revision,
                )
                if current_snapshot is None:
                    raise ConfigurationError(
                        f"Published artifact is missing for view {project.name!r}: "
                        f"{state.published.artifact_revision}"
                    )
                current = artifact_from_publication(
                    current_snapshot.revision,
                    profile,
                    state.published,
                )
        except (OSError, ConfigurationError) as error:
            _remove_profile_pointer(project, profile)
            prune_artifacts_locked(project)
            current = None
            current_snapshot = None
            recovery = ProjectDiagnostic(
                code="artifact-state-repaired",
                severity="warning",
                message="Generated artifact state was reset before this build.",
                hint=str(error),
            )
        return ArtifactBuildPreparation(current, recovery, current_snapshot)


@contextmanager
def capture_artifact_candidate(
    project: ViewProject,
    inspection: ProjectInspection,
) -> Iterator[ArtifactCandidate]:
    """Capture immutable build inputs and own their temporary generation."""
    generation_root = (
        artifact_root(project) / ".staging" / f"candidate-{secrets.token_hex(16)}"
    )
    with secure_directory(project.root) as filesystem:
        filesystem.create_directory(generation_root)
    try:
        captured = snapshot_project(project, inspection, generation_root / "project")
        files_root = artifact_root(captured.project) / "build" / "files"
        with secure_directory(generation_root) as filesystem:
            filesystem.ensure_directory(files_root)
        cache_root = artifact_root(project) / ".cache"
        ensure_secure_directory(project.root, cache_root, "Artifact provider cache")
        assert_secure_path(
            project.root,
            cache_root,
            "Artifact provider cache",
            final_kind="directory",
        )
        yield ArtifactCandidate(generation_root, captured, files_root, cache_root)
    finally:
        try:
            with secure_directory(project.root) as filesystem:
                filesystem.remove_tree(generation_root)
        except OSError:
            pass


def restore_cached_artifact(
    project: ViewProject,
    profile: BuildProfile,
    project_revision: str,
    cached: ViewArtifact,
    verified: ArtifactRevisionSnapshot,
    control: ProviderOperationControl,
    *,
    confirm_current: Callable[[], ProjectDiagnostic | None],
) -> ArtifactLease | None:
    """Lease a still-current publication after source stability is verified."""
    lease: ArtifactLease | None = None
    try:
        with artifact_lock(project) as acquired:
            if not acquired:
                raise RuntimeError("Blocking artifact lock was not acquired")
            state = read_profile_state(project, profile)
            if (
                state is None
                or state.published is None
                or cached.project_revision != project_revision
                or state.published.artifact_revision != cached.artifact_revision
                or verified.revision.manifest.artifact_revision
                != cached.artifact_revision
            ):
                return None
            current_identity = artifact_tree_identity(
                project,
                revision_root(project, cached.artifact_revision),
            )
            if current_identity != verified.identity:
                return None
            lease = lease_artifact_locked(project, cached)
            prune_artifacts_locked(project)
            rejection = confirm_current()
            if rejection is not None:
                raise ArtifactCommitRejected(rejection)
            restored = ViewBuildState(
                profile=profile,
                phase="published",
                project_revision=project_revision,
                artifact_revision=cached.artifact_revision,
                diagnostics=state.published.diagnostics,
                duration_ms=state.published.duration_ms,
            )
            committed = write_profile_state_if_active(
                project,
                profile_state(profile, state.published, restored),
                control,
            )
            if not committed:
                raise _cancelled_commit()
        return lease
    except BaseException:
        if lease is not None:
            lease.close()
        raise


def record_build_started(
    project: ViewProject,
    profile: BuildProfile,
    project_revision: str,
    recovery: ProjectDiagnostic | None,
) -> None:
    with artifact_lock(project) as acquired:
        if not acquired:
            raise RuntimeError("Blocking artifact lock was not acquired")
        state = read_profile_state(project, profile)
        published = state.published if state is not None else None
        building = ViewBuildState(
            profile=profile,
            phase="building",
            project_revision=project_revision,
            artifact_revision=(
                published.artifact_revision if published is not None else None
            ),
            diagnostics=(recovery,) if recovery is not None else (),
        )
        write_profile_state(project, profile_state(profile, published, building))


def prepare_artifact_publication(
    project: ViewProject,
    profile: BuildProfile,
    candidate: ArtifactCandidate,
    inspection: ProjectInspection,
    report: BuildResult,
    project_revision: str,
    started: float,
) -> PreparedArtifactPublication:
    """Validate and detach one candidate before its receipt transaction."""
    try:
        assert_secure_path(
            project.root,
            candidate.generation_root,
            "Artifact staging generation",
            final_kind="directory",
        )
        assert_secure_path(
            project.root,
            candidate.files_root,
            "Artifact candidate files",
            final_kind="directory",
        )
        if report.document is None:
            raise ConfigurationError("Provider produced no artifact document")
        document = normalized_artifact_path(
            report.document.as_posix(),
            "Artifact document path",
        )
        detach_public_files(candidate.files_root)
        validate_document(candidate.files_root, document)
        files = artifact_files(candidate.files_root)
        manifest = artifact_manifest(document.as_posix(), files, inspection.mounts)
        publication_root = candidate.generation_root / "publication"
        prepare_publication_candidate(
            candidate.generation_root,
            candidate.files_root,
            publication_root,
        )
    except (OSError, ConfigurationError, ViewProjectError) as error:
        record_build_failure(
            project,
            profile,
            (
                ProjectDiagnostic(
                    code="artifact-validation-failed",
                    severity="error",
                    message=str(error),
                    hint="Fix the provider output and build the view again.",
                ),
            ),
            started,
            project_revision,
        )
    try:
        atomic_write_text(
            publication_root / "artifact.json",
            encode_json(artifact_manifest_dict(manifest), pretty=True),
            root=project.root,
        )
    except (OSError, ConfigurationError) as error:
        record_build_failure(
            project,
            profile,
            (
                ProjectDiagnostic(
                    code="artifact-publication-failed",
                    severity="error",
                    message=str(error),
                    hint="Restore the artifact directory and build the view again.",
                ),
            ),
            started,
            project_revision,
        )
    try:
        identity_before = artifact_tree_identity(project, publication_root)
        published_files = publication_root / "files"
        if identity_before is None or artifact_files(published_files) != manifest.files:
            raise ConfigurationError("Artifact publication changed before commit.")
        validate_document(published_files, manifest.document)
        identity = artifact_tree_identity(project, publication_root)
        if identity is None or identity != identity_before:
            raise ConfigurationError(
                "Artifact publication changed while it was verified."
            )
    except (OSError, ConfigurationError, ViewProjectError) as error:
        record_build_failure(
            project,
            profile,
            (
                ProjectDiagnostic(
                    code="artifact-publication-failed",
                    severity="error",
                    message=str(error),
                    hint="Restore the artifact directory and build the view again.",
                ),
            ),
            started,
            project_revision,
        )
    return PreparedArtifactPublication(publication_root, manifest, identity)


def publish_artifact_candidate(
    project: ViewProject,
    profile: BuildProfile,
    prepared: PreparedArtifactPublication,
    provenance: ProviderProvenance,
    report: BuildResult,
    project_revision: str,
    started: float,
    recovery: ProjectDiagnostic | None,
    existing_snapshot: ArtifactRevisionSnapshot | None,
    control: ProviderOperationControl,
    *,
    confirm_current: Callable[[], ProjectDiagnostic | None],
) -> ArtifactLease:
    """Atomically install one prepared candidate and publish its receipt."""
    publication_root = prepared.publication_root
    manifest = prepared.manifest
    lease: ArtifactLease | None = None

    try:
        with artifact_lock(project) as acquired:
            if not acquired:
                raise RuntimeError("Blocking artifact lock was not acquired")
            with secure_directory(project.root) as filesystem:
                destination = revision_root(project, manifest.artifact_revision)
                assert_secure_path(project.root, destination, "Artifact revision")
                existing: ArtifactRevision | None = None
                if destination.exists():
                    current_identity = artifact_tree_identity(project, destination)
                    existing = (
                        existing_snapshot.revision
                        if existing_snapshot is not None
                        and current_identity == existing_snapshot.identity
                        else None
                    )
                    if existing is None:
                        quarantine = quarantine_artifact_revision_locked(
                            project,
                            manifest.artifact_revision,
                        )
                        try:
                            filesystem.replace(publication_root, destination)
                        except BaseException:
                            filesystem.replace(quarantine, destination)
                            raise
                    elif existing.manifest != manifest:
                        raise ConfigurationError(
                            f"Artifact revision collision for view {project.name!r}"
                        )
                    else:
                        filesystem.remove_tree(publication_root)
                else:
                    filesystem.replace(publication_root, destination)
            installed_identity = artifact_tree_identity(project, destination)
            expected_identity = (
                existing_snapshot.identity
                if existing is not None and existing_snapshot is not None
                else prepared.identity
            )
            if installed_identity != expected_identity:
                raise ConfigurationError(
                    "Artifact publication changed during commit for view "
                    f"{project.name!r}"
                )
            installed = (
                existing
                if existing is not None
                else ArtifactRevision(destination / "files", manifest)
            )
            duration_ms = round((time.monotonic() - started) * 1_000)
            diagnostics = (
                (recovery,) if recovery is not None else ()
            ) + report.diagnostics
            publication = ArtifactPublication(
                project_revision,
                manifest.artifact_revision,
                provenance,
                diagnostics,
                duration_ms,
            )
            completed = ViewBuildState(
                profile=profile,
                phase="published",
                project_revision=project_revision,
                artifact_revision=manifest.artifact_revision,
                diagnostics=diagnostics,
                duration_ms=duration_ms,
            )
            artifact = artifact_from_publication(installed, profile, publication)
            lease = lease_artifact_locked(project, artifact)
            prune_artifacts_locked(project)
            rejection = confirm_current()
            if rejection is not None:
                raise ArtifactCommitRejected(rejection)
            committed = write_profile_state_if_active(
                project,
                profile_state(profile, publication, completed),
                control,
            )
            if not committed:
                raise _cancelled_commit()
        return lease
    except ArtifactCommitRejected:
        if lease is None:
            prune_artifacts(project)
        else:
            lease.close()
        raise
    except (OSError, ConfigurationError, RuntimeError, ViewProjectError) as error:
        if lease is None:
            prune_artifacts(project)
        else:
            lease.close()
        record_build_failure(
            project,
            profile,
            (
                ProjectDiagnostic(
                    code="artifact-publication-failed",
                    severity="error",
                    message=str(error),
                    hint="Restore the artifact directory and build the view again.",
                ),
            ),
            started,
            project_revision,
        )
    except BaseException:
        if lease is None:
            prune_artifacts(project)
        else:
            lease.close()
        raise
