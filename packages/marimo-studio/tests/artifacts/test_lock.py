"""Exercise platform-specific artifact file locking behavior."""

from __future__ import annotations

import errno
import sys
from collections.abc import Callable
from types import SimpleNamespace

import pytest

import marimo_studio._artifacts.lock as lock_module


def _use_windows_lock(
    monkeypatch: pytest.MonkeyPatch,
    locking: Callable[[int, int, int], None],
) -> SimpleNamespace:
    monkeypatch.setattr(
        lock_module,
        "os",
        SimpleNamespace(name="nt", SEEK_SET=0, lseek=lambda *_: 0),
    )
    windows = SimpleNamespace(LK_LOCK=1, LK_NBLCK=2, locking=locking)
    monkeypatch.setitem(sys.modules, "msvcrt", windows)
    return windows


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
