"""Lock file descriptors across processes on supported platforms."""

from __future__ import annotations

import errno
import os


def acquire_file_lock(descriptor: int, *, blocking: bool) -> bool:
    """Acquire an exclusive descriptor lock, returning false on contention."""
    if os.name == "nt":
        import msvcrt

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
                if error.errno != errno.EDEADLK:
                    raise
            else:
                return True

    import fcntl

    flags = fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB)
    try:
        fcntl.flock(descriptor, flags)
    except BlockingIOError:
        return False
    return True


def release_file_lock(descriptor: int) -> None:
    """Release an exclusive descriptor lock."""
    if os.name == "nt":
        import msvcrt

        os.lseek(descriptor, 0, os.SEEK_SET)
        msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
        return

    import fcntl

    fcntl.flock(descriptor, fcntl.LOCK_UN)
