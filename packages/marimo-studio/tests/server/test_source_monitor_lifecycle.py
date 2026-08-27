from __future__ import annotations

import asyncio
import threading
from collections.abc import Awaitable, Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from marimo_studio._processes.cancellation import current_provider_cancellation
from marimo_studio._processes.supervisor import ProcessCleanupError
from marimo_studio._server.development import coordinator as development
from marimo_studio._server.development.coordinator import DevelopmentCoordinator
from marimo_studio._server.development.ports import ProjectWatchPlan
from marimo_studio._server.development.source_changes import SourceChange
from marimo_studio.errors import ConfigurationError

from ..app_helpers import configured
from ..source_change_test_support import next_source


class MemoryWatcher:
    def __init__(self) -> None:
        self.plan = ProjectWatchPlan((), ())
        self.callback: Callable[[Path], Awaitable[None]] | None = None
        self.closed = False
        self.replacements = 0

    async def replace(
        self,
        plan: ProjectWatchPlan,
        callback: Callable[[Path], Awaitable[None]],
    ) -> None:
        self.replacements += 1
        self.closed = False
        self.plan = plan
        self.callback = callback

    async def change(self, path: Path) -> None:
        assert self.callback is not None
        await self.callback(path)

    async def close(self) -> None:
        self.closed = True


class WatcherFactory:
    def __init__(self) -> None:
        self.created: list[MemoryWatcher] = []

    def __call__(self) -> MemoryWatcher:
        watcher = MemoryWatcher()
        self.created.append(watcher)
        return watcher


class GatedWatcher(MemoryWatcher):
    def __init__(self, *, gate_replace: bool = False, gate_close: bool = False) -> None:
        super().__init__()
        self.gate_replace = gate_replace
        self.gate_close = gate_close
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def replace(
        self,
        plan: ProjectWatchPlan,
        callback: Callable[[Path], Awaitable[None]],
    ) -> None:
        if self.gate_replace:
            self.entered.set()
            await self.release.wait()
        await super().replace(plan, callback)

    async def close(self) -> None:
        if self.gate_close:
            self.entered.set()
            await self.release.wait()
        await super().close()


def test_watcher_replacement_wait_does_not_hold_the_coordinator_lock(
    notebook_path: Path,
) -> None:
    studio = configured(notebook_path)

    async def exercise() -> None:
        watcher = GatedWatcher(gate_replace=True)
        coordinator = DevelopmentCoordinator(project_watcher=lambda: watcher)
        subscribing = asyncio.create_task(coordinator.subscribe(studio, "dashboard"))
        await watcher.entered.wait()
        lookup = asyncio.create_task(coordinator.retained_provider("dashboard"))
        try:
            assert await asyncio.wait_for(lookup, timeout=1) == "marimo-studio/vanilla"
        finally:
            watcher.release.set()
            subscription = await subscribing
            await subscription.close()
            await coordinator.close()

    asyncio.run(exercise())


def test_watcher_close_wait_does_not_hold_the_coordinator_lock(
    notebook_path: Path,
) -> None:
    studio = configured(notebook_path)

    async def exercise() -> None:
        watcher = GatedWatcher(gate_close=True)
        coordinator = DevelopmentCoordinator(project_watcher=lambda: watcher)
        subscription = await coordinator.subscribe(studio, "dashboard")
        closing = asyncio.create_task(subscription.close())
        await watcher.entered.wait()
        lookup = asyncio.create_task(coordinator.retained_provider("dashboard"))
        try:
            assert await asyncio.wait_for(lookup, timeout=1) == "marimo-studio/vanilla"
        finally:
            watcher.release.set()
            await closing
            await coordinator.close()

    asyncio.run(exercise())


def test_idle_refresh_does_not_reopen_the_final_subscribers_watcher(
    notebook_path: Path,
) -> None:
    studio = configured(notebook_path)
    watcher = MemoryWatcher()

    async def exercise() -> None:
        coordinator = DevelopmentCoordinator(project_watcher=lambda: watcher)
        subscription = await coordinator.subscribe(studio, "dashboard")
        await subscription.close()

        assert watcher.closed
        assert watcher.replacements == 1
        await coordinator.refresh("dashboard")
        assert watcher.closed
        assert watcher.replacements == 1
        await coordinator.close()

    asyncio.run(exercise())


