"""Convert provider-built browser files into a current immutable publication.

Provider output is a candidate, not trusted application state. Studio copies
its files out of provider scratch space into a directory that only Studio
writes, enforces file and path limits, validates the entry document and
complete manifest, and computes a content-addressed revision from the browser
files and artifact sites.

Studio makes the candidate current for the selected build profile only after it
is complete and the caller confirms that the live project still matches the
source that was built. Build-start and failure records remain separate from the
successful publication, so a later failed attempt can report diagnostics while
the last working page remains available.
"""

from __future__ import annotations

import logging
import secrets
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import NoReturn

from marimo_studio._artifacts.codec import (
    ArtifactFormatError,
    artifact_manifest,
    artifact_manifest_dict,
    encode_json,
    profile_state,
)
from marimo_studio._artifacts.inputs import ProjectSnapshot, snapshot_project
from marimo_studio._artifacts.lock import artifact_lock
from marimo_studio._artifacts.paths import (
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
    ArtifactTemplate,
    ViewArtifact,
    ViewBuildState,
)
from marimo_studio._artifacts.repository import (
    artifact_from_publication,
    artifact_tree_identity,
    ingest_publication_files,
    prepare_control_directories,
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
from marimo_studio._filesystem.files import (
    ABSENT,
    ConditionalWriteError,
    FileTree,
    TreeVersion,
)
from marimo_studio._processes.cancellation import ProviderOperationControl
from marimo_studio.errors import ConfigurationError, ViewProjectError
from marimo_studio.view_providers import (
    BuildProfile,
    BuildResult,
    ProjectDiagnostic,
    ProjectInspection,
    ViewProject,
)
from marimo_studio.view_providers._artifact_sites import ArtifactSite
from marimo_studio.view_providers._host.records import ProviderProvenance

_LOGGER = logging.getLogger("marimo.studio")


@dataclass(frozen=True)
class ArtifactBuildPreparation:
    current: ViewArtifact | None
    current_snapshot: ArtifactRevisionSnapshot | None


@dataclass(frozen=True)
class ArtifactCandidate:
    generation_root: Path
    snapshot: ProjectSnapshot
    files_root: Path
    work_root: Path
    cache_root: Path


@dataclass(frozen=True)
class TemplateCandidate:
    """Private provider output that Studio renders after publication."""

    root: Path
    document: PurePosixPath
    renderer: str


@dataclass(frozen=True)
class PreparedArtifactPublication:
    publication_root: Path
    manifest: ArtifactManifest
    identity: TreeVersion


class ArtifactCommitRejected(Exception):
    """Reject a receipt when its live project identity is no longer current."""

    def __init__(self, diagnostic: ProjectDiagnostic) -> None:
        super().__init__(diagnostic.message)
        self.diagnostic = diagnostic


def _remove_profile_pointer(project: ViewProject, profile: BuildProfile) -> None:
    FileTree(project.root).remove(profile_pointer(project, profile))


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
    raise project_build_error(project, diagnostics)


def project_build_error(
    project: ViewProject, errors: tuple[ProjectDiagnostic, ...]
) -> ViewProjectError:
    """Return a build rejection without changing publication state."""
    # Code mode shows only the message, so it carries the location and count.
    first = errors[0]
    source = project.root / first.source.path if first.source else project.manifest
    message = first.message
    if first.source is not None:
        message = f"{source}:{first.source.line}:{first.source.column}: {message}"
    if len(errors) > 1:
        more = len(errors) - 1
        message += f" Inspect the view to list {more} more error" + (
            "s." if more > 1 else "."
        )
    return ViewProjectError(
        message,
        source=source,
        line=first.source.line if first.source else None,
        column=first.source.column if first.source else None,
        hint=first.hint or None,
    )


def prepare_artifact_build(
    project: ViewProject,
    profile: BuildProfile,
) -> ArtifactBuildPreparation:
    """Recover generated state and return the verified current publication."""
    prepare_control_directories(project)
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
            # The build that follows replaces the discarded state, so the
            # person has nothing to act on. Operators see the reason here.
            if isinstance(error, ArtifactFormatError):
                _LOGGER.info(
                    "Rebuilding view %r (%s profile) because another Studio "
                    "version wrote its stored artifact: %s.",
                    project.name,
                    profile,
                    error,
                )
            else:
                _LOGGER.warning(
                    "Rebuilding view %r (%s profile) because its stored artifact "
                    "is unreadable: %s. Studio discarded the generated state in "
                    "%s. If this repeats, check whether another tool changes "
                    "that directory.",
                    project.name,
                    profile,
                    error,
                    artifact_root(project),
                )
        return ArtifactBuildPreparation(current, current_snapshot)


# https://bford.info/cachedir/ marks a directory that tools can rebuild.
# Workspace hosts and backup tools skip it, which keeps a provider's dependency
# cache and unfinished build candidates out of saved workspaces while view
# sources and revisions stay.
_CACHE_DIRECTORY_SIGNATURE = b"Signature: 8a477f597d28d172789f06886806bc55"
_CACHE_DIRECTORY_TAG = (
    _CACHE_DIRECTORY_SIGNATURE
    + b"\n# marimo Studio recreates this directory on demand.\n"
)


def _tag_cache_directory(tree: FileTree, directory: Path) -> None:
    tag = directory / "CACHEDIR.TAG"
    try:
        try:
            current = tree.read(tag)
        except FileNotFoundError:
            current = None
        if current is not None and current.content.startswith(
            _CACHE_DIRECTORY_SIGNATURE
        ):
            return
        tree.write(
            tag,
            _CACHE_DIRECTORY_TAG,
            expect=ABSENT if current is None else current.version,
        )
    except ConditionalWriteError:
        return
    except OSError as error:
        _LOGGER.warning(
            "Could not tag %s as a cache directory, so saved workspaces and "
            "backups include it. Check that the directory is writable: %s",
            directory,
            error,
        )


@contextmanager
def capture_artifact_candidate(
    project: ViewProject,
    inspection: ProjectInspection,
) -> Iterator[ArtifactCandidate]:
    """Capture immutable build inputs and own their temporary generation."""
    generation_root = (
        artifact_root(project) / ".staging" / f"candidate-{secrets.token_hex(16)}"
    )
    tree = FileTree(project.root)
    tree.create_directory(generation_root)
    _tag_cache_directory(tree, generation_root.parent)
    try:
        captured = snapshot_project(project, inspection, generation_root / "project")
        files_root = artifact_root(captured.project) / "build" / "files"
        work_root = files_root.parent / "work"
        tree.ensure_directory(files_root)
        tree.ensure_directory(work_root)
        cache_root = artifact_root(project) / ".cache"
        ensure_secure_directory(project.root, cache_root, "Artifact provider cache")
        assert_secure_path(
            project.root,
            cache_root,
            "Artifact provider cache",
            final_kind="directory",
        )
        _tag_cache_directory(tree, cache_root)
        yield ArtifactCandidate(
            generation_root,
            captured,
            files_root,
            work_root,
            cache_root,
        )
    finally:
        with suppress(OSError):
            tree.remove(generation_root)


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
            diagnostics=(),
        )
        write_profile_state(project, profile_state(profile, published, building))


