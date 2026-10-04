"""Rename filesystem entries without replacing concurrently created paths."""

from __future__ import annotations

import ctypes
import errno
import functools
import os
import stat
import sys
from collections.abc import Callable

from marimo_studio._filesystem._entry import Entry, retry_while_shared
from marimo_studio._filesystem.errors import UnsafePathError
from marimo_studio._filesystem.names import TemporaryKind, temporary_name

_COLLISIONS = frozenset({errno.EEXIST, errno.ENOTEMPTY})
# NFS, FUSE, and gVisor host mounts reject the exclusive rename flag with
# EINVAL. Kernels and sandboxes without the system call report ENOSYS.
_NO_EXCLUSIVE_RENAME = frozenset(
    {errno.EINVAL, errno.ENOSYS, errno.ENOTSUP, errno.EOPNOTSUPP}
)

_ExclusiveRename = Callable[[int, bytes, int, bytes, int], int]
_Fallback = Callable[[int, str, int, str], None]


@functools.cache
def _native_exclusive_rename() -> tuple[_ExclusiveRename, int] | None:
    if sys.platform == "darwin":
        name, flag = "renameatx_np", 0x00000004  # RENAME_EXCL
    elif sys.platform.startswith("linux"):
        name, flag = "renameat2", 0x00000001  # RENAME_NOREPLACE
    else:
        return None
    rename = getattr(ctypes.CDLL(None, use_errno=True), name, None)
    if rename is None:
        return None
    rename.argtypes = (
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    )
    rename.restype = ctypes.c_int
    return rename, flag


def _rename_natively(
    source_fd: int,
    source: str,
    destination_fd: int,
    destination: str,
) -> bool:
    """Return whether the filesystem performed one exclusive native rename."""
    native = _native_exclusive_rename()
    if native is None:
        return False
    rename, flag = native
    if (
        rename(
            source_fd,
            os.fsencode(source),
            destination_fd,
            os.fsencode(destination),
            flag,
        )
        == 0
    ):
        return True
    code = ctypes.get_errno()
    if code in _NO_EXCLUSIVE_RENAME:
        return False
    if code in _COLLISIONS:
        raise FileExistsError(code, os.strerror(code), destination)
    raise OSError(code, os.strerror(code), source, destination)


def _claim_then_rename(
    source_fd: int,
    source: str,
    destination_fd: int,
    destination: str,
) -> None:
    # An exclusive placeholder of the source's kind reserves the destination.
    # rename(2) then replaces the placeholder and refuses a directory that a
    # concurrent writer populated.
    state = os.stat(source, dir_fd=source_fd, follow_symlinks=False)
    directory = stat.S_ISDIR(state.st_mode)
    if directory:
        os.mkdir(destination, 0o700, dir_fd=destination_fd)
    else:
        os.close(
            os.open(
                destination,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o600,
                dir_fd=destination_fd,
            )
        )
    claim = os.stat(destination, dir_fd=destination_fd, follow_symlinks=False)
    try:
        os.rename(
            source,
            destination,
            src_dir_fd=source_fd,
            dst_dir_fd=destination_fd,
        )
    except OSError as error:
        _release_claim(destination_fd, destination, claim, directory=directory)
        if error.errno in _COLLISIONS:
            raise FileExistsError(error.errno, error.strerror, destination) from error
        raise


def _release_claim(
    destination_fd: int,
    destination: str,
    claim: os.stat_result,
    *,
    directory: bool,
) -> None:
    try:
        current = os.stat(destination, dir_fd=destination_fd, follow_symlinks=False)
        if (current.st_dev, current.st_ino) != (claim.st_dev, claim.st_ino):
            return
        if directory:
            os.rmdir(destination, dir_fd=destination_fd)
        elif current.st_size == 0:
            os.unlink(destination, dir_fd=destination_fd)
    except OSError:
        return


def _same_entry(
    source_fd: int,
    source: str,
    destination_fd: int,
    destination: str,
) -> bool:
    try:
        moved = os.stat(source, dir_fd=source_fd, follow_symlinks=False)
        current = os.stat(destination, dir_fd=destination_fd, follow_symlinks=False)
    except OSError:
        return False
    return os.path.samestat(moved, current)


def _link_or_claim(
    source_fd: int,
    source: str,
    destination_fd: int,
    destination: str,
) -> None:
    try:
        os.link(
            source,
            destination,
            src_dir_fd=source_fd,
            dst_dir_fd=destination_fd,
            follow_symlinks=False,
        )
    except FileExistsError:
        # An NFS client that retransmits a LINK whose reply was lost reports
        # EEXIST for the link it made.
        if not _same_entry(source_fd, source, destination_fd, destination):
            raise
    except OSError:
        # Directories refuse hard links, and FUSE drivers report missing link
        # support as EPERM, ENOTSUP, ENOSYS, or EIO. The claim raises the
        # collision or the real error when the link failed for another reason.
        _claim_then_rename(source_fd, source, destination_fd, destination)
        return
    os.unlink(source, dir_fd=source_fd)


def _rename_exclusive(source: Entry, destination: Entry, fallback: _Fallback) -> None:
    if os.name == "nt":
        from marimo_studio._filesystem._windows import rename_exclusive

        retry_while_shared(lambda: rename_exclusive(source.path, destination.path))
        return
    if source.parent is None or destination.parent is None:
        raise UnsafePathError(f"Cannot rename a tree root: {source.path}")
    names = (source.path.name, destination.path.name)
    if not _rename_natively(source.parent, names[0], destination.parent, names[1]):
        fallback(source.parent, names[0], destination.parent, names[1])


def publish_entry(source: Entry, destination: Entry) -> None:
    """Rename an entry the caller owns when the destination remains absent.

    Raises ``FileExistsError`` when the destination exists. Filesystems without
    an exclusive rename publish files through an exclusive hard link, then
    unlink the source name. Directories, and files on filesystems without hard
    links, reserve the destination with an empty placeholder that the rename
    replaces.
    """
    _rename_exclusive(source, destination, _link_or_claim)


def move_aside(entry: Entry, kind: TemporaryKind) -> Entry:
    """Move one entry to a fresh sibling and return the sibling.

    The source may be a contested name. Only this call knows the fresh sibling,
    so its placeholder fallback moves the source in one rename.
    """
    destination = entry.sibling(temporary_name(kind))
    _rename_exclusive(entry, destination, _claim_then_rename)
    return destination
