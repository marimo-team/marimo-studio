"""Keep immutable artifact revisions alive for every active reader.

A lease promises that an artifact revision will remain available until its
reader finishes. Browser responses, presentation snapshots, static exports,
and retained page history may therefore keep an older revision after a new
build publishes. That promise also applies across Studio processes, so pruning
skips the revision and view deletion rejects while readers are active.

Reads verify manifest membership, size, and digest before bytes reach a
consumer. The lease lets server delivery report a damaged revision and mark
matching publications stale for a rebuild. Studio keeps a revision while a
build profile, browser, presentation, or export still uses it, then removes it
after the final lease closes.
"""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
import uuid
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from threading import Lock
from types import TracebackType
from typing import BinaryIO

from marimo_studio._artifacts.codec import profile_state
from marimo_studio._artifacts.lock import (
    acquire_file_lock,
    artifact_lock,
    release_file_lock,
)
from marimo_studio._artifacts.paths import (
    artifact_paths,
    artifact_root,
    assert_secure_path,
    ensure_secure_directory,
    normalized_artifact_path,
    open_secure_file,
    read_secure_bytes,
)
from marimo_studio._artifacts.records import ArtifactFile, ViewArtifact, ViewBuildState
from marimo_studio._artifacts.repository import (
    read_profile_state,
    read_published_artifact,
    revision_root,
    write_profile_state,
)
from marimo_studio._filesystem.secure import secure_directory
from marimo_studio._workspace.mutation_lock import (
    artifact_lease_lock,
    view_mutation_lock,
)
from marimo_studio.errors import ConfigurationError, ViewInUseError
from marimo_studio.errors._internal import ArtifactIntegrityError
from marimo_studio.view_providers import (
    BuildProfile,
    ProjectDiagnostic,
    ViewProject,
)

_DIGEST = re.compile(r"[0-9a-f]{64}")
_PIN = re.compile(r"([1-9][0-9]*)-([0-9a-f]{32})")
_QUARANTINE = re.compile(r"([0-9a-f]{64})-([0-9a-f]{32})")
_STREAM_CHUNK_SIZE = 64 * 1024


def _integrity_error(path: PurePosixPath) -> ArtifactIntegrityError:
    return ArtifactIntegrityError(
        f"Artifact file does not match its manifest: {path.as_posix()}"
    )


def _verified_snapshot(
    source: BinaryIO,
    record: ArtifactFile,
) -> BinaryIO:
    # The response owns this descriptor until its final streamed byte closes.
    snapshot = tempfile.TemporaryFile(mode="w+b")  # noqa: SIM115
    digest = hashlib.sha256()
    remaining = record.size
    try:
        while remaining:
            chunk = source.read(min(_STREAM_CHUNK_SIZE, remaining))
            if not chunk:
                raise _integrity_error(record.path)
            snapshot.write(chunk)
            digest.update(chunk)
            remaining -= len(chunk)
        if source.read(1) or digest.hexdigest() != record.sha256:
            raise _integrity_error(record.path)
        snapshot.seek(0)
        return snapshot
    except BaseException:
        snapshot.close()
        raise
    finally:
        source.close()


def _pins_root(project: ViewProject) -> Path:
    return artifact_root(project) / ".pins"


def _quarantine_root(project: ViewProject) -> Path:
    return artifact_root(project) / ".quarantine"


def _project_root_missing(project: ViewProject) -> bool:
    try:
        project.root.lstat()
    except FileNotFoundError:
        return True
    return False


def _existing_artifact_root(project: ViewProject) -> Path | None:
    if _project_root_missing(project):
        return None
    assert_secure_path(
        project.root,
        project.root,
        "View project root",
        final_kind="directory",
    )
    root = artifact_root(project)
    try:
        root.lstat()
    except FileNotFoundError:
        return None
    assert_secure_path(
        project.root,
        root,
        "Artifact control root",
        final_kind="directory",
    )
    return root


def _close_locked_descriptor(descriptor: int) -> None:
    try:
        release_file_lock(descriptor)
    finally:
        os.close(descriptor)


