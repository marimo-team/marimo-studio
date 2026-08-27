from __future__ import annotations

import sys
from threading import Event, Thread
from types import ModuleType

import pytest

from marimo_studio._compat.server.programmatic import _MainModuleOwnership
from marimo_studio._processes.supervisor import ProcessCleanupError
from marimo_studio.errors import ProtocolError


def test_final_owner_accepts_a_module_cleared_by_owned_kernel_teardown() -> None:
    ownership = _MainModuleOwnership()
    host_main = sys.modules["__main__"]
    owner = ownership.open()
    cleared = ModuleType("__main__")
    notebook = "/tmp/owned-notebook.py"
    cleared.__dict__["__file__"] = notebook
    try:
        sys.modules["__main__"] = cleared
        ownership.observe_kernel_module(frozenset((notebook,)))
        cleared.__dict__.clear()

        ownership.close(owner)

        assert sys.modules["__main__"] is host_main
    finally:
        sys.modules["__main__"] = host_main


def test_final_owner_rejects_an_unrecorded_empty_main_module() -> None:
    ownership = _MainModuleOwnership()
    host_main = sys.modules["__main__"]
    owner = ownership.open()
    foreign = ModuleType("__main__")
    foreign.__dict__.clear()
    sys.modules["__main__"] = foreign

    try:
        with pytest.raises(ProtocolError, match="Another runtime replaced"):
            ownership.close(owner)
        assert sys.modules["__main__"] is foreign
    finally:
        sys.modules["__main__"] = host_main


def test_pending_owner_restores_after_an_overlapping_owner_closes() -> None:
    ownership = _MainModuleOwnership()
    host_main = sys.modules["__main__"]
    pending_owner = ownership.open()
    overlapping_owner = ownership.open()
    notebook = "/tmp/pending-notebook.py"
    kernel_main = ModuleType("__main__")
    kernel_main.__dict__["__file__"] = notebook
    sys.modules["__main__"] = kernel_main
    ownership.observe_kernel_module(frozenset((notebook,)))
    release = Event()

    def finish_kernel() -> None:
        release.wait()
        kernel_main.__dict__.clear()

    thread = Thread(target=finish_kernel, daemon=True)
    thread.start()
    try:
        terminal = ownership.defer(pending_owner, (thread,))
        ownership.close(overlapping_owner)

        with pytest.raises(ProcessCleanupError, match="still shutting down"):
            ownership.open()

        release.set()
        assert terminal.wait(timeout=1)
        thread.join(timeout=1)
        assert not thread.is_alive()
        assert sys.modules["__main__"] is host_main
        next_owner = ownership.open()
        ownership.close(next_owner)
    finally:
        release.set()
        thread.join(timeout=1)
        sys.modules["__main__"] = host_main


def test_reaper_start_failure_reaps_after_the_kernel_thread_stops(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ownership = _MainModuleOwnership()
    host_main = sys.modules["__main__"]
    owner = ownership.open()
    notebook = "/tmp/reaper-start-failure.py"
    kernel_main = ModuleType("__main__")
    kernel_main.__dict__["__file__"] = notebook
    sys.modules["__main__"] = kernel_main
    ownership.observe_kernel_module(frozenset((notebook,)))
    release = Event()
    kernel_thread = Thread(target=release.wait, daemon=True)
    kernel_thread.start()
    native_start = Thread.start

    def start(thread: Thread) -> None:
        if thread.name == "marimo-studio-programmatic-kernel-reaper":
            raise RuntimeError("reaper thread unavailable")
        native_start(thread)

    monkeypatch.setattr(Thread, "start", start)
    try:
        with pytest.raises(RuntimeError, match="reaper thread unavailable"):
            ownership.defer(owner, (kernel_thread,))
        with pytest.raises(ProcessCleanupError, match="still shutting down"):
            ownership.open()

        release.set()
        kernel_thread.join(timeout=1)
        assert not kernel_thread.is_alive()
        next_owner = ownership.open()
        assert sys.modules["__main__"] is host_main
        ownership.close(next_owner)
    finally:
        release.set()
        kernel_thread.join(timeout=1)
        sys.modules["__main__"] = host_main
