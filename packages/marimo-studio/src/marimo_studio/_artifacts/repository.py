"""Read, verify, and recover view-local artifact repository state."""

from __future__ import annotations

import hashlib
import json
import secrets
import stat
from contextlib import suppress
from pathlib import Path, PurePosixPath

from marimo_studio._artifacts.codec import (
    decode_artifact_manifest,
    decode_profile_state,
    encode_json,
    profile_state,
    profile_state_dict,
    read_json,
)
from marimo_studio._artifacts.limits import ARTIFACT_OUTPUT_BUDGET, FileBudgetTracker
from marimo_studio._artifacts.lock import artifact_lock, build_lock
from marimo_studio._artifacts.paths import (
    artifact_files,
    artifact_root,
    assert_secure_path,
    ensure_secure_directory,
    normalized_artifact_path,
    read_secure_bytes,
)
from marimo_studio._artifacts.records import (
    ArtifactProfileState,
    ArtifactPublication,
    ArtifactRevision,
    ArtifactRevisionSnapshot,
    ArtifactStateSnapshot,
    ArtifactTreeIdentity,
    ViewArtifact,
    ViewBuildState,
)
from marimo_studio._filesystem.io import atomic_write_text
from marimo_studio._filesystem.secure import secure_directory
from marimo_studio._processes.cancellation import ProviderOperationControl
from marimo_studio.errors import ConfigurationError, ViewProjectError
from marimo_studio.view_providers import (
    BuildProfile,
    ProjectDiagnostic,
    ViewProject,
)
from marimo_studio.view_providers._document import (
    HTMLDocumentParser,
    validate_html_document,
)


def profile_pointer(project: ViewProject, profile: BuildProfile) -> Path:
    return artifact_root(project) / f"{profile}.json"


def revision_root(project: ViewProject, artifact_revision: str) -> Path:
    return (
        artifact_root(project) / "revisions" / artifact_revision.removeprefix("sha256:")
    )


def validate_document(root: Path, document: PurePosixPath) -> None:
    relative = normalized_artifact_path(document.as_posix(), "Artifact document path")
    path = root / relative
    try:
        source = read_secure_bytes(
            root,
            path,
            "Artifact document",
            max_bytes=ARTIFACT_OUTPUT_BUDGET.max_file_bytes,
        ).decode("utf-8")
    except UnicodeDecodeError as error:
        raise ViewProjectError(
            f"Artifact document must be UTF-8: {relative}"
        ) from error
    parser = HTMLDocumentParser()
    parser.feed(source)
    validate_html_document(parser, relative.as_posix())
    if parser.has_reserved_runtime_markup:
        raise ViewProjectError(
            f"{relative}: artifact document contains reserved runtime markup"
        )


def read_profile_state(
    project: ViewProject,
    profile: BuildProfile,
) -> ArtifactProfileState | None:
    pointer = profile_pointer(project, profile)
    assert_secure_path(project.root, pointer, "Artifact profile receipt")
    if not pointer.exists():
        return None
    assert_secure_path(
        project.root,
        pointer,
        "Artifact profile receipt",
        final_kind="file",
    )
    return decode_profile_state(
        read_json(project.root, pointer, "artifact profile receipt"),
        profile,
    )


def write_profile_state(project: ViewProject, state: ArtifactProfileState) -> None:
    ensure_secure_directory(
        project.root, artifact_root(project), "Artifact control root"
    )
    pointer = profile_pointer(project, state.profile)
    assert_secure_path(project.root, pointer, "Artifact profile receipt")
    atomic_write_text(
        pointer,
        encode_json(profile_state_dict(state)),
        root=project.root,
    )


