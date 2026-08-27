"""Protect provider cancellation and supervised command execution."""

from __future__ import annotations

import asyncio
import sys
import threading
from collections.abc import Awaitable
from dataclasses import replace
from importlib.metadata import EntryPoint
from pathlib import Path
from typing import Any

import pytest

import marimo_studio._processes.provider_runner as provider_runner_module
import marimo_studio._views.build as build_module
import marimo_studio._views.inspection as inspection_module
from marimo_studio._processes.cancellation import current_provider_cancellation
from marimo_studio._processes.provider_operation import run_provider_operation
from marimo_studio._processes.provider_runner import (
    ProviderCommandError,
    create_provider_runner,
)
from marimo_studio._processes.supervisor import ProcessCleanupError, ProcessResult
from marimo_studio._server.development.coordinator import (
    DevelopmentCleanupError,
    DevelopmentCoordinator,
)
from marimo_studio._server.development.task_ownership import run_owned_worker
from marimo_studio._views.inspection import inspection_request
from marimo_studio.errors import ViewProjectError
from marimo_studio.view_providers import ProviderCancellation, ViewProject
from marimo_studio.view_providers._host.registry import (
    ProviderCandidate,
    ProviderRegistry,
)

from ..provider_test_support import inspection, provider_build_request


def _raise_cleanup_after_cancellation(started: threading.Event) -> None:
    control = current_provider_cancellation()
    assert control is not None
    cancelled = threading.Event()
    unregister = control.register(cancelled.set)
    started.set()
    try:
        assert cancelled.wait(timeout=2)
        try:
            raise ProcessCleanupError("provider process tree survived")
        except ProcessCleanupError as cleanup:
            raise RuntimeError("provider operation failed") from cleanup
    finally:
        unregister()


async def _cancel_after_start(
    operation: Awaitable[Any],
    started: threading.Event,
) -> None:
    task = asyncio.ensure_future(operation)
    assert await asyncio.to_thread(started.wait, 1)
    task.cancel()
    with pytest.raises(ProcessCleanupError, match="process tree survived"):
        await task


def test_provider_cancellation_keeps_the_event_loop_live_and_isolates_callbacks() -> (
    None
):
    async def exercise() -> None:
        cancellation = ProviderCancellation()
        release = threading.Event()
        current = threading.Event()
        late = threading.Event()

        def blocking() -> None:
            release.wait(timeout=2)

        def failing() -> None:
            raise RuntimeError("provider cleanup failed")

        cancellation.register(blocking)
        cancellation.register(failing)
        cancellation.register(current.set)
        heartbeat = asyncio.create_task(asyncio.sleep(0))
        started = asyncio.get_running_loop().time()
        cancellation.cancel()
        await asyncio.wait_for(heartbeat, timeout=0.1)
        assert asyncio.get_running_loop().time() - started < 0.1
        assert await asyncio.to_thread(current.wait, 1)

        cancellation.register(late.set)
        assert await asyncio.to_thread(late.wait, 1)
        release.set()

    asyncio.run(exercise())


