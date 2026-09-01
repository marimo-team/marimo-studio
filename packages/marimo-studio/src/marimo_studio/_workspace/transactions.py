"""Apply related workspace file writes as one recoverable operation."""

from __future__ import annotations

from collections.abc import Callable, Collection, Iterator, Mapping
from contextlib import ExitStack, contextmanager
from pathlib import Path, PurePosixPath

from marimo_studio._filesystem._secure_types import (
    ConditionalWriteError,
    SecureFileError,
)
from marimo_studio._filesystem.io import (
    atomic_write_bytes,
    read_file_snapshot_with_identity,
)
from marimo_studio._filesystem.secure import (
    FileIdentity,
    SecureDirectory,
    secure_directory,
)
from marimo_studio.errors import ConfigurationError


def _add_error_note(error: BaseException, note: str) -> None:
    add_note = getattr(error, "add_note", None)
    if callable(add_note):
        add_note(note)
        return
    notes: list[str] = list(getattr(error, "__notes__", ()))
    notes.append(note)
    error.__notes__ = notes  # pyright: ignore[reportAttributeAccessIssue]


def _claimed_root_for_path(
    path: Path,
    claimed_filesystems: Mapping[Path, SecureDirectory],
) -> Path | None:
    roots = tuple(root for root in claimed_filesystems if root in path.parents)
    if not roots:
        return None
    return max(roots, key=lambda candidate: len(candidate.parts))


def _owner_for_path(
    path: Path,
    filesystem: SecureDirectory,
    claimed_filesystems: Mapping[Path, SecureDirectory],
) -> SecureDirectory:
    root = _claimed_root_for_path(path, claimed_filesystems)
    return filesystem if root is None else claimed_filesystems[root]


def _rollback(
    filesystem: SecureDirectory,
    snapshots: Mapping[Path, tuple[bytes, int] | None],
    directories: Mapping[Path, FileIdentity],
    written_files: Mapping[Path, FileIdentity],
    claimed_filesystems: Mapping[Path, SecureDirectory],
    close_claimed_owners: Callable[[], None],
) -> None:
    failures: list[tuple[Path, Exception]] = []
    blocked_directories: set[Path] = set()

    def record_file_failure(path: Path, error: Exception) -> None:
        failures.append((path, error))
        blocked_directories.update(
            directory for directory in directories if directory in path.parents
        )

    def record_directory_failure(path: Path, error: Exception) -> None:
        failures.append((path, error))
        blocked_directories.update(
            directory for directory in directories if directory in path.parents
        )

    for path, snapshot in snapshots.items():
        identity = written_files.get(path)
        if identity is None:
            continue
        owner = _owner_for_path(path, filesystem, claimed_filesystems)
        try:
            quarantine = owner.quarantine_if_identity(path, identity)
        except FileNotFoundError:
            if snapshot is not None:
                content, mode = snapshot
                try:
                    owner.restore_file_if_absent(path, content, mode)
                except Exception as error:
                    record_file_failure(path, error)
        except Exception as error:
            record_file_failure(path, error)
        else:
            restored = snapshot is None
            if snapshot is not None:
                content, mode = snapshot
                try:
                    owner.restore_file_if_absent(path, content, mode)
                except Exception as error:
                    record_file_failure(
                        path,
                        RuntimeError(
                            f"Rollback file was preserved at {quarantine}: {error}"
                        ),
                    )
                else:
                    restored = True
            if restored:
                try:
                    owner.unlink(quarantine)
                except Exception as error:
                    record_file_failure(path, error)

    def rollback_directory(directory: Path, owner: SecureDirectory) -> None:
        if directory in blocked_directories:
            return
        try:
            quarantine = owner.quarantine_directory_if_identity(
                directory,
                directories[directory],
            )
        except FileNotFoundError:
            pass
        except Exception as error:
            record_directory_failure(directory, error)
        else:
            try:
                owner.rmdir(quarantine)
            except Exception as error:
                record_directory_failure(directory, error)

    claimed_roots = set(claimed_filesystems)
    claimed_children = tuple(
        directory
        for directory in directories
        if directory not in claimed_roots
        and any(root in directory.parents for root in claimed_roots)
    )
    outer_directories = tuple(
        directory
        for directory in directories
        if directory not in claimed_roots and directory not in claimed_children
    )
    for directory in sorted(
        claimed_children,
        key=lambda path: len(path.parts),
        reverse=True,
    ):
        owner = _owner_for_path(directory, filesystem, claimed_filesystems)
        rollback_directory(directory, owner)
    try:
        close_claimed_owners()
    except Exception as error:
        for directory in claimed_roots:
            record_directory_failure(directory, error)
            blocked_directories.add(directory)
    for directory in sorted(
        claimed_roots,
        key=lambda path: len(path.parts),
        reverse=True,
    ):
        rollback_directory(directory, filesystem)
    for directory in sorted(
        outer_directories,
        key=lambda path: len(path.parts),
        reverse=True,
    ):
        rollback_directory(directory, filesystem)
    if failures:
        details = "\n".join(f"- {path}: {error}" for path, error in failures)
        raise RuntimeError(f"Workspace rollback failures:\n{details}") from failures[0][
            1
        ]