def write_profile_state_if_active(
    project: ViewProject,
    state: ArtifactProfileState,
    control: ProviderOperationControl,
) -> bool:
    """Stage a receipt, then replace its pointer if cancellation has not won."""
    control_root = artifact_root(project)
    ensure_secure_directory(project.root, control_root, "Artifact control root")
    staging = control_root / ".staging"
    ensure_secure_directory(project.root, staging, "Artifact staging directory")
    pointer = profile_pointer(project, state.profile)
    pending = staging / f"receipt-{state.profile}-{secrets.token_hex(16)}.json"
    assert_secure_path(project.root, pointer, "Artifact profile receipt")
    assert_secure_path(project.root, pending, "Artifact pending profile receipt")
    atomic_write_text(
        pending,
        encode_json(profile_state_dict(state)),
        root=project.root,
    )

    def commit() -> None:
        with secure_directory(project.root) as filesystem:
            filesystem.replace(pending, pointer)

    def discard_pending() -> None:
        with (
            suppress(OSError, ConfigurationError),
            secure_directory(project.root) as filesystem,
        ):
            filesystem.unlink(pending)

    try:
        committed = control.commit_if_active(commit)
    except BaseException:
        discard_pending()
        raise
    if not committed:
        discard_pending()
    return committed


def recover_staging(project: ViewProject) -> None:
    staging = artifact_root(project) / ".staging"
    ensure_secure_directory(project.root, staging, "Artifact staging directory")
    with secure_directory(staging) as filesystem:
        for path in filesystem.children():
            filesystem.remove_tree(path)


def prepare_control_directories(project: ViewProject) -> None:
    control_root = artifact_root(project)
    ensure_secure_directory(project.root, control_root, "Artifact control root")
    ensure_secure_directory(
        project.root,
        control_root / "revisions",
        "Artifact revisions directory",
    )
    cache = control_root / ".cache"
    assert_secure_path(project.root, cache, "Artifact provider cache")
    if cache.exists():
        assert_secure_path(
            project.root,
            cache,
            "Artifact provider cache",
            final_kind="directory",
        )
    recover_staging(project)


def prepare_publication_candidate(
    generation_root: Path,
    files_root: Path,
    publication_root: Path,
) -> Path:
    """Detach public files from the private provider snapshot and scratch tree."""
    with secure_directory(generation_root) as filesystem:
        filesystem.create_directory(publication_root)
        published_files = publication_root / "files"
        filesystem.replace(files_root, published_files)
        for path in filesystem.children():
            if path != publication_root:
                filesystem.remove_tree(path)
    return published_files


def detach_public_files(files_root: Path) -> None:
    """Copy provider files onto revision-owned inodes before hashing."""
    budget = FileBudgetTracker(ARTIFACT_OUTPUT_BUDGET, "Artifact output")
    with secure_directory(files_root) as filesystem:
        files = filesystem.regular_file_sizes(
            max_entries=ARTIFACT_OUTPUT_BUDGET.max_files,
        )
        if not files:
            raise ConfigurationError("Artifact contains no browser files")
        for path, size in files:
            budget.add(path.relative_to(files_root).as_posix(), size)
        for path, size in files:
            filesystem.replace_with_copy(path, expected_size=size)


def artifact_from_publication(
    revision: ArtifactRevision,
    profile: BuildProfile,
    publication: ArtifactPublication,
) -> ViewArtifact:
    manifest = revision.manifest
    return ViewArtifact(
        root=revision.root,
        profile=profile,
        document=manifest.document,
        files=manifest.files,
        mounts=manifest.mounts,
        project_revision=publication.project_revision,
        artifact_revision=manifest.artifact_revision,
        provider=publication.provider,
    )


