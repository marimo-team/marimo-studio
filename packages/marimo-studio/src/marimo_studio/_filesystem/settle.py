"""Repeat a read that overlapped a change to the file it depends on."""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path
from typing import Final, TypeVar

from marimo_studio._filesystem.errors import ConcurrentChangeError
from marimo_studio.errors import MarimoStudioError

_ATTEMPTS: Final = 3
_INTERVAL_SECONDS: Final = 0.01
_Result = TypeVar("_Result")


def _stamp(path: Path) -> tuple[int, int, int, int] | None:
    try:
        state = path.stat()
    except OSError:
        return None
    return state.st_ino, state.st_size, state.st_mtime_ns, state.st_ctime_ns


def while_unchanged(path: Path, operation: Callable[[], _Result]) -> _Result:
    """Return ``operation()`` from an attempt during which ``path`` stayed unchanged.

    Marimo saves a notebook by truncating it and writing it again, so a
    concurrent read can see partial content and still succeed or fail. An
    attempt that overlapped a change repeats after a pause that lets the writer
    finish, including an attempt that raised ``MarimoStudioError``. A failure
    or an empty file counts only once the file stays unchanged across a pause.
    A file that keeps changing raises ``ConcurrentChangeError``, which callers
    may retry.
    """
    confirmed: tuple[int, int, int, int] | None = None

    def settled(before: tuple[int, int, int, int] | None, *, failed: bool) -> bool:
        nonlocal confirmed
        after = _stamp(path)
        if after != before:
            return False
        # A save can pause after truncating the file or partway through writing
        # it. Partial content can fail or read as empty, so those results wait
        # for the file to stay unchanged across a pause.
        suspect = after is not None and (failed or after[1] == 0)
        if suspect and after != confirmed:
            confirmed = after
            return False
        return True

    for attempt in range(_ATTEMPTS):
        if attempt:
            time.sleep(_INTERVAL_SECONDS)
        before = _stamp(path)
        try:
            result = operation()
        except MarimoStudioError:
            if settled(before, failed=True):
                raise
            continue
        if settled(before, failed=False):
            return result
    raise ConcurrentChangeError(f"File kept changing while it was read: {path}")
