from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from typing import Any, cast

import pytest

from marimo_studio._processes.cancellation import current_provider_cancellation
from marimo_studio._processes.supervisor import ProcessCleanupError
from marimo_studio._server.development.coordinator import DevelopmentCoordinator
from marimo_studio._server.development.ports import FileChangeCallback, ProjectWatchPlan
from marimo_studio._server.development.publication_registry import (
    PublicationRegistry,
    _Baseline,
    _Publication,
    _PublicationAdmission,
)
from marimo_studio._server.development.source_ownership import _SourceCreation
from marimo_studio.view_providers import ProviderCancellation

from ..app_helpers import configured


@pytest.mark.parametrize("owner", ("publication", "baseline"))
@pytest.mark.parametrize("replaced", (False, True))
def test_last_waiter_observes_completed_cleanup_failure(
    owner: str,
    replaced: bool,
) -> None:
    async def exercise() -> None:
        lock = asyncio.Lock()
        registry = PublicationRegistry(lock, lambda _view: None)
        release = asyncio.get_running_loop().create_future()

        async def fail() -> None:
            raise ProcessCleanupError("completed provider process survived")

        task = asyncio.create_task(fail())
        await asyncio.gather(task, return_exceptions=True)
        control = ProviderCancellation()
        key = ("dashboard", 1)
        if owner == "publication":
            publication = _Publication(
                control,
                task,
                _PublicationAdmission(foreground=True),
                waiters=1,
                waiter_releases={release},
            )
            if not replaced:
                registry._publications[(*key, "development")] = publication
            with pytest.raises(
                ProcessCleanupError,
                match="completed provider process survived",
            ):
                await registry._release_publication_waiter(
                    (*key, "development"),
                    publication,
                    release,
                )
            assert publication.waiters == 0
            assert not publication.waiter_releases
        else:
            baseline = _Baseline(
                control,
                task,
                waiters=1,
                waiter_releases={release},
            )
            if not replaced:
                registry._baselines[key] = baseline
            with pytest.raises(
                ProcessCleanupError,
                match="completed provider process survived",
            ):
                await registry._release_baseline_waiter(key, baseline, release)
            assert baseline.waiters == 0
            assert not baseline.waiter_releases

    asyncio.run(exercise())


@pytest.mark.parametrize("replaced", (False, True))
def test_last_source_creation_waiter_observes_completed_cleanup_failure(
    replaced: bool,
) -> None:
    async def exercise() -> None:
        coordinator = DevelopmentCoordinator()

        async def fail() -> None:
            raise ProcessCleanupError("completed source process survived")

        task = asyncio.create_task(fail())
        await asyncio.gather(task, return_exceptions=True)
        creation = _SourceCreation(
            ProviderCancellation(),
            cast(Any, task),
            waiters=1,
        )
        if not replaced:
            coordinator._source_monitors._creations["dashboard"] = creation

        with pytest.raises(
            ProcessCleanupError,
            match="completed source process survived",
        ):
            await coordinator._release_creation_waiter("dashboard", creation)
        assert creation.waiters == 0
        await coordinator.close()

    asyncio.run(exercise())


@pytest.mark.parametrize("boundary", ("deletion", "close"))
def test_release_waits_for_publish_cleanup_not_long_lived_caller(
    boundary: str,
) -> None:
    started = threading.Event()
    cancelled = threading.Event()

    def operation() -> str:
        control = current_provider_cancellation()
        assert control is not None
        unregister = control.register(cancelled.set)
        started.set()
        try:
            assert cancelled.wait(timeout=2)
            return "cancelled"
        finally:
            unregister()

    async def exercise() -> None:
        coordinator = DevelopmentCoordinator()
        published = asyncio.Event()

        async def producer() -> None:
            await coordinator.publish("dashboard", 1, operation)
            published.set()
            await asyncio.Future()

        caller = asyncio.create_task(producer())
        assert await asyncio.to_thread(started.wait, 1)
        try:
            if boundary == "deletion":

                async def delete() -> None:
                    async with coordinator.deleting_view("dashboard"):
                        pass

                await asyncio.wait_for(delete(), timeout=1)
            else:
                await asyncio.wait_for(coordinator.close(), timeout=1)
            assert published.is_set()
            assert not caller.done()
        finally:
            caller.cancel()
            await asyncio.gather(caller, return_exceptions=True)
            await coordinator.close()

    asyncio.run(exercise())