def read_artifact_revision(
    project: ViewProject,
    artifact_revision: str,
) -> ArtifactRevision | None:
    """Read and fully verify one immutable artifact revision."""
    digest = artifact_revision.removeprefix("sha256:")
    if (
        not artifact_revision.startswith("sha256:")
        or len(digest) != 64
        or any(character not in "0123456789abcdef" for character in digest)
    ):
        raise ConfigurationError(f"Invalid artifact revision for view {project.name!r}")

    root = revision_root(project, artifact_revision)
    assert_secure_path(project.root, root, "Artifact revision")
    if not root.exists():
        return None
    assert_secure_path(
        project.root,
        root,
        "Artifact revision",
        final_kind="directory",
    )
    manifest_path = root / "artifact.json"
    files_root = root / "files"
    assert_secure_path(
        project.root,
        manifest_path,
        "Artifact manifest",
        final_kind="file",
    )
    assert_secure_path(
        project.root,
        files_root,
        "Artifact files",
        final_kind="directory",
    )
    if {path.name for path in root.iterdir()} != {"artifact.json", "files"}:
        raise ConfigurationError(
            f"Artifact revision contains untracked entries: {root}"
        )
    manifest = decode_artifact_manifest(
        read_json(project.root, manifest_path, "artifact manifest")
    )
    if manifest.artifact_revision != artifact_revision:
        raise ConfigurationError(
            f"Artifact manifest revision does not match its directory: {manifest_path}"
        )
    physical_files = artifact_files(files_root)
    if physical_files != manifest.files:
        raise ConfigurationError(
            f"Artifact file tree does not match its manifest: {root}"
        )
    validate_document(files_root, manifest.document)
    return ArtifactRevision(files_root, manifest)


def artifact_tree_identity(
    project: ViewProject,
    root: Path,
) -> ArtifactTreeIdentity | None:
    """Capture bounded artifact metadata without reading file contents."""
    with secure_directory(project.root) as filesystem:
        return filesystem.directory_tree_identity(
            root,
            max_entries=ARTIFACT_OUTPUT_BUDGET.max_files + 2,
        )


def read_artifact_revision_snapshot(
    project: ViewProject,
    artifact_revision: str,
) -> ArtifactRevisionSnapshot | None:
    """Verify one revision outside mutation locks and capture its identity."""
    root = revision_root(project, artifact_revision)
    before = artifact_tree_identity(project, root)
    if before is None:
        return None
    revision = read_artifact_revision(project, artifact_revision)
    if revision is None:
        return None
    after = artifact_tree_identity(project, root)
    if after is None or before != after:
        raise ConfigurationError(
            f"Artifact revision changed while it was verified: {root}"
        )
    return ArtifactRevisionSnapshot(revision, after)


def read_published_artifact(
    project: ViewProject,
    profile: BuildProfile,
) -> ViewArtifact | None:
    """Read a profile publication from its captured provider descriptor."""
    state = read_profile_state(project, profile)
    if state is None or state.published is None:
        return None
    revision = read_artifact_revision(project, state.published.artifact_revision)
    if revision is None:
        raise ConfigurationError(
            f"Published artifact is missing for view {project.name!r}: "
            f"{state.published.artifact_revision}"
        )
    return artifact_from_publication(revision, profile, state.published)


def _interrupted_state(
    project: ViewProject,
    state: ArtifactProfileState,
) -> ArtifactProfileState:
    published = state.published
    diagnostic = ProjectDiagnostic(
        code="build-interrupted",
        severity="error",
        message="The previous view build stopped before publication.",
        hint="Build the view again.",
    )
    build = ViewBuildState(
        profile=state.profile,
        phase="stale" if published is not None else "failed",
        project_revision=state.build.project_revision,
        artifact_revision=(
            published.artifact_revision if published is not None else None
        ),
        diagnostics=(diagnostic,),
        duration_ms=state.build.duration_ms,
    )
    recovered = profile_state(state.profile, published, build)
    recover_staging(project)
    write_profile_state(project, recovered)
    return recovered


def _unbuilt_state(profile: BuildProfile) -> ViewBuildState:
    return ViewBuildState(profile, "unbuilt", None, None, ())


def _path_identity(path: Path, *, directory: bool, label: str) -> tuple[int, ...]:
    try:
        state = path.stat(follow_symlinks=False)
    except (FileNotFoundError, NotADirectoryError):
        raise
    except OSError as error:
        raise ConfigurationError(f"{label} is unavailable: {path}") from error
    valid = stat.S_ISDIR(state.st_mode) if directory else stat.S_ISREG(state.st_mode)
    if not valid:
        expected = "directory" if directory else "regular file"
        raise ConfigurationError(f"{label} must be a {expected}: {path}")
    return (
        state.st_dev,
        state.st_ino,
        state.st_ctime_ns,
        state.st_mtime_ns,
        state.st_size,
    )