def prepare_artifact_publication(
    project: ViewProject,
    profile: BuildProfile,
    candidate: ArtifactCandidate,
    sites: tuple[ArtifactSite, ...],
    document: PurePosixPath,
    project_revision: str,
    started: float,
    *,
    template: TemplateCandidate | None,
) -> PreparedArtifactPublication:
    """Validate and copy one candidate before its receipt transaction."""
    tree = FileTree(project.root)
    publication_root = candidate.generation_root / "publication"
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
        document = normalized_artifact_path(
            document.as_posix(),
            "Artifact document path",
        )
        tree.create_directory(publication_root)
        published_files = publication_root / "files"
        files = ingest_publication_files(project, candidate.files_root, published_files)
        validate_document(published_files, document)
        template_record = None
        if template is not None:
            template_record = ArtifactTemplate(
                normalized_artifact_path(
                    template.document.as_posix(),
                    "Artifact template document",
                ),
                ingest_publication_files(
                    project,
                    template.root,
                    publication_root / "template",
                ),
                template.renderer,
            )
        manifest = artifact_manifest(
            document.as_posix(),
            files,
            sites,
            template_record,
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
        tree.write(
            publication_root / "artifact.json",
            encode_json(artifact_manifest_dict(manifest), pretty=True).encode("utf-8"),
            expect=ABSENT,
        )
        identity = artifact_tree_identity(project, publication_root)
        if identity is None:
            raise ConfigurationError("Artifact publication was removed before commit.")
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
    return PreparedArtifactPublication(publication_root, manifest, identity)


def publish_artifact_candidate(
    project: ViewProject,
    profile: BuildProfile,
    prepared: PreparedArtifactPublication,
    provenance: ProviderProvenance,
    report: BuildResult,
    project_revision: str,
    started: float,
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
            tree = FileTree(project.root)
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
                        tree.replace(publication_root, destination)
                    except BaseException:
                        tree.replace(quarantine, destination)
                        raise
                elif existing.manifest != manifest:
                    raise ConfigurationError(
                        f"Artifact revision collision for view {project.name!r}"
                    )
                else:
                    tree.remove(publication_root)
            else:
                tree.replace(publication_root, destination)
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
            publication = ArtifactPublication(
                project_revision,
                manifest.artifact_revision,
                provenance,
                report.diagnostics,
                duration_ms,
            )
            completed = ViewBuildState(
                profile=profile,
                phase="published",
                project_revision=project_revision,
                artifact_revision=manifest.artifact_revision,
                diagnostics=report.diagnostics,
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