def test_direct_refresh_retries_against_the_retained_monitor() -> None:
    async def exercise() -> None:
        coordinator = DevelopmentCoordinator()
        first = object()
        retained = SimpleNamespace(generation=0)
        monitors = cast(dict[str, object], coordinator._source_monitors._monitors)
        monitors["dashboard"] = first
        entered = asyncio.Event()
        release = asyncio.Event()
        scanned: list[object] = []

        async def scan(_view: str, monitor: object) -> None:
            scanned.append(monitor)
            if monitor is first:
                entered.set()
                await release.wait()
                return
            retained.generation += 1

        cast(Any, coordinator)._scan_monitor = scan
        refreshing = asyncio.create_task(coordinator.refresh("dashboard"))
        await entered.wait()
        async with coordinator._lock:
            monitors["dashboard"] = retained
        release.set()
        await refreshing

        assert scanned == [first, retained]
        assert retained.generation == 1

    asyncio.run(exercise())


def test_repeated_cancellation_releases_a_creation_waiter_blocked_on_the_lock(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    studio = configured(notebook_path)

    async def exercise() -> None:
        coordinator = DevelopmentCoordinator()
        construct_started = asyncio.Event()
        construct_finished = asyncio.Event()
        release_construct = asyncio.Event()
        release_entered = asyncio.Event()
        release_waiter = coordinator._release_creation_waiter

        async def gated_construct(*_args: Any) -> Any:
            construct_started.set()
            try:
                await release_construct.wait()
                return development.SourceChangeProducer(studio, "dashboard")
            finally:
                construct_finished.set()

        async def gated_release(*args: Any) -> None:
            release_entered.set()
            await release_waiter(*args)

        monkeypatch.setattr(coordinator, "_construct_source", gated_construct)
        monkeypatch.setattr(coordinator, "_release_creation_waiter", gated_release)
        waiting = asyncio.create_task(coordinator.subscribe(studio, "dashboard"))
        await construct_started.wait()
        creation = coordinator._source_monitors._creations["dashboard"]

        await coordinator._lock.acquire()
        try:
            waiting.cancel()
            await release_entered.wait()
            waiting.cancel()
            await asyncio.sleep(0)
            still_releasing = not waiting.done()
            waiting.cancel()
            await asyncio.sleep(0)
        finally:
            coordinator._lock.release()

        try:
            with pytest.raises(asyncio.CancelledError):
                await waiting
            assert still_releasing
            assert construct_finished.is_set()
            assert creation.waiters == 0
            assert creation.task.done()
            assert not coordinator._source_monitors._creations
            assert not coordinator._source_monitors._monitors
        finally:
            release_construct.set()
            await coordinator.close()

    asyncio.run(exercise())


def test_repeated_cancellation_releases_a_completed_creation_before_claim(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    studio = configured(notebook_path)
    producer = development.SourceChangeProducer(studio, "dashboard")

    async def exercise() -> None:
        coordinator = DevelopmentCoordinator()
        construct_started = asyncio.Event()
        release_construct = asyncio.Event()
        claim_entered = asyncio.Event()
        release_entered = asyncio.Event()
        claim_creation = coordinator._claim_source_creation
        release_waiter = coordinator._release_creation_waiter

        async def gated_construct(*_args: Any) -> Any:
            construct_started.set()
            await release_construct.wait()
            return producer

        async def gated_claim(*args: Any) -> Any:
            claim_entered.set()
            return await claim_creation(*args)

        async def gated_release(*args: Any) -> None:
            release_entered.set()
            await release_waiter(*args)

        monkeypatch.setattr(coordinator, "_construct_source", gated_construct)
        monkeypatch.setattr(coordinator, "_claim_source_creation", gated_claim)
        monkeypatch.setattr(coordinator, "_release_creation_waiter", gated_release)
        waiting = asyncio.create_task(coordinator.subscribe(studio, "dashboard"))
        await construct_started.wait()
        creation = coordinator._source_monitors._creations["dashboard"]

        await coordinator._lock.acquire()
        try:
            release_construct.set()
            await asyncio.wait_for(asyncio.shield(creation.task), timeout=1)
            await claim_entered.wait()
            waiting.cancel()
            await asyncio.wait_for(release_entered.wait(), timeout=1)
            waiting.cancel()
            await asyncio.sleep(0)
            still_releasing = not waiting.done()
            waiting.cancel()
            await asyncio.sleep(0)
        finally:
            coordinator._lock.release()

        try:
            with pytest.raises(asyncio.CancelledError):
                await waiting
            assert still_releasing
            assert creation.waiters == 0
            assert creation.task.done()
            assert not coordinator._source_monitors._creations
            assert not coordinator._source_monitors._monitors
        finally:
            await coordinator.close()

    asyncio.run(exercise())


def test_subscribers_share_one_generation_scan(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    studio = configured(notebook_path)
    project = studio.view("dashboard")
    inspection = development.SourceChangeProducer(studio, "dashboard").catalog()[1]
    polls = 0

    class Producer:
        def __init__(self, selected: Any, _view: Any) -> None:
            self.studio = selected
            self.watch_plan = ProjectWatchPlan(
                (project.root / "index.html",),
                (),
            )

        def poll(self) -> SourceChange:
            nonlocal polls
            polls += 1
            return SourceChange("project", ())

        def catalog(self) -> tuple[Any, Any, str]:
            return project, inspection, "sha256:input"

    monkeypatch.setattr(development, "SourceChangeProducer", Producer)
    watchers = WatcherFactory()

    async def exercise() -> None:
        coordinator = DevelopmentCoordinator(project_watcher=watchers)
        first = await coordinator.subscribe(studio, "dashboard")
        second = await coordinator.subscribe(studio, "dashboard")
        try:
            await watchers.created[0].change(project.root / "index.html")
            first_event, second_event = await asyncio.gather(
                next_source(first),
                next_source(second),
            )
            assert first_event == second_event
        finally:
            await first.close()
            await second.close()
            assert watchers.created[0].closed
            await coordinator.close()

    asyncio.run(exercise())
    assert polls == 1
    assert watchers.created[0].closed


def test_concurrent_subscribers_share_one_monitor_activation(
    notebook_path: Path,
) -> None:
    studio = configured(notebook_path)
    watcher = GatedWatcher(gate_replace=True)

    async def exercise() -> None:
        coordinator = DevelopmentCoordinator(project_watcher=lambda: watcher)
        first = asyncio.create_task(coordinator.subscribe(studio, "dashboard"))
        await watcher.entered.wait()
        second_started = asyncio.Event()

        async def subscribe_second() -> Any:
            second_started.set()
            return await coordinator.subscribe(studio, "dashboard")

        second = asyncio.create_task(subscribe_second())
        try:
            await asyncio.wait_for(second_started.wait(), timeout=1)
            async with coordinator._lock:
                monitor = coordinator._source_monitors._monitors["dashboard"]
                assert len(monitor.subscribers) == 2
        finally:
            watcher.release.set()
        subscriptions = await asyncio.gather(first, second)
        try:
            assert watcher.replacements == 1
            assert not watcher.closed
        finally:
            await asyncio.gather(*(item.close() for item in subscriptions))
            await coordinator.close()

    asyncio.run(exercise())


def test_subscription_recovers_a_missed_file_event(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    studio = configured(notebook_path)
    project = studio.view("dashboard")
    watchers = WatcherFactory()
    monkeypatch.setattr(development, "_CATALOG_PROBE_INTERVAL", 0)

    async def exercise() -> None:
        coordinator = DevelopmentCoordinator(project_watcher=watchers)
        subscription = await coordinator.subscribe(studio, "dashboard")
        try:
            source = project.root / "index.html"
            source.write_text(
                source.read_text(encoding="utf-8") + "\n",
                encoding="utf-8",
            )

            event = await next_source(subscription)

            assert event.change.kind == "project"
        finally:
            await subscription.close()
            await coordinator.close()

    asyncio.run(exercise())


def test_resubscribe_keeps_the_restarted_watcher_while_the_previous_task_stops(
    notebook_path: Path,
) -> None:
    studio = configured(notebook_path)
    watchers = WatcherFactory()

    async def exercise() -> None:
        coordinator = DevelopmentCoordinator(project_watcher=watchers)
        first = await coordinator.subscribe(studio, "dashboard")
        stopping = asyncio.Event()
        release = asyncio.Event()
        monitor = coordinator._source_monitors._monitors["dashboard"]
        assert monitor.task is not None
        monitor.task.cancel()
        await asyncio.gather(monitor.task, return_exceptions=True)

        async def delayed_stop() -> None:
            started.set()
            try:
                await asyncio.Future()
            except asyncio.CancelledError:
                stopping.set()
                await release.wait()

        started = asyncio.Event()
        monitor.task = asyncio.create_task(delayed_stop())
        await asyncio.wait_for(started.wait(), timeout=1)
        closing = asyncio.create_task(first.close())
        await stopping.wait()
        second = await coordinator.subscribe(studio, "dashboard")
        release.set()
        await closing
        try:
            assert len(watchers.created) == 1
            assert not watchers.created[0].closed
        finally:
            await second.close()
            await coordinator.close()

    asyncio.run(exercise())


def test_resubscribe_finishes_an_idle_close_before_restarting_the_watcher(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    studio = configured(notebook_path)

    class NotificationWatcher(MemoryWatcher):
        async def change(self, path: Path) -> None:
            if self.closed:
                return
            await super().change(path)

    watcher = NotificationWatcher()

    async def exercise() -> None:
        coordinator = DevelopmentCoordinator(project_watcher=lambda: watcher)
        first = await coordinator.subscribe(studio, "dashboard")
        monitor = coordinator._source_monitors._monitors["dashboard"]
        close_started = asyncio.Event()
        release_close = asyncio.Event()
        start_entered = asyncio.Event()
        release_start = asyncio.Event()
        original_close = monitor.watcher.close
        original_start = coordinator._start_monitor

        async def gated_close() -> None:
            close_started.set()
            await release_close.wait()
            await original_close()

        async def gated_start(key: str | None, selected: Any) -> bool:
            start_entered.set()
            await release_start.wait()
            return await original_start(key, selected)

        monkeypatch.setattr(monitor.watcher, "close", gated_close)
        monkeypatch.setattr(coordinator, "_start_monitor", gated_start)

        closing = asyncio.create_task(first.close())
        await close_started.wait()
        subscribing = asyncio.create_task(coordinator.subscribe(studio, "dashboard"))
        await start_entered.wait()
        release_start.set()
        asyncio.get_running_loop().call_soon(release_close.set)
        await closing
        second = await subscribing
        try:
            assert not watcher.closed
            source = studio.view("dashboard").root / "index.html"
            source.write_text(
                source.read_text(encoding="utf-8") + "\n",
                encoding="utf-8",
            )
            await watcher.change(source)
            event = await next_source(second)
            assert event.change.kind == "project"
        finally:
            await second.close()
            await coordinator.close()

    asyncio.run(exercise())


def test_rolled_back_deletion_keeps_an_idle_monitor_stopped(
    notebook_path: Path,
) -> None:
    studio = configured(notebook_path)
    watchers = WatcherFactory()

    async def exercise() -> None:
        coordinator = DevelopmentCoordinator(project_watcher=watchers)
        subscription = await coordinator.subscribe(studio, "dashboard")
        await subscription.close()
        monitor = coordinator._source_monitors._monitors["dashboard"]
        assert not monitor.subscribers
        assert monitor.task is None

        with pytest.raises(RuntimeError, match="rollback"):
            async with coordinator.deleting_view("dashboard"):
                raise RuntimeError("rollback")

        assert monitor.task is None
        assert watchers.created[0].closed
        await coordinator.close()

    asyncio.run(exercise())


def test_repeated_cancellation_finishes_view_deletion_state_commit(
    notebook_path: Path,
) -> None:
    studio = configured(notebook_path)
    watchers = WatcherFactory()

    async def exercise() -> None:
        coordinator = DevelopmentCoordinator(project_watcher=watchers)
        subscription = await coordinator.subscribe(studio, "dashboard")
        monitor = coordinator._source_monitors._monitors["dashboard"]
        deletion_entered = asyncio.Event()
        release_deletion = asyncio.Event()

        async def remove() -> None:
            async with coordinator.deleting_view("dashboard"):
                deletion_entered.set()
                await release_deletion.wait()

        deleting = asyncio.create_task(remove())
        await deletion_entered.wait()
        await coordinator._lock.acquire()
        try:
            release_deletion.set()
            await asyncio.sleep(0)
            deleting.cancel()
            await asyncio.sleep(0)
            still_finishing = not deleting.done()
            deleting.cancel()
            await asyncio.sleep(0)
        finally:
            coordinator._lock.release()

        try:
            with pytest.raises(asyncio.CancelledError):
                await deleting
            assert still_finishing
            assert "dashboard" not in coordinator._deleting_views
            assert "dashboard" not in coordinator._source_monitors._monitors
            assert monitor.task is None
            assert watchers.created[0].closed

            replacement = await coordinator.subscribe(studio, "dashboard")
            try:
                source = studio.view("dashboard").root / "index.html"
                source.write_text(
                    source.read_text(encoding="utf-8") + "\n",
                    encoding="utf-8",
                )
                await watchers.created[1].change(source)
                event = await next_source(replacement)
                assert event.change.kind == "project"
            finally:
                await replacement.close()
        finally:
            release_deletion.set()
            await subscription.close()
            await coordinator.close()

    asyncio.run(exercise())


def test_scan_failure_blocks_stale_catalog_until_the_next_generation(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    studio = configured(notebook_path)
    project = studio.view("dashboard")
    inspection = development.SourceChangeProducer(studio, "dashboard").catalog()[1]
    failure = True

    class Producer:
        def __init__(self, selected: Any, _view: Any) -> None:
            self.studio = selected
            self.watch_plan = ProjectWatchPlan(
                (project.root / "index.html",),
                (),
            )

        def poll(self) -> SourceChange:
            if failure:
                raise OSError("source root is unavailable")
            return SourceChange("project", ())

        def catalog(self) -> tuple[Any, Any, str]:
            return project, inspection, "sha256:input"

    monkeypatch.setattr(development, "SourceChangeProducer", Producer)
    watchers = WatcherFactory()

    async def exercise() -> None:
        nonlocal failure
        coordinator = DevelopmentCoordinator(project_watcher=watchers)
        subscription = await coordinator.subscribe(studio, "dashboard")
        try:
            await watchers.created[0].change(project.root / "index.html")
            failed = await next_source(subscription)
            assert failed.change.error == "source root is unavailable"
            with pytest.raises(ConfigurationError, match="source root is unavailable"):
                await coordinator.project_catalog(studio, "dashboard")

            failure = False
            await watchers.created[0].change(project.root / "index.html")
            recovered = await next_source(subscription)
            assert recovered.change.error is None
            catalog = await coordinator.project_catalog(studio, "dashboard")
            assert catalog.input_id == "sha256:input"
        finally:
            await subscription.close()
            await coordinator.close()

    asyncio.run(exercise())


def test_cancelled_source_scan_propagates_provider_cleanup_failure(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    studio = configured(notebook_path)
    started = threading.Event()
    cancelled = threading.Event()

    def poll() -> SourceChange | None:
        control = current_provider_cancellation()
        assert control is not None
        unregister = control.register(cancelled.set)
        started.set()
        try:
            assert cancelled.wait(timeout=2)
            raise ProcessCleanupError("source scan provider survived")
        finally:
            unregister()

    async def exercise() -> None:
        coordinator = DevelopmentCoordinator()
        subscription = await coordinator.subscribe(studio, "dashboard")
        monitor = coordinator._source_monitors._monitors["dashboard"]
        monkeypatch.setattr(monitor.producer, "poll", poll)
        scanning = asyncio.create_task(coordinator._scan_monitor("dashboard", monitor))
        try:
            assert await asyncio.to_thread(started.wait, 1)
            scanning.cancel()
            with pytest.raises(
                ProcessCleanupError,
                match="source scan provider survived",
            ):
                await scanning
            assert cancelled.is_set()
            assert monitor.scan_control is None
            assert monitor.scan_task is None
            assert not monitor.journal
        finally:
            await subscription.close()
            await coordinator.close()

    asyncio.run(exercise())


def test_watcher_replacement_failure_reports_once_and_recovers(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    studio = configured(notebook_path)

    class FlakyWatcher(MemoryWatcher):
        attempts = 0

        async def replace(
            self,
            plan: ProjectWatchPlan,
            callback: Callable[[Path], Awaitable[None]],
        ) -> None:
            self.attempts += 1
            if self.attempts == 2:
                raise OSError("watch replacement failed")
            await super().replace(plan, callback)

    watcher = FlakyWatcher()
    monkeypatch.setattr(development, "_CATALOG_PROBE_INTERVAL", 0)

    async def exercise() -> None:
        coordinator = DevelopmentCoordinator(project_watcher=lambda: watcher)
        subscription = await coordinator.subscribe(studio, "dashboard")
        try:
            source = studio.view("dashboard").root / "index.html"
            source.write_text(
                source.read_text(encoding="utf-8") + "\n", encoding="utf-8"
            )
            await watcher.change(source)

            failed = await next_source(subscription)
            recovered = await next_source(subscription)

            assert failed.change.error == "watch replacement failed"
            assert recovered.change.error is None
            assert not watcher.closed
        finally:
            await subscription.close()
            await coordinator.close()

    asyncio.run(exercise())


def test_subscription_release_finishes_after_cancellation(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    studio = configured(notebook_path)
    watchers = WatcherFactory()

    async def exercise() -> None:
        coordinator = DevelopmentCoordinator(project_watcher=watchers)
        subscription = await coordinator.subscribe(studio, "dashboard")
        unsubscribe = coordinator._unsubscribe
        committed = asyncio.Event()
        release = asyncio.Event()

        async def delayed_unsubscribe(*args: Any) -> None:
            await unsubscribe(*args)
            committed.set()
            await release.wait()

        monkeypatch.setattr(coordinator, "_unsubscribe", delayed_unsubscribe)
        closing = asyncio.create_task(subscription.close())
        await committed.wait()
        closing.cancel()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await closing

        monitor = coordinator._source_monitors._monitors["dashboard"]
        assert not monitor.subscribers
        assert monitor.task is None
        assert watchers.created[0].closed
        await subscription.close()
        await coordinator.close()

    asyncio.run(exercise())
