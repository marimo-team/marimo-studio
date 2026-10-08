"""Read, verify, and recover view-local artifact repository state."""

from __future__ import annotations

import hashlib
import json
import secrets
import stat
from contextlib import suppress
from pathlib import Path, PurePosixPath

from marimo_studio._artifacts.codec import (
    ArtifactFormatError,
    decode_artifact_manifest,
    decode_profile_state,
    encode_json,
    profile_state,
    profile_state_dict,
    read_json,
)
from marimo_studio._artifacts.limits import ARTIFACT_OUTPUT_BUDGET
from marimo_studio._artifacts.lock import artifact_lock, build_lock
from marimo_studio._artifacts.paths import (
    artifact_files,
    artifact_root,
    assert_secure_path,
    ensure_secure_directory,
    normalized_artifact_path,
    read_secure_bytes,
    validated_artifact_paths,
)
from marimo_studio._artifacts.records import (
    ArtifactFile,
    ArtifactProfileState,
    ArtifactPublication,
    ArtifactRevision,
    ArtifactRevisionSnapshot,
    ArtifactStateSnapshot,
    ViewArtifact,
    ViewBuildState,
)
from marimo_studio._filesystem.files import FileTree, TreeVersion
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


def _current_profile_state(
    project: ViewProject,
    profile: BuildProfile,
) -> ArtifactProfileState | None:
    # Readers treat state from another Studio format as unbuilt. The next
    # build discards it and publishes in the current format.
    try:
        return read_profile_state(project, profile)
    except ArtifactFormatError:
        return None


def write_profile_state(project: ViewProject, state: ArtifactProfileState) -> None:
    ensure_secure_directory(
        project.root, artifact_root(project), "Artifact control root"
    )
    pointer = profile_pointer(project, state.profile)
    assert_secure_path(project.root, pointer, "Artifact profile receipt")
    FileTree(project.root).write(
        pointer, encode_json(profile_state_dict(state)).encode("utf-8")
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
    tree = FileTree(project.root)
    tree.write(pending, encode_json(profile_state_dict(state)).encode("utf-8"))

    def commit() -> None:
        tree.replace(pending, pointer)

    def discard_pending() -> None:
        with suppress(OSError):
            tree.remove(pending)

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
    tree = FileTree(project.root)
    for path in tree.children(staging):
        tree.remove(path)


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


def ingest_publication_files(
    project: ViewProject,
    files_root: Path,
    destination: Path,
) -> tuple[ArtifactFile, ...]:
    """Copy provider output into a new Studio-owned revision directory.

    The provider can still reach ``files_root``, so publication reads, hashes,
    and serves only the Studio-owned copy at ``destination``.
    """
    ingested = {
        item.path.as_posix(): item
        for item in FileTree(project.root).ingest(
            files_root,
            destination,
            budget=ARTIFACT_OUTPUT_BUDGET,
            label="Artifact output",
        )
    }
    return tuple(
        ArtifactFile(
            path, ingested[path.as_posix()].digest, ingested[path.as_posix()].size
        )
        for path in validated_artifact_paths(ingested)
    )


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
        sites=manifest.sites,
        project_revision=publication.project_revision,
        artifact_revision=manifest.artifact_revision,
        provider=publication.provider,
        template=manifest.template,
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
    manifest = decode_artifact_manifest(
        read_json(project.root, manifest_path, "artifact manifest")
    )
    if manifest.artifact_revision != artifact_revision:
        raise ConfigurationError(
            f"Artifact manifest revision does not match its directory: {manifest_path}"
        )
    expected = {"artifact.json", "files"}
    if manifest.template is not None:
        expected.add("template")
    if {path.name for path in root.iterdir()} != expected:
        raise ConfigurationError(
            f"Artifact revision contains untracked entries: {root}"
        )
    physical_files = artifact_files(files_root)
    if physical_files != manifest.files:
        raise ConfigurationError(
            f"Artifact file tree does not match its manifest: {root}"
        )
    if manifest.template is not None:
        template_root = root / "template"
        assert_secure_path(
            project.root,
            template_root,
            "Artifact template",
            final_kind="directory",
        )
        if artifact_files(template_root) != manifest.template.files:
            raise ConfigurationError(
                f"Artifact template tree does not match its manifest: {root}"
            )
    validate_document(files_root, manifest.document)
    return ArtifactRevision(files_root, manifest)


def artifact_tree_identity(project: ViewProject, root: Path) -> TreeVersion | None:
    """Capture bounded artifact metadata without reading file contents.

    A document revision holds its public files and its private template, each
    within the artifact file budget, beside ``artifact.json``.
    """
    return FileTree(project.root).tree_version(
        root,
        max_entries=2 * ARTIFACT_OUTPUT_BUDGET.max_files + 3,
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
    state = _current_profile_state(project, profile)
    if state is None or state.published is None:
        return None
    try:
        revision = read_artifact_revision(project, state.published.artifact_revision)
    except ArtifactFormatError:
        return None
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
        state = _current_profile_state(project, profile)
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
            latest = _current_profile_state(project, profile)
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
        state = _current_profile_state(project, profile)
        if state is None:
            return ArtifactStateSnapshot(None, None, _unbuilt_state(profile))
        artifact = None
        if state.published is not None:
            try:
                revision = read_artifact_revision(
                    project,
                    state.published.artifact_revision,
                )
            except ArtifactFormatError:
                return ArtifactStateSnapshot(None, None, _unbuilt_state(profile))
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