@pytest.mark.parametrize("operation", ("inspect", "build"))
def test_cancelled_provider_process_finishes_when_extension_ignores_cancellation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    monkeypatch.setenv("PYTHONPATH", str(Path(__file__).parents[2]))
    point = EntryPoint(
        name="ignoring",
        value=("tests.providers.test_process_isolation:ignoring_cancellation_provider"),
        group="marimo_studio.view_provider",
    )
    registry = ProviderRegistry(
        (
            ProviderCandidate(
                registration="ignoring",
                distribution="test-isolated",
                version="1.0.0",
                entry_point=point,
            ),
        ),
        isolate_operations=True,
    )
    installed = registry.get("test-isolated/ignoring")
    root = tmp_path / "view"
    root.mkdir()
    root.joinpath("view.toml").write_text("schema = 1\n", encoding="utf-8")
    root.joinpath("index.html").write_text("<main></main>", encoding="utf-8")
    marker = tmp_path / f"{operation}-entered"
    project = ViewProject(
        "dashboard",
        root,
        root / "view.toml",
        installed.key,
        {"marker": str(marker)},
    )
    cancellation = ProviderCancellation()
    if operation == "inspect":
        selected_inspection = inspection_request(
            project,
            cancellation=cancellation,
            command_timeout=1,
        )

        def invoke() -> object:
            return installed.inspect(selected_inspection)

    else:
        staging = tmp_path / "staging"
        staging.mkdir()
        cache = tmp_path / "live" / ".artifacts" / ".cache"
        selected_build = provider_build_request(
            project,
            inspection(),
            staging,
            cache_root=cache,
            command_timeout=1,
        )
        selected_build = replace(
            selected_build,
            cancellation=cancellation,
            runner=create_provider_runner(project, cancellation, 1),
        )

        def invoke() -> object:
            return installed.build(selected_build)

    async def exercise() -> None:
        pending = asyncio.create_task(asyncio.to_thread(invoke))

        async def wait_until_entered() -> None:
            while not marker.exists() and not pending.done():
                await asyncio.sleep(0.01)
            if pending.done():
                await pending

        await asyncio.wait_for(wait_until_entered(), timeout=2)
        heartbeat = asyncio.create_task(asyncio.sleep(0))
        cancellation.cancel()
        await asyncio.wait_for(heartbeat, timeout=0.1)
        with pytest.raises(ViewProjectError, match="cancelled"):
            await asyncio.wait_for(pending, timeout=3)

    asyncio.run(exercise())


def test_provider_runner_executes_a_bounded_project_command(
    tmp_path: Path,
) -> None:
    project = ViewProject(
        "dashboard",
        tmp_path,
        tmp_path / "view.toml",
        "example/html",
        {},
    )
    cancellation = ProviderCancellation()
    runner = create_provider_runner(project, cancellation)

    completed = runner.run(
        [sys.executable, "-c", "print('built')"],
        cwd=tmp_path,
    )

    assert completed.returncode == 0
    assert completed.stdout.splitlines() == ["built"]


@pytest.mark.parametrize(
    "timeout",
    (
        pytest.param(True, id="boolean"),
        pytest.param(0, id="non-positive"),
        pytest.param(float("nan"), id="non-finite"),
        pytest.param("1", id="non-numeric"),
    ),
)
def test_provider_runner_requires_a_finite_positive_command_timeout(
    tmp_path: Path,
    timeout: Any,
) -> None:
    project = ViewProject(
        "dashboard",
        tmp_path,
        tmp_path / "view.toml",
        "example/html",
        {},
    )

    with pytest.raises(ProviderCommandError, match="finite positive number"):
        create_provider_runner(
            project,
            ProviderCancellation(),
            command_timeout=timeout,
        )


