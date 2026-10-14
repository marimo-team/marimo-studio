"""Serialize one view's cross-process filesystem mutations."""

from __future__ import annotations

import os
import stat
import threading
from collections.abc import Generator, Iterator
from contextlib import ExitStack, contextmanager
from pathlib import Path
from weakref import WeakValueDictionary

from marimo_studio._filesystem.errors import UnsafePathError
from marimo_studio._filesystem.files import FileTree
from marimo_studio._filesystem.ignore import ignore_generated_directory
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


@contextmanager
def _mutation_lock(
    view_root: Path,
    filename: str,
    *,
    blocking: bool = True,
) -> Generator[bool, None, None]:
    root = view_root.absolute()
    lock_path = root / ".locks" / filename
    # The lock tree starts at the nearest existing ancestor of the view root,
    # because opening the ancestors above it would need read permission on
    # folders a notebook reaches with search permission alone. lstat needs
    # only search permission, so it refuses a link swapped in above that root.
    boundary = root.parent
    while not boundary.is_dir() and boundary != boundary.parent:
        boundary = boundary.parent
    for ancestor in (*reversed(boundary.parents), boundary):
        if stat.S_ISLNK(ancestor.lstat().st_mode):
            raise UnsafePathError(f"Path is a symlink: {ancestor}")
    tree = FileTree(boundary)
    thread_lock = _thread_lock(lock_path)
    if not thread_lock.acquire(blocking=blocking):
        yield False
        return
    try:
        held = _held_paths()
        if lock_path in held:
            yield True
            return
        with ExitStack() as owner:
            try:
                # A lock file removed or replaced while held no longer
                # excluded other processes from this mutation.
                acquired = owner.enter_context(
                    tree.lock(lock_path, blocking=blocking, require_held=True)
                )
            except ConfigurationError:
                raise
            except OSError as error:
                raise ConfigurationError(
                    f"Could not open view mutation lock: {lock_path}"
                ) from error
            if not acquired:
                yield False
                return
            # Lock files stay in the authored catalog, where every process
            # that changes it finds them, so the directory ignores itself.
            ignore_generated_directory(tree, lock_path.parent)
            held.add(lock_path)
            try:
                yield True
            finally:
                held.discard(lock_path)
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
def view_build_lock(
    view_root: Path, view_name: str, *, blocking: bool = True
) -> Iterator[bool]:
    """Serialize builds with removal and rename while authored files stay writable.

    Yields ``False`` when ``blocking`` is false and a build holds the lock.
    """
    if VIEW_PATTERN.fullmatch(view_name) is None:
        raise ConfigurationError(f"Invalid Studio view name {view_name!r}")
    with _mutation_lock(
        view_root, f"{view_name}.build.lock", blocking=blocking
    ) as acquired:
        yield acquired


@contextmanager
def view_retirement_lock(
    view_root: Path, view_name: str
) -> Generator[None, None, None]:
    """Own a view name for removal or rename after its in-flight build ends."""
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
