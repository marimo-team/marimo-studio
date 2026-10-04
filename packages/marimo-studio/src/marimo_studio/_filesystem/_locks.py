"""Open and lock persistent lock files with the platform's advisory locks."""

from __future__ import annotations

import errno
import os

from marimo_studio._filesystem._entry import DESCRIPTORS, FILE_FLAGS, Entry

_LOCK_FILE_MODE = 0o600


def open_lock_file(entry: Entry, *, create: bool) -> int:
    """Open one lock file for reading and writing without following a link.

    Raises ``FileNotFoundError`` when the file is absent and ``create`` is
    false.
    """
    flags = os.O_RDWR | FILE_FLAGS

    def existing() -> int:
        if DESCRIPTORS:
            return os.open(entry.name, flags, dir_fd=entry.parent)
        # A delete-sharing handle lets another process remove the tree that
        # holds a lock file, as POSIX allows.
        from marimo_studio._filesystem._windows import open_file

        return open_file(entry.path, os.O_RDWR)

    def new() -> int:
        if DESCRIPTORS:
            return os.open(
                entry.name,
                flags | os.O_CREAT | os.O_EXCL,
                _LOCK_FILE_MODE,
                dir_fd=entry.parent,
            )
        from marimo_studio._filesystem._windows import open_file

        return open_file(entry.path, os.O_RDWR, create=True)

    try:
        return existing()
    except FileNotFoundError:
        if not create:
            raise
    # Concurrent O_CREAT opens of one new name can fail with ENOENT on macOS.
    # An exclusive create settles which process creates the lock file.
    try:
        return new()
    except FileExistsError:
        return existing()


def acquire(descriptor: int, *, blocking: bool) -> bool:
    """Take the exclusive lock, or return ``False`` when it is held elsewhere."""
    if os.name == "nt":
        import msvcrt

        # msvcrt locks byte ranges, so the lock file needs one byte to lock.
        if os.fstat(descriptor).st_size == 0:
            os.lseek(descriptor, 0, os.SEEK_SET)
            os.write(descriptor, b"\0")
            os.fsync(descriptor)
        mode = msvcrt.LK_LOCK if blocking else msvcrt.LK_NBLCK
        while True:
            os.lseek(descriptor, 0, os.SEEK_SET)
            try:
                msvcrt.locking(descriptor, mode, 1)
            except OSError as error:
                if not blocking:
                    return False
                # LK_LOCK gives up after ten one-second retries.
                if error.errno != errno.EDEADLK:
                    raise
            else:
                return True

    import fcntl

    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
    except BlockingIOError:
        return False
    return True


def release(descriptor: int) -> None:
    if os.name == "nt":
        import msvcrt

        os.lseek(descriptor, 0, os.SEEK_SET)
        msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
        return

    import fcntl

    fcntl.flock(descriptor, fcntl.LOCK_UN)