def _current_identity(
    filesystem: SecureDirectory,
    path: Path,
) -> FileIdentity | None:
    try:
        return filesystem.file_identity(path)
    except FileNotFoundError:
        return None


def _require_identities(
    filesystem: SecureDirectory,
    expected: Mapping[Path, FileIdentity | None],
    *,
    known: Mapping[Path, FileIdentity | None] | None = None,
) -> None:
    for path, identity in expected.items():
        current = known.get(path) if known is not None and path in known else None
        if known is None or path not in known:
            current = _current_identity(filesystem, path)
        if current != identity:
            raise ConfigurationError(
                f"Workspace file changed before the transaction committed: {path}. "
                "Run the operation again."
            )


def _require_owned_identities(
    filesystem: SecureDirectory,
    claimed_filesystems: Mapping[Path, SecureDirectory],
    expected: Mapping[Path, FileIdentity | None],
) -> None:
    for path, identity in expected.items():
        owner = _owner_for_path(path, filesystem, claimed_filesystems)
        _require_identities(owner, {path: identity})


def _require_absent_entries(
    filesystem: SecureDirectory,
    paths: Collection[Path],
) -> None:
    for path in paths:
        if filesystem.entry_exists(path):
            raise ConfigurationError(
                f"Workspace path was recreated before the transaction committed: "
                f"{path}. Run the operation again."
            )


def _require_directory_identities(
    filesystem: SecureDirectory,
    expected: Mapping[Path, FileIdentity],
) -> None:
    for path, identity in expected.items():
        if filesystem.directory_identity(path) != identity:
            raise ConfigurationError(
                f"Workspace directory changed before the transaction committed: "
                f"{path}. Run the operation again."
            )


def _expected_tree_paths(
    files: tuple[PurePosixPath, ...],
) -> frozenset[str]:
    paths = {"."}
    for file in files:
        paths.add(file.as_posix())
        paths.update(
            parent.as_posix() for parent in file.parents if parent != PurePosixPath(".")
        )
    return frozenset(paths)


def _require_directory_catalog(
    filesystem: SecureDirectory,
    directory: Path,
    files: tuple[PurePosixPath, ...],
    *,
    expected_root: FileIdentity,
) -> tuple[tuple[object, ...], ...]:
    try:
        identity = filesystem.directory_tree_identity(
            directory,
            max_entries=len(_expected_tree_paths(files)),
        )
    except SecureFileError as error:
        raise ConfigurationError(
            f"Workspace directory changed before the transaction committed: "
            f"{directory}. Run the operation again."
        ) from error
    root = identity[0] if identity else None
    root_matches = root == (
        ".",
        expected_root.mode,
        expected_root.device,
        expected_root.inode,
    )
    if (
        identity is None
        or not root_matches
        or {str(entry[0]) for entry in identity} != set(_expected_tree_paths(files))
    ):
        raise ConfigurationError(
            f"Workspace directory changed before the transaction committed: "
            f"{directory}. Run the operation again."
        )
    return identity


