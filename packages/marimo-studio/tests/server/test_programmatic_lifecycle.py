from __future__ import annotations

import asyncio
import multiprocessing
import sys
from collections.abc import Callable, MutableMapping
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from threading import Thread
from types import ModuleType
from typing import Any, cast
from urllib.parse import urlsplit

import marimo
import pytest
from starlette.testclient import TestClient

from marimo_studio import create_asgi_app
from marimo_studio._composition import (
    _PrivateAdapterLifecycle,
    own_programmatic_lifespans,
    programmatic_middleware,
)
from marimo_studio._server.ports import CloseHandle
from marimo_studio.errors import ProtocolError

from ..app_helpers import published_dashboard, session_manager
from ..helpers import notebook_source

pytestmark = pytest.mark.native_process


class _TrackedClose:
    def __init__(
        self,
        handle: CloseHandle,
        closed: list[int],
        owner: int,
    ) -> None:
        self._handle = handle
        self._closed = closed
        self._owner = owner

    def close(self) -> None:
        self._handle.close()
        self._closed.append(self._owner)


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


def test_programmatic_apps_own_each_notebook_lifespan(
    notebook_path: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = published_dashboard(notebook_path)
    second_notebook = tmp_path / "second.py"
    second_notebook.write_text(
        notebook_source(tmp_path / "second-executed"),
        encoding="utf-8",
    )
    second = published_dashboard(second_notebook)
    opened: list[int] = []
    closed: list[int] = []
    native_open: Callable[[_PrivateAdapterLifecycle], CloseHandle] = (
        _PrivateAdapterLifecycle.open
    )

    def open_lifecycle(lifecycle: _PrivateAdapterLifecycle) -> CloseHandle:
        owner = id(lifecycle)
        opened.append(owner)
        return _TrackedClose(native_open(lifecycle), closed, owner)

    monkeypatch.setattr(_PrivateAdapterLifecycle, "open", open_lifecycle)
    first_app = create_asgi_app(first.notebook)
    second_app = create_asgi_app(second.notebook)
    first_manager = session_manager(first_app)
    second_manager = session_manager(second_app)
    shutdown: list[object] = []
    first_shutdown = first_manager.shutdown
    second_shutdown = second_manager.shutdown

    def shutdown_first() -> None:
        shutdown.append(first_manager)
        first_shutdown()

    def shutdown_second() -> None:
        shutdown.append(second_manager)
        second_shutdown()

    monkeypatch.setattr(first_manager, "shutdown", shutdown_first)
    monkeypatch.setattr(second_manager, "shutdown", shutdown_second)

    with TestClient(first_app) as first_client:
        assert len(opened) == 1
        assert first_client.get("/").status_code == 200
        assert len(opened) == 1
        with TestClient(second_app) as second_client:
            assert len(opened) == 2
            assert len(set(opened)) == 2
            assert second_client.get("/").status_code == 200
            assert closed == []
        assert closed == [opened[1]]
        assert shutdown == [second_manager]
        assert first_client.get("/").status_code == 200

    assert closed == [opened[1], opened[0]]
    assert shutdown == [second_manager, first_manager]


def test_programmatic_lifespan_cancellation_drains_owned_resources(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    studio = published_dashboard(notebook_path)
    opened = 0
    closed = 0
    native_open: Callable[[_PrivateAdapterLifecycle], CloseHandle] = (
        _PrivateAdapterLifecycle.open
    )

    def open_lifecycle(lifecycle: _PrivateAdapterLifecycle) -> CloseHandle:
        nonlocal opened
        opened += 1
        handle = native_open(lifecycle)

        class Close:
            def close(self) -> None:
                nonlocal closed
                handle.close()
                closed += 1

        return Close()

    monkeypatch.setattr(_PrivateAdapterLifecycle, "open", open_lifecycle)
    app = create_asgi_app(studio.notebook)
    manager = session_manager(app)
    shutdown = 0
    native_shutdown = manager.shutdown

    def shutdown_manager() -> None:
        nonlocal shutdown
        shutdown += 1
        native_shutdown()

    monkeypatch.setattr(manager, "shutdown", shutdown_manager)

    async def cancel_lifespan() -> list[str]:
        startup = True
        sent: list[str] = []
        baseline = asyncio.all_tasks()

        async def receive() -> dict[str, str]:
            nonlocal startup
            if startup:
                startup = False
                return {"type": "lifespan.startup"}
            raise asyncio.CancelledError

        async def send(message: MutableMapping[str, Any]) -> None:
            sent.append(str(message["type"]))

        with pytest.raises(asyncio.CancelledError):
            await app(
                {
                    "type": "lifespan",
                    "asgi": {"version": "3.0", "spec_version": "2.0"},
                    "state": {},
                },
                receive,
                send,
            )
        leaked = [task for task in asyncio.all_tasks() - baseline if not task.done()]
        assert leaked == []
        return sent

    sent = asyncio.run(cancel_lifespan())

    assert sent == ["lifespan.startup.complete", "lifespan.shutdown.failed"]
    assert opened == 1
    assert closed == 1
    assert shutdown == 1


def test_programmatic_startup_failure_closes_siblings_and_session_managers(
    notebook_path: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = published_dashboard(notebook_path)
    second_notebook = tmp_path / "second.py"
    second_notebook.write_text(
        notebook_source(tmp_path / "second-executed"),
        encoding="utf-8",
    )
    second = published_dashboard(second_notebook)
    opened: list[int] = []
    closed: list[int] = []
    native_open: Callable[[_PrivateAdapterLifecycle], CloseHandle] = (
        _PrivateAdapterLifecycle.open
    )

    def open_lifecycle(lifecycle: _PrivateAdapterLifecycle) -> CloseHandle:
        owner = id(lifecycle)
        opened.append(owner)
        if len(opened) == 2:
            raise RuntimeError("adapter startup failed")
        return _TrackedClose(native_open(lifecycle), closed, owner)

    monkeypatch.setattr(_PrivateAdapterLifecycle, "open", open_lifecycle)
    app = (
        marimo.create_asgi_app(quiet=True, skew_protection=True)
        .with_app(
            path="/first",
            root=str(first.notebook),
            middleware=[programmatic_middleware(first.notebook)],
        )
        .with_app(
            path="/second",
            root=str(second.notebook),
            middleware=[programmatic_middleware(second.notebook)],
        )
        .build()
    )
    managers = [
        route.app.state.session_manager
        for route in cast(Any, app).routes
        if hasattr(getattr(route, "app", None), "state")
    ]
    shutdown: list[object] = []
    for manager in managers:
        native_shutdown = manager.shutdown

        def shutdown_manager(
            manager: object = manager,
            native_shutdown: Callable[[], None] = native_shutdown,
        ) -> None:
            shutdown.append(manager)
            native_shutdown()

        monkeypatch.setattr(manager, "shutdown", shutdown_manager)
    owned = own_programmatic_lifespans(app)

    with (
        pytest.raises(RuntimeError, match="adapter startup failed"),
        TestClient(owned),
    ):
        pass

    assert len(opened) == 2
    assert closed == [opened[0]]
    assert len(managers) == 2
    assert set(shutdown) == set(managers)


@pytest.mark.parametrize("retry_fails", (False, True))
def test_programmatic_shutdown_retries_and_preserves_the_first_failure(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    retry_fails: bool,
) -> None:
    studio = published_dashboard(notebook_path)
    app = create_asgi_app(studio.notebook)
    manager = session_manager(app)
    native_shutdown = manager.shutdown
    first_failure = RuntimeError("first shutdown failed")
    retry_failure = RuntimeError("retry shutdown failed")
    attempts = 0

    def shutdown_manager() -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise first_failure
        if retry_fails:
            raise retry_failure
        native_shutdown()

    monkeypatch.setattr(manager, "shutdown", shutdown_manager)

    with (
        pytest.raises(RuntimeError, match="first shutdown failed") as raised,
        TestClient(app),
    ):
        pass

    assert raised.value is first_failure
    assert raised.value.__cause__ is (retry_failure if retry_fails else None)
    assert attempts == 2


def test_programmatic_shutdown_settles_native_kernels_before_return(
    notebook_path: Path,
) -> None:
    host_main = sys.modules["__main__"]
    studio = published_dashboard(notebook_path)
    app = create_asgi_app(studio.notebook)
    manager = session_manager(app)
    kernel_thread: Thread | None = None

    with TestClient(app) as client:
        kernel_thread = _start_kernel(client, manager)

    assert manager.sessions == {}
    assert kernel_thread is not None
    assert not kernel_thread.is_alive()
    assert sys.modules["__main__"] is host_main
    assert hasattr(host_main, "__spec__")

    context = multiprocessing.get_context("spawn")
    with ProcessPoolExecutor(max_workers=1, mp_context=context) as executor:
        assert executor.submit(_spawned_value, "ready").result(timeout=5) == "ready"


def test_programmatic_shutdown_preserves_a_foreign_main_module(
    notebook_path: Path,
) -> None:
    host_main = sys.modules["__main__"]
    app = create_asgi_app(published_dashboard(notebook_path).notebook)
    client = TestClient(app)
    client.__enter__()
    foreign = ModuleType("foreign_main")
    foreign.__dict__["owner"] = "foreign-runtime"
    sys.modules["__main__"] = foreign
    try:
        with pytest.raises(ProtocolError, match="Another runtime replaced"):
            client.__exit__(None, None, None)
        assert sys.modules["__main__"] is foreign
    finally:
        sys.modules["__main__"] = host_main


def test_startup_failure_remains_primary_when_main_restoration_conflicts(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    host_main = sys.modules["__main__"]
    foreign = ModuleType("foreign_main")
    foreign.__dict__["owner"] = "foreign-runtime"
    app = create_asgi_app(published_dashboard(notebook_path).notebook)

    def fail_start(_lifecycle: _PrivateAdapterLifecycle) -> CloseHandle:
        sys.modules["__main__"] = foreign
        raise RuntimeError("adapter startup failed")

    monkeypatch.setattr(_PrivateAdapterLifecycle, "open", fail_start)
    try:
        with (
            pytest.raises(RuntimeError, match="adapter startup failed") as raised,
            TestClient(app),
        ):
            pass
        assert isinstance(raised.value.__cause__, ProtocolError)
        assert sys.modules["__main__"] is foreign
    finally:
        sys.modules["__main__"] = host_main


@pytest.mark.parametrize("first_to_close", (0, 1))
def test_overlapping_programmatic_apps_restore_main_after_the_final_kernel(
    notebook_path: Path,
    tmp_path: Path,
    first_to_close: int,
) -> None:
    host_main = sys.modules["__main__"]
    other_notebook = tmp_path / "other.py"
    other_notebook.write_text(
        notebook_source(tmp_path / "other-executed"),
        encoding="utf-8",
    )
    apps = (
        create_asgi_app(published_dashboard(notebook_path).notebook),
        create_asgi_app(published_dashboard(other_notebook).notebook),
    )
    managers = tuple(session_manager(app) for app in apps)
    clients = tuple(TestClient(app) for app in apps)
    opened = [False, False]

    try:
        for index, client in enumerate(clients):
            client.__enter__()
            opened[index] = True
        threads = tuple(
            _start_kernel(client, manager)
            for client, manager in zip(clients, managers, strict=True)
        )

        clients[first_to_close].__exit__(None, None, None)
        opened[first_to_close] = False
        survivor = 1 - first_to_close
        assert not threads[first_to_close].is_alive()
        assert threads[survivor].is_alive()
        assert sys.modules["__main__"] is not host_main

        clients[survivor].__exit__(None, None, None)
        opened[survivor] = False
        assert not threads[survivor].is_alive()
        assert sys.modules["__main__"] is host_main
    finally:
        for index, client in reversed(tuple(enumerate(clients))):
            if opened[index]:
                client.__exit__(None, None, None)


def test_zero_kernel_app_cannot_restore_main_while_an_owned_kernel_runs(
    notebook_path: Path,
    tmp_path: Path,
) -> None:
    host_main = sys.modules["__main__"]
    idle_notebook = tmp_path / "idle.py"
    idle_notebook.write_text(
        notebook_source(tmp_path / "idle-executed"),
        encoding="utf-8",
    )
    kernel_app = create_asgi_app(published_dashboard(notebook_path).notebook)
    idle_app = create_asgi_app(published_dashboard(idle_notebook).notebook)
    kernel_manager = session_manager(kernel_app)
    kernel_client = TestClient(kernel_app)
    idle_client = TestClient(idle_app)
    kernel_open = False
    idle_open = False

    try:
        kernel_client.__enter__()
        kernel_open = True
        idle_client.__enter__()
        idle_open = True
        kernel_thread = _start_kernel(kernel_client, kernel_manager)

        idle_client.__exit__(None, None, None)
        idle_open = False
        assert kernel_thread.is_alive()
        assert sys.modules["__main__"] is not host_main

        kernel_client.__exit__(None, None, None)
        kernel_open = False
        assert not kernel_thread.is_alive()
        assert sys.modules["__main__"] is host_main
    finally:
        if idle_open:
            idle_client.__exit__(None, None, None)
        if kernel_open:
            kernel_client.__exit__(None, None, None)
