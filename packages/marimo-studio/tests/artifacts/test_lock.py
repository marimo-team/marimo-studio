"""Exercise platform-specific artifact file locking behavior."""

from __future__ import annotations

import errno
import sys
from collections.abc import Callable
from types import SimpleNamespace

import pytest

import marimo_studio._filesystem.file_lock as lock_module


def _use_windows_lock(
    monkeypatch: pytest.MonkeyPatch,
    locking: Callable[[int, int, int], None],
) -> SimpleNamespace:
    monkeypatch.setattr(
        lock_module,
        "os",
        SimpleNamespace(
            name="nt",
            SEEK_SET=0,
            fstat=lambda _: SimpleNamespace(st_size=1),
            lseek=lambda *_: 0,
        ),
    )
    windows = SimpleNamespace(LK_LOCK=1, LK_NBLCK=2, locking=locking)
    monkeypatch.setitem(sys.modules, "msvcrt", windows)
    return windows


def test_windows_empty_lock_file_is_initialized_before_acquisition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operations: list[tuple[object, ...]] = []
    monkeypatch.setattr(
        lock_module,
        "os",
        SimpleNamespace(
            name="nt",
            SEEK_SET=0,
            fstat=lambda descriptor: SimpleNamespace(st_size=0),
            lseek=lambda *arguments: operations.append(("seek", *arguments)),
            write=lambda *arguments: operations.append(("write", *arguments)),
            fsync=lambda *arguments: operations.append(("sync", *arguments)),
        ),
    )
    windows = SimpleNamespace(
        LK_LOCK=1,
        LK_NBLCK=2,
        locking=lambda *arguments: operations.append(("lock", *arguments)),
    )
    monkeypatch.setitem(sys.modules, "msvcrt", windows)

    assert lock_module.acquire_file_lock(17, blocking=True)
    assert operations == [
        ("seek", 17, 0, 0),
        ("write", 17, b"\0"),
        ("sync", 17),
        ("seek", 17, 0, 0),
        ("lock", 17, windows.LK_LOCK, 1),
    ]


def test_windows_blocking_lock_retries_until_acquired(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts = 0

    def locking(_descriptor: int, mode: int, _size: int) -> None:
        nonlocal attempts
        assert mode == windows.LK_LOCK
        attempts += 1
        if attempts < 3:
            raise OSError(errno.EDEADLK, "contended")

    windows = _use_windows_lock(monkeypatch, locking)

    assert lock_module.acquire_file_lock(17, blocking=True)


def test_windows_blocking_lock_propagates_permanent_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts = 0

    def locking(_descriptor: int, mode: int, _size: int) -> None:
        nonlocal attempts
        assert mode == windows.LK_LOCK
        attempts += 1
        raise OSError(errno.EBADF, "invalid descriptor")

    windows = _use_windows_lock(monkeypatch, locking)

    with pytest.raises(OSError, match="invalid descriptor"):
        lock_module.acquire_file_lock(17, blocking=True)
    assert attempts == 1


def test_windows_nonblocking_lock_returns_after_first_contention(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts = 0

    def locking(_descriptor: int, mode: int, _size: int) -> None:
        nonlocal attempts
        assert mode == windows.LK_NBLCK
        attempts += 1
        raise OSError("contended")

    windows = _use_windows_lock(monkeypatch, locking)

    assert not lock_module.acquire_file_lock(17, blocking=False)
    assert attempts == 1