def _live_pin_revisions(
    project: ViewProject,
    *,
    create: bool = True,
) -> set[str]:
    root = _pins_root(project)
    if create:
        ensure_secure_directory(project.root, root, "Artifact pins directory")
    elif not root.exists() and not root.is_symlink():
        return set()
    else:
        assert_secure_path(
            project.root,
            root,
            "Artifact pins directory",
            final_kind="directory",
        )
    live: set[str] = set()
    with secure_directory(root) as pins:
        for directory in pins.children():
            if _DIGEST.fullmatch(directory.name) is None:
                raise ConfigurationError(
                    f"Artifact pin revision is invalid: {directory}"
                )
            with secure_directory(directory) as revision_pins:
                for pin in revision_pins.children():
                    if _PIN.fullmatch(pin.name) is None:
                        raise ConfigurationError(f"Artifact pin name is invalid: {pin}")
                    descriptor = revision_pins.open_file(pin, os.O_RDWR)
                    acquired = False
                    try:
                        acquired = acquire_file_lock(descriptor, blocking=False)
                    finally:
                        if not acquired:
                            os.close(descriptor)
                    if not acquired:
                        live.add(f"sha256:{directory.name}")
                    else:
                        _close_locked_descriptor(descriptor)
                        revision_pins.unlink(pin)
            with suppress(OSError):
                pins.rmdir(directory)
    return live


def _prune_quarantine_locked(project: ViewProject) -> None:
    root = _quarantine_root(project)
    if not root.exists() and not root.is_symlink():
        return
    assert_secure_path(
        project.root,
        root,
        "Artifact quarantine directory",
        final_kind="directory",
    )
    with secure_directory(root) as filesystem:
        for path in filesystem.children():
            if _QUARANTINE.fullmatch(path.name) is None:
                raise ConfigurationError(f"Artifact quarantine name is invalid: {path}")
            try:
                filesystem.remove_tree(path)
            except OSError:
                # Open Windows descriptors can retain the physical generation.
                # Their lease close retries this cleanup through artifact pruning.
                continue


def quarantine_artifact_revision_locked(
    project: ViewProject,
    artifact_revision: str,
) -> Path:
    """Move one damaged physical revision aside while its leases drain."""
    digest = artifact_revision.removeprefix("sha256:")
    if _DIGEST.fullmatch(digest) is None:
        raise ConfigurationError(f"Invalid artifact revision: {artifact_revision}")
    source = revision_root(project, artifact_revision)
    assert_secure_path(
        project.root,
        source,
        "Artifact revision",
        final_kind="directory",
    )
    root = _quarantine_root(project)
    ensure_secure_directory(project.root, root, "Artifact quarantine directory")
    destination = root / f"{digest}-{uuid.uuid4().hex}"
    assert_secure_path(project.root, destination, "Artifact quarantine revision")
    with secure_directory(project.root) as filesystem:
        filesystem.replace(source, destination)
    return destination


def prune_artifacts_locked(project: ViewProject) -> None:
    """Delete revisions with no profile publication or live snapshot owner."""
    try:
        project.root.lstat()
    except FileNotFoundError:
        return
    assert_secure_path(
        project.root,
        project.root,
        "View project root",
        final_kind="directory",
    )
    try:
        protected = _live_pin_revisions(project, create=False)
        _prune_quarantine_locked(project)
        for profile in ("development", "production"):
            try:
                state = read_profile_state(project, profile)
            except (OSError, ConfigurationError):
                # A damaged sibling receipt has unknown ownership. Leave every
                # revision in place until that profile repairs its own state.
                return
            if state is not None and state.published is not None:
                protected.add(state.published.artifact_revision)

        revisions = artifact_root(project) / "revisions"
        if not revisions.exists() and not revisions.is_symlink():
            return
        assert_secure_path(
            project.root,
            revisions,
            "Artifact revisions directory",
            final_kind="directory",
        )
        with secure_directory(revisions) as filesystem:
            for path in filesystem.children():
                if _DIGEST.fullmatch(path.name) is None:
                    raise ConfigurationError(
                        f"Artifact revision name is invalid: {path}"
                    )
                if f"sha256:{path.name}" not in protected:
                    filesystem.remove_tree(path)
    except FileNotFoundError:
        return


