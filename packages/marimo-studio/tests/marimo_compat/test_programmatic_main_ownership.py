from __future__ import annotations

import sys
from collections.abc import Iterator
from threading import Event, Thread
from types import ModuleType

import pytest
from marimo._runtime import patches as marimo_patches
from marimo._server.session_manager import SessionManager

from marimo_studio._compat.server.programmatic import _MainModuleOwnership
from marimo_studio._processes.supervisor import ProcessCleanupError
from marimo_studio.errors import ProtocolError
from marimo_studio.errors._internal import CompatibilityError


@pytest.fixture(autouse=True)
def _restore_process_globals() -> Iterator[None]:
    host_main = sys.modules["__main__"]
    native_patch = marimo_patches.patch_sys_module
    native_close_session = SessionManager.close_session
    yield
    sys.modules["__main__"] = host_main
    marimo_patches.patch_sys_module = native_patch
    SessionManager.close_session = native_close_session


def test_main_publication_is_atomic_with_final_owner_release(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ownership = _MainModuleOwnership()
    host_main = sys.modules["__main__"]
    notebook = "/tmp/atomic-publication.py"
    native_patch = marimo_patches.patch_sys_module
    published = Event()
    release_publication = Event()
    close_attempted = Event()
    errors: list[BaseException] = []

    def blocked_native_patch(module: ModuleType) -> None:
        native_patch(module)
        published.set()
        release_publication.wait()

    monkeypatch.setattr(marimo_patches, "patch_sys_module", blocked_native_patch)
    owner = ownership.open(frozenset((notebook,)))
    kernel_main = ModuleType("__main__")
    kernel_main.__file__ = notebook
    publisher = Thread(target=marimo_patches.patch_sys_module, args=(kernel_main,))

    def close_owner() -> None:
        close_attempted.set()
        try:
            ownership.close(owner, (publisher,))
        except BaseException as error:
            errors.append(error)

    closer = Thread(target=close_owner)
    try:
        publisher.start()
        assert published.wait(1)
        closer.start()
        assert close_attempted.wait(1)
        closer.join(timeout=0.25)
        assert closer.is_alive()

        release_publication.set()
        publisher.join(timeout=1)
        closer.join(timeout=1)
        terminal = ownership.defer(owner, (publisher,))
        assert terminal.wait(1)

        assert not publisher.is_alive()
        assert not closer.is_alive()
        assert errors == []
        assert sys.modules["__main__"] is host_main
        assert marimo_patches.patch_sys_module is blocked_native_patch
    finally:
        release_publication.set()
        if publisher.ident is not None:
            publisher.join(timeout=1)
        if closer.ident is not None:
            closer.join(timeout=1)
        sys.modules["__main__"] = host_main
        ownership.close(owner, (publisher,))


def test_failed_patch_restoration_is_retried_by_the_next_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ownership = _MainModuleOwnership()
    host_main = sys.modules["__main__"]
    notebook_paths = frozenset(("/tmp/retry-patch.py",))
    native_patch = marimo_patches.patch_sys_module
    owner = ownership.open(notebook_paths)
    owned_patch = marimo_patches.patch_sys_module

    def foreign_patch(module: ModuleType) -> None:
        native_patch(module)

    monkeypatch.setattr(marimo_patches, "patch_sys_module", foreign_patch)
    with pytest.raises(CompatibilityError, match="before Studio could restore"):
        ownership.close(owner)
    assert marimo_patches.patch_sys_module is foreign_patch

    monkeypatch.setattr(marimo_patches, "patch_sys_module", owned_patch)
    next_owner = ownership.open(notebook_paths)
    assert sys.modules["__main__"] is host_main
    ownership.close(next_owner)
    assert marimo_patches.patch_sys_module is native_patch


def test_overlapping_open_rolls_back_the_session_patch_user(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ownership = _MainModuleOwnership()
    notebook_paths = frozenset(("/tmp/open-rollback.py",))
    native_patch = marimo_patches.patch_sys_module
    native_close_session = SessionManager.close_session
    owner = ownership.open(notebook_paths)
    owned_patch = marimo_patches.patch_sys_module
    owned_close_session = SessionManager.close_session

    def foreign_patch(_module: ModuleType) -> None:
        return

    monkeypatch.setattr(marimo_patches, "patch_sys_module", foreign_patch)
    with pytest.raises(CompatibilityError, match="while Studio was using"):
        ownership.open(notebook_paths)
    assert SessionManager.close_session is owned_close_session

    monkeypatch.setattr(marimo_patches, "patch_sys_module", owned_patch)
    ownership.close(owner)
    assert marimo_patches.patch_sys_module is native_patch
    assert SessionManager.close_session is native_close_session


def test_cached_patch_cannot_publish_after_final_owner_release() -> None:
    ownership = _MainModuleOwnership()
    host_main = sys.modules["__main__"]
    notebook = "/tmp/stale-publication.py"
    owner = ownership.open(frozenset((notebook,)))
    cached_patch = marimo_patches.patch_sys_module

    ownership.close(owner)
    stale_main = ModuleType("__main__")
    stale_main.__file__ = notebook
    cached_patch(stale_main)

    assert sys.modules["__main__"] is host_main


def test_final_owner_accepts_a_module_cleared_by_owned_kernel_teardown() -> None:
    ownership = _MainModuleOwnership()
    host_main = sys.modules["__main__"]
    notebook = "/tmp/owned-notebook.py"
    native_patch = marimo_patches.patch_sys_module
    owner = ownership.open(frozenset((notebook,)))
    cleared = ModuleType("__main__")
    cleared.__dict__["__file__"] = notebook
    published = Event()

    def publish() -> None:
        marimo_patches.patch_sys_module(cleared)
        published.set()

    kernel_thread = Thread(target=publish)
    try:
        kernel_thread.start()
        assert published.wait(1)
        kernel_thread.join(timeout=1)
        assert not kernel_thread.is_alive()
        cleared.__dict__.clear()

        ownership.close(owner, (kernel_thread,))

        assert sys.modules["__main__"] is host_main
        assert marimo_patches.patch_sys_module is native_patch
    finally:
        sys.modules["__main__"] = host_main


def test_final_owner_rejects_an_unclaimed_same_path_main_module() -> None:
    ownership = _MainModuleOwnership()
    host_main = sys.modules["__main__"]
    notebook = "/tmp/owned-notebook.py"
    native_patch = marimo_patches.patch_sys_module
    owner = ownership.open(frozenset((notebook,)))
    foreign = ModuleType("__main__")
    foreign.__dict__["__file__"] = notebook
    marimo_patches.patch_sys_module(foreign)
    foreign.__dict__.clear()

    try:
        with pytest.raises(ProtocolError, match="Another runtime replaced"):
            ownership.close(owner)
        assert sys.modules["__main__"] is foreign
        assert marimo_patches.patch_sys_module is native_patch
    finally:
        sys.modules["__main__"] = host_main


def test_pending_owner_restores_after_an_overlapping_owner_closes() -> None:
    ownership = _MainModuleOwnership()
    host_main = sys.modules["__main__"]
    notebook = "/tmp/pending-notebook.py"
    native_patch = marimo_patches.patch_sys_module
    pending_owner = ownership.open(frozenset((notebook,)))
    overlapping_owner = ownership.open(frozenset((notebook,)))
    owned_patch = marimo_patches.patch_sys_module
    kernel_main = ModuleType("__main__")
    kernel_main.__dict__["__file__"] = notebook
    release = Event()
    published = Event()

    def finish_kernel() -> None:
        marimo_patches.patch_sys_module(kernel_main)
        published.set()
        release.wait()
        kernel_main.__dict__.clear()

    thread = Thread(target=finish_kernel, daemon=True)
    thread.start()
    assert published.wait(1)
    try:
        terminal = ownership.defer(pending_owner, (thread,))
        ownership.close(overlapping_owner)
        assert marimo_patches.patch_sys_module is owned_patch

        with pytest.raises(ProcessCleanupError, match="still shutting down"):
            ownership.open(frozenset((notebook,)))

        release.set()
        assert terminal.wait(timeout=1)
        thread.join(timeout=1)
        assert not thread.is_alive()
        assert sys.modules["__main__"] is host_main
        assert marimo_patches.patch_sys_module is native_patch
        next_owner = ownership.open(frozenset((notebook,)))
        ownership.close(next_owner)
    finally:
        release.set()
        thread.join(timeout=1)
        sys.modules["__main__"] = host_main


def test_deferred_patch_conflict_recovers_before_the_next_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ownership = _MainModuleOwnership()
    host_main = sys.modules["__main__"]
    notebook = "/tmp/deferred-patch-retry.py"
    notebook_paths = frozenset((notebook,))
    native_patch = marimo_patches.patch_sys_module
    owner = ownership.open(notebook_paths)
    owned_patch = marimo_patches.patch_sys_module
    kernel_main = ModuleType("__main__")
    kernel_main.__file__ = notebook
    release = Event()
    published = Event()

    def run_kernel() -> None:
        marimo_patches.patch_sys_module(kernel_main)
        published.set()
        release.wait()
        kernel_main.__dict__.clear()

    kernel_thread = Thread(target=run_kernel, daemon=True)
    kernel_thread.start()
    assert published.wait(1)
    terminal = ownership.defer(owner, (kernel_thread,))

    def foreign_patch(_module: ModuleType) -> None:
        return

    monkeypatch.setattr(marimo_patches, "patch_sys_module", foreign_patch)
    release.set()
    assert terminal.wait(1)
    kernel_thread.join(timeout=1)
    assert not kernel_thread.is_alive()
    assert marimo_patches.patch_sys_module is foreign_patch

    monkeypatch.setattr(marimo_patches, "patch_sys_module", owned_patch)
    next_owner = ownership.open(notebook_paths)
    assert sys.modules["__main__"] is host_main
    ownership.close(next_owner)
    assert marimo_patches.patch_sys_module is native_patch


def test_committed_deferred_conflict_does_not_poison_the_next_owner() -> None:
    ownership = _MainModuleOwnership()
    notebook = "/tmp/deferred-foreign-main.py"
    notebook_paths = frozenset((notebook,))
    native_patch = marimo_patches.patch_sys_module
    owner = ownership.open(notebook_paths)
    foreign_main = ModuleType("__main__")
    foreign_main.__file__ = notebook
    marimo_patches.patch_sys_module(foreign_main)
    release = Event()
    kernel_thread = Thread(target=release.wait, daemon=True)
    kernel_thread.start()

    terminal = ownership.defer(owner, (kernel_thread,))
    release.set()
    assert terminal.wait(1)
    kernel_thread.join(timeout=1)
    assert not kernel_thread.is_alive()
    assert sys.modules["__main__"] is foreign_main
    assert marimo_patches.patch_sys_module is native_patch

    next_owner = ownership.open(notebook_paths)
    ownership.close(next_owner)
    assert sys.modules["__main__"] is foreign_main
    assert marimo_patches.patch_sys_module is native_patch


def test_reaper_start_failure_releases_main_ownership(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ownership = _MainModuleOwnership()
    host_main = sys.modules["__main__"]
    notebook = "/tmp/reaper-start-failure.py"
    native_patch = marimo_patches.patch_sys_module
    owner = ownership.open(frozenset((notebook,)))
    kernel_main = ModuleType("__main__")
    kernel_main.__dict__["__file__"] = notebook
    release = Event()
    published = Event()

    def run_kernel() -> None:
        marimo_patches.patch_sys_module(kernel_main)
        published.set()
        release.wait()

    kernel_thread = Thread(target=run_kernel, daemon=True)
    kernel_thread.start()
    assert published.wait(1)
    native_start = Thread.start

    def start(thread: Thread) -> None:
        if thread.name == "marimo-studio-programmatic-kernel-reaper":
            raise RuntimeError("reaper thread unavailable")
        native_start(thread)

    monkeypatch.setattr(Thread, "start", start)
    try:
        with pytest.raises(RuntimeError, match="reaper thread unavailable"):
            ownership.defer(owner, (kernel_thread,))
        assert sys.modules["__main__"] is host_main
        assert marimo_patches.patch_sys_module is native_patch

        release.set()
        kernel_thread.join(timeout=1)
        assert not kernel_thread.is_alive()
        next_owner = ownership.open(frozenset((notebook,)))
        ownership.close(next_owner)
        assert marimo_patches.patch_sys_module is native_patch
    finally:
        release.set()
        kernel_thread.join(timeout=1)
        sys.modules["__main__"] = host_main


def test_failed_reaper_cleanup_waits_for_the_retained_kernel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ownership = _MainModuleOwnership()
    host_main = sys.modules["__main__"]
    notebook = "/tmp/reaper-cleanup-retry.py"
    notebook_paths = frozenset((notebook,))
    native_patch = marimo_patches.patch_sys_module
    owner = ownership.open(notebook_paths)
    owned_patch = marimo_patches.patch_sys_module
    kernel_main = ModuleType("__main__")
    kernel_main.__file__ = notebook
    release = Event()
    published = Event()

    def run_kernel() -> None:
        marimo_patches.patch_sys_module(kernel_main)
        published.set()
        release.wait()

    kernel_thread = Thread(target=run_kernel, daemon=True)
    kernel_thread.start()
    assert published.wait(1)
    native_start = Thread.start

    def start(thread: Thread) -> None:
        if thread.name == "marimo-studio-programmatic-kernel-reaper":
            raise RuntimeError("reaper thread unavailable")
        native_start(thread)

    def foreign_patch(_module: ModuleType) -> None:
        return

    try:
        monkeypatch.setattr(Thread, "start", start)
        monkeypatch.setattr(marimo_patches, "patch_sys_module", foreign_patch)
        with pytest.raises(RuntimeError, match="reaper thread unavailable"):
            ownership.defer(owner, (kernel_thread,))

        monkeypatch.setattr(marimo_patches, "patch_sys_module", owned_patch)
        with pytest.raises(ProcessCleanupError, match="still shutting down"):
            ownership.open(notebook_paths)
        assert marimo_patches.patch_sys_module is owned_patch

        release.set()
        kernel_thread.join(timeout=1)
        assert not kernel_thread.is_alive()
        next_owner = ownership.open(notebook_paths)
        ownership.close(next_owner)
        assert marimo_patches.patch_sys_module is native_patch
    finally:
        release.set()
        kernel_thread.join(timeout=1)
        sys.modules["__main__"] = host_main
