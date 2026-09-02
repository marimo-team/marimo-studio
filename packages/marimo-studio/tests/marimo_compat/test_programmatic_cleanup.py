from __future__ import annotations

import multiprocessing
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from threading import Event, Thread
from threading import enumerate as enumerate_threads
from types import ModuleType
from typing import Any, cast
from urllib.parse import urlsplit

import pytest
from marimo._runtime import patches as marimo_patches
from marimo._server.session_manager import SessionManager
from starlette.testclient import TestClient

import marimo_studio._compat.server.programmatic as programmatic_module
from marimo_studio import create_asgi_app
from marimo_studio._processes.supervisor import ProcessCleanupError

from ..app_helpers import published_dashboard, session_manager


def _spawned_value(value: str) -> str:
    return value


def _start_kernel(client: TestClient, manager: Any) -> Thread:
    config = client.get("/_marimo-studio/views/dashboard/config").json()
    root = urlsplit(config["runtime"]["data"]["url"])
    websocket_url = (
        f"{root.path.rstrip('/')}/ws?session_id={config['presentationSessionId']}"
    )
    with client.websocket_connect(websocket_url):
        session = next(iter(manager.sessions.values()))
        task = cast(Any, session)._kernel_manager.kernel_task
        assert isinstance(task, Thread)
        return task


@pytest.mark.native_process
def test_late_kernel_publication_restores_the_host_main_module(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    host_main = sys.modules["__main__"]
    native_patch = marimo_patches.patch_sys_module
    app = create_asgi_app(published_dashboard(notebook_path).notebook)
    manager = session_manager(app)
    native_shutdown = manager.shutdown
    publisher_waiting = Event()
    allow_publish = Event()
    kernel_thread: Thread | None = None

    def delayed_patch(module: ModuleType) -> None:
        publisher_waiting.set()
        if not allow_publish.wait(5):
            raise RuntimeError("Kernel module publication was not released")
        native_patch(module)

    def shutdown_manager() -> None:
        allow_publish.set()
        native_shutdown()

    monkeypatch.setattr(marimo_patches, "patch_sys_module", delayed_patch)
    monkeypatch.setattr(manager, "shutdown", shutdown_manager)
    try:
        with TestClient(app) as client:
            kernel_thread = _start_kernel(client, manager)
            assert publisher_waiting.wait(5)
    finally:
        allow_publish.set()

    assert kernel_thread is not None
    assert not kernel_thread.is_alive()
    assert sys.modules["__main__"] is host_main
    assert marimo_patches.patch_sys_module is delayed_patch


@pytest.mark.native_process
def test_closed_session_kernel_remains_owned_until_lifespan_exit(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    host_main = sys.modules["__main__"]
    native_patch = marimo_patches.patch_sys_module
    native_close_session = SessionManager.close_session
    native_join = programmatic_module._join_kernel_threads
    settled_threads: set[Thread] = set()

    def join_kernel_threads(threads: tuple[Thread, ...]) -> None:
        settled_threads.update(threads)
        native_join(threads)

    app = create_asgi_app(published_dashboard(notebook_path).notebook)
    manager = session_manager(app)
    monkeypatch.setattr(
        programmatic_module,
        "_join_kernel_threads",
        join_kernel_threads,
    )

    with TestClient(app) as client:
        kernel_thread = _start_kernel(client, manager)
        session_id = next(iter(manager.sessions))
        assert manager.close_session(session_id)
        assert manager.sessions == {}

    kernel_thread.join(timeout=5)
    deadline = time.monotonic() + 5
    while (
        sys.modules["__main__"] is not host_main
        or marimo_patches.patch_sys_module is not native_patch
    ) and time.monotonic() < deadline:
        time.sleep(0.01)

    assert not kernel_thread.is_alive()
    assert kernel_thread in settled_threads
    assert sys.modules["__main__"] is host_main
    assert marimo_patches.patch_sys_module is native_patch
    assert SessionManager.close_session is native_close_session
    context = multiprocessing.get_context("spawn")
    with ProcessPoolExecutor(max_workers=1, mp_context=context) as executor:
        assert executor.submit(_spawned_value, "ready").result(timeout=5) == "ready"


@pytest.mark.native_process
def test_deferred_kernel_exit_restores_main_without_another_lifespan(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    host_main = sys.modules["__main__"]
    kernel_main = ModuleType("__main__")
    kernel_main.__file__ = str(notebook_path)
    ownership = programmatic_module._MainModuleOwnership()
    notebook_paths = frozenset({str(notebook_path)})
    native_patch = marimo_patches.patch_sys_module
    token = ownership.open(notebook_paths)
    owned_patch = marimo_patches.patch_sys_module
    release = Event()
    published = Event()

    def run_kernel() -> None:
        marimo_patches.patch_sys_module(kernel_main)
        published.set()
        release.wait()

    kernel_thread = Thread(target=run_kernel, daemon=True)
    kernel_thread.start()
    assert published.wait(1)
    monkeypatch.setattr(programmatic_module, "_KERNEL_JOIN_TIMEOUT", 0.01)

    try:
        existing_reapers = {
            id(thread)
            for thread in enumerate_threads()
            if thread.name == "marimo-studio-programmatic-kernel-reaper"
        }
        with pytest.raises(ProcessCleanupError, match="did not stop"):
            programmatic_module._join_kernel_threads((kernel_thread,))
        terminal = ownership.defer(token, (kernel_thread,))
        assert marimo_patches.patch_sys_module is owned_patch
        reapers = [
            thread
            for thread in enumerate_threads()
            if thread.name == "marimo-studio-programmatic-kernel-reaper"
            and id(thread) not in existing_reapers
        ]
        assert len(reapers) == 1
        with pytest.raises(ProcessCleanupError, match="still shutting down"):
            ownership.open(notebook_paths)

        release.set()
        assert terminal.wait(1)
        assert not kernel_thread.is_alive()
        for reaper in reapers:
            reaper.join(timeout=1)
        assert all(not reaper.is_alive() for reaper in reapers)
        assert sys.modules["__main__"] is host_main
        assert marimo_patches.patch_sys_module is native_patch

        next_token = ownership.open(notebook_paths)
        ownership.close(next_token)
        assert marimo_patches.patch_sys_module is native_patch
        context = multiprocessing.get_context("spawn")
        with ProcessPoolExecutor(max_workers=1, mp_context=context) as executor:
            assert executor.submit(_spawned_value, "ready").result(timeout=5) == (
                "ready"
            )
    finally:
        release.set()
        kernel_thread.join(timeout=1)
        sys.modules["__main__"] = host_main