def prune_artifacts(project: ViewProject) -> None:
    """Prune unowned revisions outside view-source mutation locks."""
    if _existing_artifact_root(project) is None:
        return
    with artifact_lock(project, create=False) as acquired:
        if not acquired:
            if _existing_artifact_root(project) is None:
                return
            raise RuntimeError("Blocking artifact lock was not acquired")
        prune_artifacts_locked(project)


@contextmanager
def artifact_deletion_guard(project: ViewProject) -> Iterator[None]:
    """Block new leases and reject deletion while another process owns one."""
    with (
        view_mutation_lock(project.root.parent, project.name),
        artifact_lease_lock(project.root.parent, project.name),
    ):
        with artifact_lock(project, create=False) as acquired:
            if not acquired:
                if _pins_root(project).exists():
                    raise ConfigurationError(
                        "Artifact publication lock is missing for view "
                        f"{project.name!r}"
                    )
                yield
                return
            if _live_pin_revisions(project, create=False):
                raise ViewInUseError(project.name)
        # Windows cannot rename a tree containing this open lock descriptor.
        # The view-name lock remains held and blocks new leases through deletion.
        yield


@dataclass
class _ArtifactPin:
    """Filesystem lock retaining one immutable revision directory."""

    project: ViewProject
    path: Path
    descriptor: int
    closed: bool = False

    def _release(self) -> None:
        descriptor = self.descriptor
        self.descriptor = -1
        if descriptor >= 0:
            _close_locked_descriptor(descriptor)

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        try:
            if _project_root_missing(self.project):
                return
            assert_secure_path(
                self.project.root,
                self.project.root,
                "View project root",
                final_kind="directory",
            )
            if not self.path.exists() and not self.path.is_symlink():
                return
            with artifact_lock(self.project, create=False) as acquired:
                if not acquired:
                    return
                assert_secure_path(
                    self.project.root,
                    self.path,
                    "Artifact pin",
                    final_kind="file",
                )
                self._release()
                with secure_directory(self.project.root) as filesystem:
                    with suppress(FileNotFoundError):
                        filesystem.unlink(self.path)
                    with suppress(OSError):
                        filesystem.rmdir(self.path.parent)
                prune_artifacts_locked(self.project)
        except (ConfigurationError, OSError):
            if not _project_root_missing(self.project):
                raise
        finally:
            self._release()


def _pin_revision_locked(
    project: ViewProject,
    artifact_revision: str,
) -> _ArtifactPin:
    digest = artifact_revision.removeprefix("sha256:")
    if _DIGEST.fullmatch(digest) is None:
        raise ConfigurationError(f"Invalid artifact revision: {artifact_revision}")
    assert_secure_path(
        project.root,
        revision_root(project, artifact_revision),
        "Artifact revision",
        final_kind="directory",
    )
    root = _pins_root(project)
    directory = root / digest
    path = directory / f"{os.getpid()}-{uuid.uuid4().hex}"
    assert_secure_path(project.root, root, "Artifact pins directory")
    assert_secure_path(project.root, directory, "Artifact revision pins")
    assert_secure_path(project.root, path, "Artifact pin")
    try:
        with secure_directory(project.root) as filesystem:
            filesystem.ensure_directory(root)
            filesystem.ensure_directory(directory)
            descriptor = filesystem.create_file(path)
            try:
                os.write(descriptor, f"{os.getpid()}\n".encode())
                os.fsync(descriptor)
                if not acquire_file_lock(descriptor, blocking=True):
                    raise RuntimeError("Blocking artifact lease lock was not acquired")
            except BaseException:
                os.close(descriptor)
                with suppress(FileNotFoundError):
                    filesystem.unlink(path)
                raise
    except OSError as error:
        raise ConfigurationError(f"Could not create artifact pin: {path}") from error
    return _ArtifactPin(project, path, descriptor)


@dataclass
class _SharedArtifactPin:
    """Reference-count one cross-process pin inside the current process."""

    pin: _ArtifactPin | None
    owners: int = 1
    lock: Lock = field(default_factory=Lock, repr=False)

    def retain(self) -> None:
        with self.lock:
            if self.pin is None:
                raise RuntimeError("Artifact lease is closed")
            self.owners += 1

    def current(self) -> _ArtifactPin:
        with self.lock:
            if self.pin is None:
                raise RuntimeError("Artifact lease is closed")
            return self.pin

    def close(self) -> None:
        pin = None
        with self.lock:
            if self.pin is None:
                return
            self.owners -= 1
            if self.owners == 0:
                pin = self.pin
                self.pin = None
        if pin is not None:
            pin.close()


