"""Conditionally replace files while preserving concurrent writes."""

from __future__ import annotations

import errno
import os
import secrets
import stat
from contextlib import suppress
from pathlib import Path
from typing import Protocol

from marimo_studio._filesystem._secure_operations import (
    copy_file_if_absent_at,
    open_file_at,
    regular_identity,
)
from marimo_studio._filesystem._secure_types import (
    ConditionalWriteError,
    FileIdentity,
    ParentContext,
    SecureFileError,
)


class ConditionalFilesystem(Protocol):
    def create_file(self, path: Path, mode: int = 0o600) -> int: ...

    def file_identity(self, path: Path) -> FileIdentity: ...

    def quarantine_if_identity(
        self,
        path: Path,
        expected: FileIdentity,
    ) -> Path: ...

    def rename_if_absent(self, source: Path, destination: Path) -> None: ...

    def unlink(self, path: Path) -> None: ...


def _finalize_failed_replacement(
    filesystem: ConditionalFilesystem,
    claimed: Path,
    path: Path,
) -> None:
    try:
        filesystem.rename_if_absent(claimed, path)
    except FileExistsError:
        try:
            filesystem.unlink(claimed)
        except OSError as cleanup_error:
            raise ConditionalWriteError(
                "The previous source is preserved after a failed commit",
                recovery=claimed,
            ) from cleanup_error
    except OSError as restore_error:
        raise ConditionalWriteError(
            "The previous source is preserved after a failed commit",
            recovery=claimed,
        ) from restore_error


def replace_file_if_identity(
    filesystem: ConditionalFilesystem,
    path: Path,
    content: bytes,
    expected: FileIdentity,
) -> FileIdentity:
    """Replace one regular file when its full identity is still current."""
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(16)}.cas")
    descriptor = filesystem.create_file(temporary, stat.S_IMODE(expected.mode))
    temporary_exists = True
    try:
        view = memoryview(content)
        while view:
            written = os.write(descriptor, view)
            if not written:
                raise SecureFileError(f"Could not write replacement source: {path}")
            view = view[written:]
        if hasattr(os, "fchmod"):
            os.fchmod(descriptor, stat.S_IMODE(expected.mode))
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = -1
        claimed = filesystem.quarantine_if_identity(path, expected)
        try:
            filesystem.rename_if_absent(temporary, path)
            temporary_exists = False
        except BaseException:
            _finalize_failed_replacement(filesystem, claimed, path)
            raise
        try:
            identity = filesystem.file_identity(path)
        except BaseException:
            _finalize_failed_replacement(filesystem, claimed, path)
            raise
        try:
            filesystem.unlink(claimed)
        except OSError as cleanup_error:
            raise ConditionalWriteError(
                "The previous source is preserved after the commit",
                recovery=claimed,
            ) from cleanup_error
        return identity
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if temporary_exists:
            with suppress(FileNotFoundError):
                filesystem.unlink(temporary)


def quarantine_if_identity(
    parent_context: ParentContext,
    path: Path,
    expected: FileIdentity,
) -> Path:
    """Move one leaf aside atomically, then verify the moved identity."""
    with parent_context(path) as parent:
        target: str | Path = path.name if parent.descriptor is not None else path
        quarantine_name = f".{path.name}.rollback-{secrets.token_hex(8)}"
        quarantine: str | Path = (
            quarantine_name
            if parent.descriptor is not None
            else parent.path / quarantine_name
        )
        os.rename(
            target,
            quarantine,
            src_dir_fd=parent.descriptor,
            dst_dir_fd=parent.descriptor,
        )
        state = os.stat(
            quarantine,
            dir_fd=parent.descriptor,
            follow_symlinks=False,
        )
        actual: FileIdentity | None = None
        basic_identity_matches = (
            state.st_dev == expected.device
            and state.st_ino == expected.inode
            and state.st_mode == expected.mode
            and not expected.directory
            and state.st_size == expected.size
        )
        if basic_identity_matches and stat.S_ISREG(state.st_mode):
            descriptor = open_file_at(
                parent,
                path.with_name(quarantine_name),
                os.O_RDONLY,
            )
            try:
                actual = regular_identity(descriptor)
            finally:
                os.close(descriptor)
        if actual == expected:
            return path.with_name(quarantine_name)
        recovered = False
        if not stat.S_ISDIR(state.st_mode):
            try:
                os.link(
                    quarantine,
                    target,
                    src_dir_fd=parent.descriptor,
                    dst_dir_fd=parent.descriptor,
                    follow_symlinks=False,
                )
            except FileExistsError:
                pass
            except OSError as error:
                unsupported = {
                    errno.EPERM,
                    errno.EXDEV,
                    getattr(errno, "ENOTSUP", errno.EPERM),
                    getattr(errno, "EOPNOTSUPP", errno.EPERM),
                }
                if error.errno in unsupported and stat.S_ISREG(state.st_mode):
                    try:
                        copy_file_if_absent_at(
                            parent,
                            quarantine,
                            target,
                            stat.S_IMODE(state.st_mode),
                        )
                    except Exception:
                        pass
                    else:
                        os.unlink(quarantine, dir_fd=parent.descriptor)
                        recovered = True
            else:
                os.unlink(quarantine, dir_fd=parent.descriptor)
                recovered = True
        location = path if recovered else path.with_name(quarantine_name)
        raise ConditionalWriteError(
            f"Contained leaf changed before rollback and was preserved at {location}",
            recovery=None if recovered else location,
        )
