"""Serialize one view's cross-process filesystem mutations."""

from __future__ import annotations

import os
import threading
from collections.abc import Generator, Iterator
from contextlib import ExitStack, contextmanager
from pathlib import Path
from weakref import WeakValueDictionary

from marimo_studio._filesystem.file_lock import (
    acquire_file_lock as _acquire_file_lock,
)
from marimo_studio._filesystem.file_lock import (
    release_file_lock as _release_file_lock,
)
from marimo_studio._filesystem.io import reject_mutable_symlinks
from marimo_studio._filesystem.secure import SecureDirectory, secure_directory
from marimo_studio._workspace.models import VIEW_PATTERN
from marimo_studio.errors import ConfigurationError

_THREAD_LOCKS_GUARD = threading.Lock()
_THREAD_LOCKS: WeakValueDictionary[Path, threading.RLock] = WeakValueDictionary()
_THREAD_LOCKS_PID = os.getpid()
_HELD = threading.local()


def _thread_lock(path: Path) -> threading.RLock:
    global _THREAD_LOCKS, _THREAD_LOCKS_PID
    with _THREAD_LOCKS_GUARD:
        if os.getpid() != _THREAD_LOCKS_PID:
            _THREAD_LOCKS = WeakValueDictionary()
            _THREAD_LOCKS_PID = os.getpid()
        lock = _THREAD_LOCKS.get(path)
        if lock is None:
            lock = threading.RLock()
            _THREAD_LOCKS[path] = lock
        return lock


def _held_paths() -> set[Path]:
    pid = os.getpid()
    if getattr(_HELD, "pid", None) != pid:
        _HELD.pid = pid
        _HELD.paths = set()
    return _HELD.paths


def _require_lock_owner(
    filesystem: SecureDirectory,
    lock_path: Path,
    expected: tuple[int, int, int],
    phase: str,
) -> None:
    try:
        current = filesystem.file_owner(lock_path)
    except OSError as error:
        raise ConfigurationError(f"View mutation lock {phase}: {lock_path}") from error
    if current != expected:
        raise ConfigurationError(f"View mutation lock {phase}: {lock_path}")


@contextmanager
def _mutation_lock(
    view_root: Path,
    filename: str,
    *,
    blocking: bool = True,
) -> Generator[bool, None, None]:
    root = view_root.absolute()
    control = root / ".locks"
    boundary = Path(root.anchor)
    lock_path = control / filename
    reject_mutable_symlinks(boundary, {root, control, lock_path})
    thread_lock = _thread_lock(lock_path)
    if not thread_lock.acquire(blocking=blocking):
        yield False
        return
    try:
        held = _held_paths()
        if lock_path in held:
            yield True
            return
        owner = ExitStack()
        try:
            filesystem = owner.enter_context(secure_directory(boundary))
            filesystem.ensure_directory(root)
            filesystem.ensure_directory(control)
            descriptor = filesystem.open_or_create_file(lock_path)
        except OSError as error:
            owner.close()
            raise ConfigurationError(
                f"Could not open view mutation lock: {lock_path}"
            ) from error
        acquired = False
        try:
            acquired = _acquire_file_lock(descriptor, blocking=blocking)
            if not acquired:
                yield False
                return
            lock_state = os.fstat(descriptor)
            lock_owner = (lock_state.st_dev, lock_state.st_ino, lock_state.st_mode)
            _require_lock_owner(
                filesystem,
                lock_path,
                lock_owner,
                "changed before acquisition",
            )
            held.add(lock_path)
            yield True
            _require_lock_owner(
                filesystem,
                lock_path,
                lock_owner,
                "changed while held",
            )
        finally:
            held.discard(lock_path)
            if acquired:
                _release_file_lock(descriptor)
            os.close(descriptor)
            owner.close()
    finally:
        thread_lock.release()


@contextmanager
def workspace_catalog_lock(view_root: Path) -> Iterator[None]:
    """Lock the configured view catalog before acquiring individual views."""
    root = view_root.absolute()
    catalog = root / ".locks" / ".catalog.lock"
    held = _held_paths()
    if catalog not in held and any(
        path.parent == catalog.parent and path != catalog for path in held
    ):
        raise RuntimeError("Acquire the workspace catalog lock before view locks")
    with _mutation_lock(root, catalog.name):
        yield


@contextmanager
def view_mutation_lock(view_root: Path, view_name: str) -> Iterator[None]:
    """Lock one view name outside its replaceable project directory.

    Acquire this after the workspace catalog lock when a transaction changes
    catalog membership. Build and source transactions can acquire it directly.
    """
    if VIEW_PATTERN.fullmatch(view_name) is None:
        raise ConfigurationError(f"Invalid Studio view name {view_name!r}")
    with _mutation_lock(view_root, f"{view_name}.lock"):
        yield


@contextmanager
def artifact_lease_lock(view_root: Path, view_name: str) -> Iterator[None]:
    """Block artifact lease creation while a view tree is replaced."""
    if VIEW_PATTERN.fullmatch(view_name) is None:
        raise ConfigurationError(f"Invalid Studio view name {view_name!r}")
    with _mutation_lock(view_root, f"{view_name}.artifacts.lock"):
        yield


@contextmanager
def view_build_lock(view_root: Path, view_name: str) -> Iterator[None]:
    """Serialize builds with removal while authored files stay writable."""
    if VIEW_PATTERN.fullmatch(view_name) is None:
        raise ConfigurationError(f"Invalid Studio view name {view_name!r}")
    with _mutation_lock(view_root, f"{view_name}.build.lock"):
        yield


@contextmanager
def view_removal_lock(view_root: Path, view_name: str) -> Generator[None, None, None]:
    """Acquire removal ownership while leaving the catalog available during builds."""
    if VIEW_PATTERN.fullmatch(view_name) is None:
        raise ConfigurationError(f"Invalid Studio view name {view_name!r}")
    while True:
        with (
            workspace_catalog_lock(view_root),
            _mutation_lock(
                view_root, f"{view_name}.build.lock", blocking=False
            ) as acquired,
        ):
            if acquired:
                with view_mutation_lock(view_root, view_name):
                    yield
                return
        # Wait for the build owner before retrying the ordered transaction.
        with view_build_lock(view_root, view_name):
            pass