@dataclass
class ArtifactLease:
    """Explicit lifetime owner for one verified published artifact."""

    project: ViewProject
    artifact: ViewArtifact
    _owner: _SharedArtifactPin | None
    _lock: Lock = field(default_factory=Lock, repr=False)

    @property
    def closed(self) -> bool:
        with self._lock:
            return self._owner is None

    def share(self) -> ArtifactLease:
        """Acquire another owner from the verified artifact record."""
        with self._lock:
            if self._owner is None:
                raise RuntimeError("Artifact lease is closed")
            self._ensure_live_locked()
            self._owner.retain()
            owner = self._owner
        return ArtifactLease(self.project, self.artifact, owner)

    def _ensure_live_locked(self) -> None:
        with artifact_lock(self.project, create=False) as acquired:
            if not acquired or self._owner is None:
                raise ConfigurationError(
                    f"Artifact project was removed: {self.project.root}"
                )
            pin = self._owner.current()
            assert_secure_path(
                self.project.root,
                pin.path,
                "Artifact pin",
                final_kind="file",
            )
            assert_secure_path(
                self.project.root,
                self.artifact.root,
                "Artifact revision files",
                final_kind="directory",
            )

    def _read_locked(self, path: PurePosixPath) -> bytes:
        record = next(
            (item for item in self.artifact.files if item.path == path),
            None,
        )
        if record is None:
            raise ConfigurationError(
                f"Artifact file is absent from its manifest: {path.as_posix()}"
            )
        try:
            payload = read_secure_bytes(
                self.artifact.root,
                self.artifact.root.joinpath(*path.parts),
                "Artifact file",
            )
        except (OSError, ConfigurationError) as error:
            raise _integrity_error(path) from error
        if (
            len(payload) != record.size
            or hashlib.sha256(payload).hexdigest() != record.sha256
        ):
            raise _integrity_error(path)
        return payload

    def read_bytes(self, path: str | PurePosixPath) -> bytes:
        """Return one manifest-listed file after verifying its size and digest."""
        relative = normalized_artifact_path(path, "Artifact file path")
        with self._lock:
            if self._owner is None:
                raise RuntimeError("Artifact lease is closed")
            self._ensure_live_locked()
            return self._read_locked(relative)

    def read_text(
        self,
        path: str | PurePosixPath,
        *,
        encoding: str = "utf-8",
    ) -> str:
        """Decode one verified manifest-listed file."""
        try:
            return self.read_bytes(path).decode(encoding)
        except UnicodeDecodeError as error:
            raise ConfigurationError(
                f"Artifact file is not valid {encoding}"
            ) from error

    def open_file(self, path: str | PurePosixPath) -> LeasedArtifactFile:
        """Snapshot one verified manifest-listed file for bounded streaming."""
        relative = normalized_artifact_path(path, "Artifact file path")
        with self._lock:
            if self._owner is None:
                raise RuntimeError("Artifact lease is closed")
            self._ensure_live_locked()
            record = next(
                (item for item in self.artifact.files if item.path == relative),
                None,
            )
            if record is None:
                raise ConfigurationError(
                    f"Artifact file is absent from its manifest: {relative.as_posix()}"
                )
            try:
                source = open_secure_file(
                    self.artifact.root,
                    self.artifact.root.joinpath(*relative.parts),
                    "Artifact file",
                )
            except (OSError, ConfigurationError) as error:
                raise _integrity_error(relative) from error
            return LeasedArtifactFile(
                self,
                _verified_snapshot(source, record),
                relative,
                record.size,
                record.sha256,
            )

    def record_corruption(self, error: ArtifactIntegrityError) -> None:
        """Mark publications that need rebuilding after integrity failure."""
        with self._lock:
            if self._owner is None:
                return
            with artifact_lock(self.project, create=False) as acquired:
                if not acquired:
                    return
                for profile in ("development", "production"):
                    try:
                        state = read_profile_state(self.project, profile)
                    except (OSError, ConfigurationError):
                        continue
                    if (
                        state is None
                        or state.published is None
                        or state.published.artifact_revision
                        != self.artifact.artifact_revision
                    ):
                        continue
                    diagnostic = ProjectDiagnostic(
                        code=error.code,
                        severity="error",
                        message=(
                            "Published artifact bytes failed integrity verification."
                        ),
                        hint=str(error),
                    )
                    build = ViewBuildState(
                        profile=profile,
                        phase="stale",
                        project_revision=state.published.project_revision,
                        artifact_revision=state.published.artifact_revision,
                        diagnostics=(diagnostic,),
                        duration_ms=state.build.duration_ms,
                    )
                    write_profile_state(
                        self.project,
                        profile_state(profile, state.published, build),
                    )

    def _verify_membership_locked(self) -> None:
        expected = tuple(item.path for item in self.artifact.files)
        try:
            actual = artifact_paths(self.artifact.root)
        except ConfigurationError as error:
            raise ArtifactIntegrityError(
                "Artifact file tree does not match its manifest"
            ) from error
        if actual != expected:
            raise ArtifactIntegrityError(
                "Artifact file tree does not match its manifest"
            )

    def verify_membership(self) -> None:
        """Require the physical file tree to match the artifact manifest paths."""
        with self._lock:
            if self._owner is None:
                raise RuntimeError("Artifact lease is closed")
            self._ensure_live_locked()
            self._verify_membership_locked()

    def verify(self) -> None:
        """Verify membership, sizes, and digests for the leased artifact tree."""
        with self._lock:
            if self._owner is None:
                raise RuntimeError("Artifact lease is closed")
            self._ensure_live_locked()
            expected = tuple(item.path for item in self.artifact.files)
            self._verify_membership_locked()
            for path in expected:
                self._read_locked(path)
            try:
                self._verify_membership_locked()
            except ArtifactIntegrityError as error:
                raise ArtifactIntegrityError(
                    "Artifact file tree changed during verification"
                ) from error

    def close(self) -> None:
        with self._lock:
            owner = self._owner
            self._owner = None
        if owner is not None:
            owner.close()

    def __enter__(self) -> ArtifactLease:
        if self.closed:
            raise RuntimeError("Artifact lease is closed")
        return self

    def __exit__(
        self,
        _exception_type: type[BaseException] | None,
        _exception: BaseException | None,
        _traceback: TracebackType | None,
    ) -> None:
        self.close()