def test_provider_runner_charges_only_supervised_command_time(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = ViewProject(
        "dashboard",
        tmp_path,
        tmp_path / "view.toml",
        "example/html",
        {},
    )
    timeouts: list[float] = []
    times = iter((0.0, 20.0, 70.0, 90.0))

    class Supervisor:
        def run(
            self,
            _command: list[str],
            timeout: float,
            **_kwargs: Any,
        ) -> ProcessResult:
            timeouts.append(timeout)
            return ProcessResult(0, b"", b"")

        def cancel(self) -> None:
            return

    monkeypatch.setattr(provider_runner_module, "monotonic", lambda: next(times))
    monkeypatch.setattr(provider_runner_module, "ProcessSupervisor", Supervisor)
    runner = create_provider_runner(
        project,
        ProviderCancellation(),
        command_timeout=120,
    )

    runner.run(["first"], cwd=tmp_path)
    runner.run(["second"], cwd=tmp_path)

    assert timeouts == [120, 100]


def test_provider_runner_rejects_cancelled_work(tmp_path: Path) -> None:
    project = ViewProject(
        "dashboard",
        tmp_path,
        tmp_path / "view.toml",
        "example/html",
        {},
    )
    cancellation = ProviderCancellation()
    cancellation.cancel()

    with pytest.raises(ProviderCommandError, match="cancelled"):
        create_provider_runner(project, cancellation).run(
            [sys.executable, "-c", "raise SystemExit(0)"],
            cwd=tmp_path,
        )


def test_standalone_provider_operation_surfaces_cleanup_failure() -> None:
    started = threading.Event()

    asyncio.run(
        _cancel_after_start(
            run_provider_operation(lambda: _raise_cleanup_after_cancellation(started)),
            started,
        )
    )


def test_development_worker_surfaces_cleanup_failure() -> None:
    started = threading.Event()
    cancelled = threading.Event()
    control = ProviderCancellation()
    control.register(cancelled.set)

    def operation() -> None:
        started.set()
        assert cancelled.wait(timeout=2)
        try:
            raise ProcessCleanupError("development process tree survived")
        except ProcessCleanupError as cleanup:
            raise RuntimeError("development operation failed") from cleanup

    asyncio.run(
        _cancel_after_start(
            run_owned_worker(control, operation),
            started,
        )
    )


def test_async_inspection_surfaces_cleanup_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = threading.Event()
    project = ViewProject(
        "dashboard",
        tmp_path,
        tmp_path / "view.toml",
        "example/html",
        {},
    )
    monkeypatch.setattr(
        inspection_module,
        "inspect_view_project_sync",
        lambda *_args, **_kwargs: _raise_cleanup_after_cancellation(started),
    )

    asyncio.run(
        _cancel_after_start(
            inspection_module.inspect_view_project(project),
            started,
        )
    )


def test_mount_inspection_surfaces_cleanup_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = ViewProject(
        "dashboard",
        tmp_path,
        tmp_path / "view.toml",
        "example/html",
        {},
    )

    def fail(*_args: object, **_kwargs: object) -> object:
        raise ProcessCleanupError("mount inspection process survived")

    monkeypatch.setattr(inspection_module, "inspect_view_project_sync", fail)

    with pytest.raises(
        ProcessCleanupError,
        match="mount inspection process survived",
    ):
        inspection_module.inspect_view_mounts(project)


def test_async_build_surfaces_cleanup_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = threading.Event()
    project = ViewProject(
        "dashboard",
        tmp_path,
        tmp_path / "view.toml",
        "example/html",
        {},
    )
    monkeypatch.setattr(
        build_module,
        "build_view_project_sync",
        lambda *_args, **_kwargs: _raise_cleanup_after_cancellation(started),
    )

    asyncio.run(
        _cancel_after_start(
            build_module.build_view_project(project),
            started,
        )
    )


def test_coordinator_shutdown_reports_provider_cleanup_failure() -> None:
    started = threading.Event()

    async def exercise() -> None:
        coordinator = DevelopmentCoordinator()
        publication = asyncio.create_task(
            coordinator.publish(
                "dashboard",
                1,
                lambda: _raise_cleanup_after_cancellation(started),
            )
        )
        assert await asyncio.to_thread(started.wait, 1)
        try:
            with pytest.raises(DevelopmentCleanupError) as captured:
                await coordinator.close()
            assert len(captured.value.errors) == 1
            assert isinstance(captured.value.errors[0], ProcessCleanupError)
            assert "process tree survived" in str(captured.value.errors[0])
        finally:
            await asyncio.gather(publication, return_exceptions=True)

    asyncio.run(exercise())


def test_view_deletion_reports_provider_cleanup_failure() -> None:
    started = threading.Event()

    async def exercise() -> None:
        coordinator = DevelopmentCoordinator()
        publication = asyncio.create_task(
            coordinator.publish(
                "dashboard",
                1,
                lambda: _raise_cleanup_after_cancellation(started),
            )
        )
        assert await asyncio.to_thread(started.wait, 1)
        try:
            with pytest.raises(ProcessCleanupError, match="process tree survived"):
                async with coordinator.deleting_view("dashboard"):
                    pytest.fail("Deletion continued after process cleanup failed")
        finally:
            await asyncio.gather(publication, return_exceptions=True)
            await coordinator.close()

    asyncio.run(exercise())