def test_close_attempts_every_release_after_one_watcher_fails(
    notebook_path: Path,
) -> None:
    studio = configured(notebook_path)
    watchers: list[Watcher] = []

    class Watcher:
        def __init__(self, failing: bool) -> None:
            self.failing = failing
            self.closed = False

        async def replace(
            self,
            plan: ProjectWatchPlan,
            callback: FileChangeCallback,
        ) -> None:
            del plan, callback
            return

        async def close(self) -> None:
            self.closed = True
            if self.failing:
                raise OSError("first watcher failed")

    def watcher_factory() -> Watcher:
        watcher = Watcher(failing=not watchers)
        watchers.append(watcher)
        return watcher

    publication_started = threading.Event()
    publication_cancelled = threading.Event()
    baseline_started = threading.Event()
    baseline_cancelled = threading.Event()

    def blocking_operation(
        started: threading.Event,
        cancelled: threading.Event,
    ) -> str:
        control = current_provider_cancellation()
        assert control is not None
        unregister = control.register(cancelled.set)
        started.set()
        try:
            assert cancelled.wait(timeout=2)
            return "cancelled"
        finally:
            unregister()

    async def exercise() -> tuple[BaseException | None, tuple[bool, ...], bool]:
        coordinator = DevelopmentCoordinator(
            project_watcher=watcher_factory,
            interval=60,
        )
        subscriptions = (
            await coordinator.subscribe(studio, None),
            await coordinator.subscribe(studio, "dashboard"),
        )
        monitors = tuple(coordinator._source_monitors._monitors.values())
        monitor_tasks = tuple(
            task
            for monitor in monitors
            for task in (monitor.task, monitor.scan_task)
            if task is not None
        )
        publication = asyncio.create_task(
            coordinator.publish(
                "dashboard",
                1,
                lambda: blocking_operation(
                    publication_started,
                    publication_cancelled,
                ),
            )
        )
        baseline = asyncio.create_task(
            coordinator.baseline(
                "dashboard",
                1,
                lambda: blocking_operation(baseline_started, baseline_cancelled),
            )
        )
        assert await asyncio.to_thread(publication_started.wait, 1)
        assert await asyncio.to_thread(baseline_started.wait, 1)

        cleanup_error: BaseException | None = None
        try:
            await coordinator.close()
        except BaseException as error:
            cleanup_error = error

        state = (
            cleanup_error,
            tuple(watcher.closed for watcher in watchers),
            all(task.done() for task in (*monitor_tasks, publication, baseline)),
        )
        try:
            return state
        finally:
            publication_cancelled.set()
            baseline_cancelled.set()
            for task in (*monitor_tasks, publication, baseline):
                task.cancel()
            await asyncio.gather(
                *monitor_tasks,
                publication,
                baseline,
                return_exceptions=True,
            )
            for subscription in subscriptions:
                await subscription.close()

    cleanup_error, closed, all_tasks_done = asyncio.run(exercise())

    assert cleanup_error is not None
    assert "first watcher failed" in str(cleanup_error)
    assert closed == (True, True)
    assert publication_cancelled.is_set()
    assert baseline_cancelled.is_set()
    assert all_tasks_done


def test_repeated_cancellation_finishes_close_state_commit(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    studio = configured(notebook_path)

    class Watcher:
        def __init__(self) -> None:
            self.closed = False

        async def replace(
            self,
            plan: ProjectWatchPlan,
            callback: FileChangeCallback,
        ) -> None:
            del plan, callback

        async def close(self) -> None:
            self.closed = True

    watcher = Watcher()

    async def exercise() -> None:
        coordinator = DevelopmentCoordinator(project_watcher=lambda: watcher)
        subscription = await coordinator.subscribe(studio, "dashboard")
        finish_entered = asyncio.Event()
        release_finish = asyncio.Event()
        finish_close = coordinator._finish_close

        async def gated_finish(errors: tuple[Exception, ...]) -> None:
            finish_entered.set()
            await release_finish.wait()
            await finish_close(errors)

        monkeypatch.setattr(coordinator, "_finish_close", gated_finish)
        async with coordinator._lock:
            coordinator._deleting_views.add("stale-view")
        closing = asyncio.create_task(coordinator.close())
        await finish_entered.wait()

        await coordinator._lock.acquire()
        try:
            release_finish.set()
            await asyncio.sleep(0)
            closing.cancel()
            await asyncio.sleep(0)
            still_finishing = not closing.done()
            closing.cancel()
            await asyncio.sleep(0)
        finally:
            coordinator._lock.release()

        with pytest.raises(asyncio.CancelledError):
            await closing
        assert still_finishing
        assert watcher.closed
        assert not coordinator._source_monitors._monitors
        assert not coordinator._source_monitors._creations
        assert not coordinator._publications._publications
        assert not coordinator._publications._baselines
        assert not coordinator._deleting_views
        await coordinator.close()
        await subscription.close()

    asyncio.run(exercise())