@dataclass
class LeasedArtifactFile:
    """Verified open artifact file retaining its revision lease."""

    lease: ArtifactLease
    stream: BinaryIO
    path: PurePosixPath
    size: int
    sha256: str
    closed: bool = False

    def iter_bytes(self) -> Iterator[bytes]:
        """Yield bounded file chunks and release the artifact on completion."""
        try:
            remaining = self.size
            while remaining:
                chunk = self.stream.read(min(_STREAM_CHUNK_SIZE, remaining))
                if not chunk:
                    raise _integrity_error(self.path)
                remaining -= len(chunk)
                yield chunk
            if self.stream.read(1):
                raise _integrity_error(self.path)
        finally:
            self.close()

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        try:
            self.stream.close()
        finally:
            self.lease.close()


def lease_artifact_locked(
    project: ViewProject,
    artifact: ViewArtifact,
) -> ArtifactLease:
    """Acquire a lease for a verified artifact under the publication lock."""
    expected_root = revision_root(project, artifact.artifact_revision) / "files"
    if artifact.root != expected_root:
        raise ConfigurationError("Artifact root does not match its revision")
    pin = _pin_revision_locked(project, artifact.artifact_revision)
    return ArtifactLease(project, artifact, _SharedArtifactPin(pin))


def lease_published_artifact(
    project: ViewProject,
    profile: BuildProfile,
) -> ArtifactLease | None:
    """Acquire the current profile publication and its immutable revision."""
    with (
        artifact_lease_lock(project.root.parent, project.name),
        artifact_lock(project, create=False) as acquired,
    ):
        if not acquired:
            return None
        artifact = read_published_artifact(project, profile)
        return None if artifact is None else lease_artifact_locked(project, artifact)
