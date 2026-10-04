"""Address directory entries through their open parent directory."""

from __future__ import annotations

import errno
import os
import stat
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Final, TypeVar

from marimo_studio._filesystem.errors import UnsafePathError

# Windows has no descriptor-relative file API. Its entries carry no parent
# descriptor, and operations address them by path after a symlink check.
DESCRIPTORS: Final = os.name != "nt"
FILE_FLAGS: Final = (
    getattr(os, "O_NOFOLLOW", 0)
    | getattr(os, "O_CLOEXEC", 0)
    | getattr(os, "O_BINARY", 0)
)
# gVisor follows a trailing symlink when O_DIRECTORY accompanies O_NOFOLLOW,
# so directories open with O_NOFOLLOW alone and fstat confirms the type.
# O_NONBLOCK keeps a FIFO swapped in at the path from blocking the open.
_DIRECTORY_FLAGS: Final = (
    os.O_RDONLY
    | getattr(os, "O_NOFOLLOW", 0)
    | getattr(os, "O_CLOEXEC", 0)
    | getattr(os, "O_NONBLOCK", 0)
)
_SHARING_ATTEMPTS: Final = 100
_SHARING_INTERVAL_SECONDS: Final = 0.01
_Result = TypeVar("_Result")
# Symbolic links, junctions, and mount points carry the name-surrogate bit.
# Data reparse points such as cloud placeholders do not redirect the path.
NAME_SURROGATE: Final = 0x20000000


def is_link(state: os.stat_result) -> bool:
    """Return whether an ``lstat`` result names a path-redirecting entry."""
    if stat.S_ISLNK(state.st_mode):
        return True
    if os.name != "nt":
        return False
    attributes = getattr(state, "st_file_attributes", 0)
    return bool(
        attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT
        and getattr(state, "st_reparse_tag", 0) & NAME_SURROGATE
    )


@dataclass(frozen=True)
class Entry:
    """One directory entry and the descriptor of the directory that holds it."""

    path: Path
    parent: int | None

    @property
    def name(self) -> str | Path:
        """Return the argument that addresses this entry with ``dir_fd=parent``."""
        return self.path if self.parent is None else self.path.name

    def sibling(self, name: str) -> Entry:
        return Entry(self.path.with_name(name), self.parent)


def retry_while_shared(operation: Callable[[], _Result]) -> _Result:
    """Retry a Windows file operation while another handle briefly holds the file.

    Antivirus scanners, indexers, and concurrent renames briefly hold files open
    without delete sharing. Other platforms run the operation once.
    """
    attempts = _SHARING_ATTEMPTS if os.name == "nt" else 1
    for attempt in range(attempts):
        try:
            return operation()
        except PermissionError:
            if attempt + 1 == attempts:
                raise
            time.sleep(_SHARING_INTERVAL_SECONDS)
    raise AssertionError("unreachable")


def open_directory(name: str | Path, *, path: Path, parent: int | None = None) -> int:
    """Open one directory without following a symlink at its final component."""
    try:
        descriptor = os.open(name, _DIRECTORY_FLAGS, dir_fd=parent)
    except OSError as error:
        if error.errno == errno.ELOOP:
            raise UnsafePathError(f"Path is a symlink: {path}") from error
        if error.errno == errno.ENOTDIR:
            raise UnsafePathError(
                f"Path ancestor is not a directory: {path}"
            ) from error
        raise
    if not stat.S_ISDIR(os.fstat(descriptor).st_mode):
        os.close(descriptor)
        raise UnsafePathError(f"Path is not a directory: {path}")
    return descriptor
