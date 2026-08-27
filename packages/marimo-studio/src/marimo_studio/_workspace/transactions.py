"""Apply related workspace file writes as one recoverable operation."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path

from marimo_studio._filesystem.io import (
    atomic_write_bytes,
    read_file_snapshot,
)
from marimo_studio._filesystem.secure import (
    FileIdentity,
    SecureDirectory,
    secure_directory,
)


def _add_error_note(error: BaseException, note: str) -> None:
    add_note = getattr(error, "add_note", None)
    if callable(add_note):
        add_note(note)
        return
    notes: list[str] = list(getattr(error, "__notes__", ()))
    notes.append(note)
    error.__notes__ = notes


def _rollback(
    filesystem: SecureDirectory,
    snapshots: Mapping[Path, tuple[bytes, int] | None],
    directories: Mapping[Path, FileIdentity],
    written_files: Mapping[Path, FileIdentity],
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
        try:
            quarantine = filesystem.quarantine_if_identity(path, identity)
        except FileNotFoundError:
            if snapshot is not None:
                content, mode = snapshot
                try:
                    filesystem.restore_file_if_absent(path, content, mode)
                except Exception as error:
                    record_file_failure(path, error)
        except Exception as error:
            record_file_failure(path, error)
        else:
            restored = snapshot is None
            if snapshot is not None:
                content, mode = snapshot
                try:
                    filesystem.restore_file_if_absent(path, content, mode)
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
                    filesystem.unlink(quarantine)
                except Exception as error:
                    record_file_failure(path, error)
    for directory in sorted(
        directories, key=lambda path: len(path.parts), reverse=True
    ):
        if directory in blocked_directories:
            continue
        try:
            quarantine = filesystem.quarantine_directory_if_identity(
                directory,
                directories[directory],
            )
        except FileNotFoundError:
            pass
        except Exception as error:
            record_directory_failure(directory, error)
        else:
            try:
                filesystem.rmdir(quarantine)
            except Exception as error:
                record_directory_failure(directory, error)
    if failures:
        details = "\n".join(f"- {path}: {error}" for path, error in failures)
        raise RuntimeError(f"Workspace rollback failures:\n{details}") from failures[0][
            1
        ]


@contextmanager
def write_file_transaction(
    root: Path,
    writes: Mapping[Path, str | bytes],
) -> Iterator[None]:
    """Write text or binary files and restore prior state after a failure."""
    paths = set(writes)
    with secure_directory(root) as filesystem:
        snapshots: dict[Path, tuple[bytes, int] | None] = {}
        for path in paths:
            try:
                snapshots[path] = read_file_snapshot(path, filesystem=filesystem)
            except FileNotFoundError:
                snapshots[path] = None
        directories: dict[Path, FileIdentity] = {}
        written_files: dict[Path, FileIdentity] = {}
        try:
            for path, content in writes.items():
                filesystem.ensure_parent(path, directories)
                payload = (
                    content.encode("utf-8") if isinstance(content, str) else content
                )
                written_files[path] = atomic_write_bytes(
                    path,
                    payload,
                    filesystem=filesystem,
                )
            yield
        except BaseException as error:
            try:
                _rollback(filesystem, snapshots, directories, written_files)
            except BaseException as rollback_error:
                _add_error_note(
                    error,
                    f"Workspace rollback also failed: {rollback_error}",
                )
            raise