@contextmanager
def write_file_transaction(
    root: Path,
    writes: Mapping[Path, str | bytes],
    *,
    expected: Mapping[Path, FileIdentity | None] | None = None,
    expected_absent_entries: Collection[Path] = (),
    expected_directories: Mapping[Path, FileIdentity] | None = None,
    claimed_directories: Mapping[Path, tuple[PurePosixPath, ...]] | None = None,
) -> Iterator[None]:
    """Conditionally write files and restore prior state after a failure."""
    paths = set(writes)
    read_set = dict(expected or {})
    directory_claims = dict(claimed_directories or {})
    directory_read_set = dict(expected_directories or {})
    with secure_directory(root) as filesystem, ExitStack() as ownership:
        snapshots: dict[Path, tuple[bytes, int] | None] = {}
        initial_identities: dict[Path, FileIdentity | None] = {}
        for path in paths:
            try:
                payload, mode, identity = read_file_snapshot_with_identity(
                    path,
                    filesystem=filesystem,
                )
            except FileNotFoundError:
                snapshots[path] = None
                initial_identities[path] = None
            else:
                snapshots[path] = (payload, mode)
                initial_identities[path] = identity
        _require_identities(
            filesystem,
            read_set,
            known=initial_identities,
        )
        _require_absent_entries(filesystem, expected_absent_entries)
        _require_directory_identities(filesystem, directory_read_set)
        directories: dict[Path, FileIdentity] = {}
        claimed_filesystems: dict[Path, SecureDirectory] = {}
        written_files: dict[Path, FileIdentity] = {}
        try:
            for directory in directory_claims:
                filesystem.ensure_parent(directory, directories)
                try:
                    directories[directory] = filesystem.create_directory(directory)
                except FileExistsError as error:
                    raise ConfigurationError(
                        "Workspace directory changed before the transaction "
                        f"committed: {directory}. Run the operation again."
                    ) from error
                claimed = ownership.enter_context(secure_directory(directory))
                claimed.ensure_attached(directories[directory])
                claimed_filesystems[directory] = claimed
            for path, content in writes.items():
                owner = _owner_for_path(path, filesystem, claimed_filesystems)
                claimed_root = _claimed_root_for_path(path, claimed_filesystems)
                if claimed_root is not None:
                    owner.ensure_attached(directories[claimed_root])
                owner.ensure_parent(path, directories)
                payload = (
                    content.encode("utf-8") if isinstance(content, str) else content
                )
                if path not in read_set:
                    written_files[path] = atomic_write_bytes(
                        path,
                        payload,
                        filesystem=owner,
                    )
                    if claimed_root is not None:
                        owner.ensure_attached(directories[claimed_root])
                    continue
                expected_identity = read_set[path]
                try:
                    if expected_identity is None:
                        written_files[path] = owner.write_file_if_absent(
                            path,
                            payload,
                        )
                    else:
                        written_files[path] = owner.replace_file_if_identity(
                            path,
                            payload,
                            expected_identity,
                        )
                except ConditionalWriteError as write_error:
                    if write_error.committed is not None:
                        written_files[path] = write_error.committed
                    raise
                if claimed_root is not None:
                    owner.ensure_attached(directories[claimed_root])
            committed_trees: dict[Path, tuple[tuple[object, ...], ...]] = {}
            for directory, files in directory_claims.items():
                claimed = claimed_filesystems[directory]
                claimed.ensure_attached(directories[directory])
                claimed_files = {
                    directory.joinpath(*relative.parts): written_files[
                        directory.joinpath(*relative.parts)
                    ]
                    for relative in files
                }
                _require_identities(claimed, claimed_files)
                committed_trees[directory] = _require_directory_catalog(
                    filesystem,
                    directory,
                    files,
                    expected_root=directories[directory],
                )
                claimed.ensure_attached(directories[directory])
            committed = {
                path: identity
                for path, identity in read_set.items()
                if path not in written_files
            }
            committed.update(written_files)
            yield
            _require_absent_entries(filesystem, expected_absent_entries)
            _require_directory_identities(filesystem, directory_read_set)
            for directory, identity in committed_trees.items():
                claimed = claimed_filesystems[directory]
                claimed.ensure_attached(directories[directory])
                current = _require_directory_catalog(
                    filesystem,
                    directory,
                    directory_claims[directory],
                    expected_root=directories[directory],
                )
                claimed.ensure_attached(directories[directory])
                if current != identity:
                    raise ConfigurationError(
                        "Workspace directory changed before the transaction "
                        f"committed: {directory}. Run the operation again."
                    )
            _require_owned_identities(filesystem, claimed_filesystems, committed)
            for directory, claimed in claimed_filesystems.items():
                claimed.ensure_attached(directories[directory])
        except BaseException as error:
            try:
                _rollback(
                    filesystem,
                    snapshots,
                    directories,
                    written_files,
                    claimed_filesystems,
                    ownership.close,
                )
            except BaseException as rollback_error:
                _add_error_note(
                    error,
                    f"Workspace rollback also failed: {rollback_error}",
                )
            raise
