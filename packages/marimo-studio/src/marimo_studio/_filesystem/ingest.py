"""Copy untrusted build output into a new Studio-owned directory.

Provider builds run with write access limited to their staging directory, so
the staging tree is the one input that a lower-privilege process controls
while Studio reads it. ``copy_tree`` traverses it through directory
descriptors and never follows a symlink, rejects every entry other than
directories and regular files, enforces the caller's file budget and a bound
on directories and nesting, and copies each file into a fresh directory that
only Studio writes. Later reads and publication operate on that copy.
"""

from __future__ import annotations

import hashlib
import os
import stat
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from marimo_studio._filesystem._entry import changed, open_directory
from marimo_studio._filesystem.budgets import FileBudget, FileBudgetTracker
from marimo_studio._filesystem.errors import ConcurrentChangeError, UnsafePathError
from marimo_studio.errors import ConfigurationError

_CHUNK_BYTES = 1024 * 1024
_PERMISSION_BITS = 0o777
# Build output nests a few levels. The bound also keeps the copy within the
# interpreter's recursion limit.
_MAX_DEPTH = 64
_NEW_FILE_FLAGS = (
    os.O_WRONLY
    | os.O_CREAT
    | os.O_EXCL
    | getattr(os, "O_NOFOLLOW", 0)
    | getattr(os, "O_CLOEXEC", 0)
    | getattr(os, "O_BINARY", 0)
)
# O_NONBLOCK keeps a FIFO swapped in after the stat from blocking the open.
_SOURCE_FLAGS = (
    os.O_RDONLY
    | getattr(os, "O_NOFOLLOW", 0)
    | getattr(os, "O_CLOEXEC", 0)
    | getattr(os, "O_NONBLOCK", 0)
)


@dataclass(frozen=True)
class IngestedFile:
    """One copied regular file with its SHA-256 digest and byte size."""

    path: PurePosixPath
    digest: str
    size: int


def copy_tree(
    source: int | Path,
    destination: int | Path,
    *,
    budget: FileBudget,
    label: str,
) -> tuple[IngestedFile, ...]:
    """Copy every regular file below one open directory into another.

    POSIX callers pass directory descriptors and Windows callers pass paths.
    """
    walk = _Walk(FileBudgetTracker(budget, label), label)
    if isinstance(source, int) and isinstance(destination, int):
        _copy_posix_tree(source, destination, PurePosixPath(), walk)
    elif isinstance(source, Path) and isinstance(destination, Path):
        _copy_windows_tree(source, destination, PurePosixPath(), walk)
    else:
        raise TypeError("Source and destination must use the same handle kind")
    return tuple(sorted(walk.files, key=lambda item: item.path.as_posix()))


@dataclass
class _Walk:
    tracker: FileBudgetTracker
    label: str
    files: list[IngestedFile] = field(default_factory=list)
    directories: int = 0

    def enter_directory(self, relative: PurePosixPath) -> None:
        self.directories += 1
        limit = self.tracker.budget.max_files
        if self.directories > limit:
            raise ConfigurationError(
                f"{self.label} contains more than {limit} directories. "
                "Remove directories or split the project."
            )
        if len(relative.parts) > _MAX_DEPTH:
            raise ConfigurationError(
                f"{self.label} nests deeper than {_MAX_DEPTH} directories: {relative}"
            )


def _changed(label: str, relative: PurePosixPath) -> ConcurrentChangeError:
    return ConcurrentChangeError(f"{label} changed while it was copied: {relative}")


def _copy_stream(
    source: int,
    state: os.stat_result,
    target: int,
    relative: PurePosixPath,
    label: str,
) -> IngestedFile:
    digest = hashlib.sha256()
    with os.fdopen(target, "wb") as output:
        remaining = state.st_size
        while remaining:
            chunk = os.read(source, min(_CHUNK_BYTES, remaining))
            if not chunk:
                break
            digest.update(chunk)
            output.write(chunk)
            remaining -= len(chunk)
        # A same-size rewrite during the copy shows up in the timestamps.
        if remaining or os.read(source, 1) or changed(state, os.fstat(source)):
            raise _changed(label, relative)
        output.flush()
        if hasattr(os, "fchmod"):
            os.fchmod(output.fileno(), stat.S_IMODE(state.st_mode) & _PERMISSION_BITS)
        os.fsync(output.fileno())
    return IngestedFile(relative, digest.hexdigest(), state.st_size)


def _copy_posix_tree(
    source: int,
    destination: int,
    relative: PurePosixPath,
    walk: _Walk,
) -> None:
    with os.scandir(source) as listing:
        for item in listing:
            name = item.name
            child = relative / name
            state = os.stat(name, dir_fd=source, follow_symlinks=False)
            if stat.S_ISDIR(state.st_mode):
                walk.enter_directory(child)
                nested_source = open_directory(name, parent=source, path=Path(child))
                try:
                    if not os.path.samestat(os.fstat(nested_source), state):
                        raise _changed(walk.label, child)
                    os.mkdir(name, 0o700, dir_fd=destination)
                    nested_destination = open_directory(
                        name, parent=destination, path=Path(child)
                    )
                    try:
                        _copy_posix_tree(nested_source, nested_destination, child, walk)
                    finally:
                        os.close(nested_destination)
                finally:
                    os.close(nested_source)
                continue
            if not stat.S_ISREG(state.st_mode):
                kind = "symlink" if stat.S_ISLNK(state.st_mode) else "special file"
                raise UnsafePathError(f"{walk.label} contains a {kind}: {child}")
            try:
                descriptor = os.open(name, _SOURCE_FLAGS, dir_fd=source)
            except OSError as error:
                raise _changed(walk.label, child) from error
            try:
                opened = os.fstat(descriptor)
                if not stat.S_ISREG(opened.st_mode) or not os.path.samestat(
                    opened, state
                ):
                    raise _changed(walk.label, child)
                walk.tracker.add(child.as_posix(), opened.st_size)
                target = os.open(name, _NEW_FILE_FLAGS, 0o600, dir_fd=destination)
                walk.files.append(
                    _copy_stream(descriptor, opened, target, child, walk.label)
                )
            finally:
                os.close(descriptor)


def _copy_windows_tree(
    directory: Path,
    destination: Path,
    relative: PurePosixPath,
    walk: _Walk,
) -> None:
    from marimo_studio._filesystem._windows import (
        close_handle,
        open_directory_handle,
        open_file,
    )

    # The held handle keeps the listed directory from being replaced by a
    # junction while its entries are copied.
    handle = open_directory_handle(directory)
    try:
        with os.scandir(directory) as listing:
            for item in listing:
                child = relative / item.name
                path = directory / item.name
                # DirEntry.stat omits the file index on Windows.
                state = os.lstat(path)
                if stat.S_ISDIR(state.st_mode) and not item.is_symlink():
                    walk.enter_directory(child)
                    os.mkdir(destination / item.name, 0o700)
                    _copy_windows_tree(path, destination / item.name, child, walk)
                    continue
                descriptor = open_file(path, os.O_RDONLY)
                try:
                    opened = os.fstat(descriptor)
                    if not os.path.samestat(opened, state):
                        raise _changed(walk.label, child)
                    walk.tracker.add(child.as_posix(), opened.st_size)
                    target = os.open(destination / item.name, _NEW_FILE_FLAGS, 0o600)
                    walk.files.append(
                        _copy_stream(descriptor, opened, target, child, walk.label)
                    )
                finally:
                    os.close(descriptor)
    finally:
        close_handle(handle)
