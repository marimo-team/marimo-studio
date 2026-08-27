from __future__ import annotations

import multiprocessing
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from threading import Event, Thread
from threading import enumerate as enumerate_threads
from types import ModuleType

import pytest

import marimo_studio._compat.server.programmatic as programmatic_module
from marimo_studio._processes.supervisor import ProcessCleanupError


def _spawned_value(value: str) -> str:
    return value


def test_deferred_kernel_exit_restores_main_without_another_lifespan(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    host_main = sys.modules["__main__"]
    kernel_main = ModuleType("__main__")
    kernel_main.__file__ = str(notebook_path)
    ownership = programmatic_module._MainModuleOwnership()
    token = ownership.open()
    sys.modules["__main__"] = kernel_main
    ownership.observe_kernel_module(frozenset({str(notebook_path)}))
    release = Event()
    kernel_thread = Thread(target=release.wait, daemon=True)
    kernel_thread.start()
    monkeypatch.setattr(programmatic_module, "_KERNEL_JOIN_TIMEOUT", 0.01)

    try:
        with pytest.raises(ProcessCleanupError, match="did not stop"):
            programmatic_module._join_kernel_threads((kernel_thread,))
        terminal = ownership.defer(token, (kernel_thread,))
        reapers = [
            thread
            for thread in enumerate_threads()
            if thread.name == "marimo-studio-programmatic-kernel-reaper"
        ]
        assert len(reapers) == 1
        with pytest.raises(ProcessCleanupError, match="still shutting down"):
            ownership.open()

        release.set()
        assert terminal.wait(1)
        assert not kernel_thread.is_alive()
        for reaper in reapers:
            reaper.join(timeout=1)
        assert all(not reaper.is_alive() for reaper in reapers)
        assert sys.modules["__main__"] is host_main

        next_token = ownership.open()
        ownership.close(next_token)
        context = multiprocessing.get_context("spawn")
        with ProcessPoolExecutor(max_workers=1, mp_context=context) as executor:
            assert executor.submit(_spawned_value, "ready").result(timeout=5) == (
                "ready"
            )
    finally:
        release.set()
        kernel_thread.join(timeout=1)
        sys.modules["__main__"] = host_main