def _project_incarnation(project: ViewProject) -> str | None:
    try:
        root_before = _path_identity(
            project.root,
            directory=True,
            label="View project root",
        )
        manifest_before = _path_identity(
            project.manifest,
            directory=False,
            label="View project manifest",
        )
        manifest = read_secure_bytes(
            project.root,
            project.manifest,
            "View project manifest",
        )
        root_after = _path_identity(
            project.root,
            directory=True,
            label="View project root",
        )
        manifest_after = _path_identity(
            project.manifest,
            directory=False,
            label="View project manifest",
        )
    except (FileNotFoundError, NotADirectoryError):
        return None
    except ConfigurationError:
        if not project.root.is_dir() or not project.manifest.is_file():
            return None
        raise
    if root_before != root_after or manifest_before != manifest_after:
        return None
    encoded = json.dumps(
        {
            "name": project.name,
            "provider": project.provider,
            "options": dict(project.options),
            "root": root_before,
            "manifest": manifest_before,
            "manifest_sha256": hashlib.sha256(manifest).hexdigest(),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode()
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _read_build_state(
    project: ViewProject,
    profile: BuildProfile,
    incarnation: str,
) -> ViewBuildState:
    unbuilt = _unbuilt_state(profile)
    with artifact_lock(project, create=False) as acquired:
        if not acquired or _project_incarnation(project) != incarnation:
            return unbuilt
        state = read_profile_state(project, profile)
        if state is None:
            return unbuilt
        if state.build.phase != "building":
            return state.build
    with build_lock(project, blocking=False, create=False) as acquired:
        if not acquired:
            return (
                state.build if _project_incarnation(project) == incarnation else unbuilt
            )
        if _project_incarnation(project) != incarnation:
            return unbuilt
        with artifact_lock(project, create=False) as published:
            if not published or _project_incarnation(project) != incarnation:
                return unbuilt
            latest = read_profile_state(project, profile)
            if latest is None:
                return unbuilt
            return (
                _interrupted_state(project, latest).build
                if latest.build.phase == "building"
                else latest.build
            )


def read_build_state(
    project: ViewProject,
    profile: BuildProfile,
) -> ViewBuildState:
    """Return the latest build receipt and recover abandoned build state."""
    incarnation = _project_incarnation(project)
    if incarnation is None:
        return _unbuilt_state(profile)
    return _read_build_state(project, profile, incarnation)


def read_artifact_state(
    project: ViewProject,
    profile: BuildProfile,
) -> ArtifactStateSnapshot:
    """Atomically read one profile receipt and its verified publication."""
    incarnation = _project_incarnation(project)
    if incarnation is None:
        return ArtifactStateSnapshot(None, None, _unbuilt_state(profile))
    _read_build_state(project, profile, incarnation)
    with artifact_lock(project, create=False) as acquired:
        if not acquired or _project_incarnation(project) != incarnation:
            return ArtifactStateSnapshot(None, None, _unbuilt_state(profile))
        state = read_profile_state(project, profile)
        if state is None:
            return ArtifactStateSnapshot(None, None, _unbuilt_state(profile))
        artifact = None
        if state.published is not None:
            try:
                revision = read_artifact_revision(
                    project,
                    state.published.artifact_revision,
                )
            except (ConfigurationError, FileNotFoundError):
                if _project_incarnation(project) != incarnation:
                    return ArtifactStateSnapshot(None, None, _unbuilt_state(profile))
                raise
            if revision is None:
                raise ConfigurationError(
                    f"Published artifact is missing for view {project.name!r}: "
                    f"{state.published.artifact_revision}"
                )
            artifact = artifact_from_publication(
                revision,
                profile,
                state.published,
            )
        return ArtifactStateSnapshot(state, artifact, state.build)
