"""Read and atomically replace contained application files."""

from __future__ import annotations

import hashlib
import os
import stat
from pathlib import Path

from marimo_studio._filesystem.secure import (
    FileIdentity,
    SecureDirectory,
    atomic_write_contained,
    open_contained_file,
)
from marimo_studio.errors import ConfigurationError

_WORKSPACE_FILE_MAX_BYTES = 64 * 1024 * 1024


def _read_file_snapshot(
    path: Path,
    *,
    root: Path | None = None,
    filesystem: SecureDirectory | None = None,
) -> tuple[bytes, int, os.stat_result]:
    try:
        descriptor = (
            filesystem.open_file(path)
            if filesystem is not None
            else open_contained_file(root or path.parent, path)
        )
    except FileNotFoundError:
        raise
    except OSError as error:
        raise ConfigurationError(f"Could not open workspace file: {path}") from error
    try:
        with os.fdopen(descriptor, "rb") as stream:
            before = os.fstat(stream.fileno())
            if not stat.S_ISREG(before.st_mode):
                raise ConfigurationError(f"Workspace path is not a file: {path}")
            if before.st_size > _WORKSPACE_FILE_MAX_BYTES:
                raise ConfigurationError(
                    "Workspace file exceeds the "
                    f"{_WORKSPACE_FILE_MAX_BYTES}-byte limit: {path}"
                )
            payload = stream.read(before.st_size)
            if len(payload) != before.st_size or stream.read(1):
                raise ConfigurationError(
                    f"Workspace file changed while it was read: {path}"
                )
            after = os.fstat(stream.fileno())
    except OSError as error:
        raise ConfigurationError(f"Could not read workspace file: {path}") from error
    if (
        before.st_dev != after.st_dev
        or before.st_ino != after.st_ino
        or before.st_mode != after.st_mode
        or before.st_size != after.st_size
        or before.st_mtime_ns != after.st_mtime_ns
        or before.st_ctime_ns != after.st_ctime_ns
    ):
        raise ConfigurationError(f"Workspace file changed while it was read: {path}")
    return payload, stat.S_IMODE(before.st_mode), before


def read_file_snapshot(
    path: Path,
    *,
    root: Path | None = None,
    filesystem: SecureDirectory | None = None,
) -> tuple[bytes, int]:
    """Read stable bytes and mode through one contained file descriptor."""
    payload, mode, _state = _read_file_snapshot(
        path,
        root=root,
        filesystem=filesystem,
    )
    return payload, mode


def read_file_snapshot_with_identity(
    path: Path,
    *,
    root: Path | None = None,
    filesystem: SecureDirectory | None = None,
) -> tuple[bytes, int, FileIdentity]:
    """Read stable bytes, mode, and content identity from one descriptor."""
    payload, mode, state = _read_file_snapshot(
        path,
        root=root,
        filesystem=filesystem,
    )
    return (
        payload,
        mode,
        FileIdentity(
            state.st_dev,
            state.st_ino,
            state.st_mode,
            state.st_size,
            hashlib.sha256(payload).digest(),
            False,
        ),
    )


def read_bytes(path: Path, *, root: Path | None = None) -> bytes:
    """Read one stable contained workspace file."""
    return read_file_snapshot(path, root=root)[0]


def read_text(path: Path, *, root: Path | None = None) -> str:
    """Read UTF-8 text without translating line endings."""
    return read_bytes(path, root=root).decode("utf-8")


def reject_mutable_symlinks(root: Path, paths: set[Path]) -> None:
    """Reject symlinks between the workspace root and each mutable path."""
    root = root.absolute()
    for path in paths:
        candidate = path.absolute()
        try:
            relative = candidate.relative_to(root)
        except ValueError as error:
            raise ConfigurationError(
                f"Mutable workspace path is outside the workspace root: {candidate}"
            ) from error
        current = root
        for part in relative.parts:
            current /= part
            if current.is_symlink():
                raise ConfigurationError(
                    f"Mutable workspace path is a symlink: {current}"
                )


def atomic_write_text(
    path: Path,
    content: str,
    *,
    root: Path | None = None,
) -> FileIdentity:
    """Replace a text file through a temporary file in the same directory."""
    return atomic_write_bytes(path, content.encode("utf-8"), root=root)


def atomic_write_bytes(
    path: Path,
    content: bytes,
    *,
    root: Path | None = None,
    filesystem: SecureDirectory | None = None,
    mode: int | None = None,
) -> FileIdentity:
    """Replace a binary file through a temporary file in the same directory."""
    try:
        if filesystem is not None:
            return filesystem.atomic_write(path, content, mode=mode)
        return atomic_write_contained(root or path.parent, path, content, mode=mode)
    except OSError as error:
        raise ConfigurationError(
            f"Could not replace mutable workspace file: {path}"
        ) from error
