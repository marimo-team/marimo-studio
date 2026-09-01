"""Protect project watcher coalescing and lifecycle."""

from __future__ import annotations

import asyncio
import os
import queue
import threading
from pathlib import Path
from typing import Any

import pytest

from marimo_studio._processes.supervisor import ProcessCleanupError
from marimo_studio._server.development import watcher as file_watcher
from marimo_studio._server.development.ports import ProjectWatchPlan

from ..async_test_support import wait_for_event


def _assert_bounded_join(timeouts: list[float | None]) -> None:
    assert timeouts
    assert all(timeout is not None and timeout > 0 for timeout in timeouts)


def test_watchdog_events_ignore_read_only_file_activity() -> None:
    assert file_watcher._watchdog_event_is_mutation("modified")
    assert file_watcher._watchdog_event_is_mutation("moved")
    assert not file_watcher._watchdog_event_is_mutation("opened")
    assert not file_watcher._watchdog_event_is_mutation("closed_no_write")


def test_native_observer_discards_retired_events_before_stop() -> None:
    class Observer:
        def __init__(self) -> None:
            self.event_queue: queue.Queue[object] = queue.Queue()
            self.alive = True
            self.stopped_with_pending_events = False

        def stop(self) -> None:
            self.stopped_with_pending_events = not self.event_queue.empty()
            self.alive = False

        def join(self, timeout: float | None = None) -> None:
            return

        def is_alive(self) -> bool:
            return self.alive

    observer = Observer()
    for event in range(100):
        observer.event_queue.put(event)

    file_watcher._stop_watchdog_observer(observer)

    assert not observer.stopped_with_pending_events
    assert observer.event_queue.empty()
    assert observer.event_queue.unfinished_tasks == 0


def test_observer_stops_event_producers_before_draining_the_queue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Emitter:
        def __init__(self, events: queue.Queue[object]) -> None:
            self.events = events
            self.alive = True
            self.watch = object()

        def stop(self) -> None:
            self.events.put("terminal")
            self.alive = False

        def join(self, timeout: float | None = None) -> None:
            return

        def is_alive(self) -> bool:
            return self.alive

    class Observer:
        def __init__(self) -> None:
            self.event_queue: queue.Queue[object] = queue.Queue()
            self.emitter = Emitter(self.event_queue)
            self.emitters = {self.emitter}
            self.alive = True

        def stop(self) -> None:
            assert not self.emitter.is_alive()
            assert self.event_queue.empty()
            self.alive = False

        def join(self, timeout: float | None = None) -> None:
            return

        def is_alive(self) -> bool:
            return self.alive

    observer = Observer()
    observer.event_queue.put("pending")

    def stop_emitter(emitter: Emitter) -> None:
        emitter.stop()
        emitter.join()

    monkeypatch.setattr(
        file_watcher,
        "_prepare_watchdog_emitter_stop",
        stop_emitter,
    )

    file_watcher._stop_watchdog_observer(observer)

    assert observer.event_queue.unfinished_tasks == 0


def test_bounded_observer_rechecks_stop_without_a_queue_wakeup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observer = file_watcher._bound_watchdog_dispatch(file_watcher.Observer())
    blocked = threading.Event()
    get = observer.event_queue.get

    def observed_get(
        block: bool = True,
        timeout: float | None = None,
    ) -> object:
        blocked.set()
        return get(block=block, timeout=timeout)

    monkeypatch.setattr(file_watcher, "_WATCHDOG_DISPATCH_TIMEOUT", 0.01)
    monkeypatch.setattr(observer.event_queue, "get", observed_get)
    observer.start()
    try:
        assert blocked.wait(timeout=1)
        observer.stopped_event.set()
        observer.join(timeout=1)
        assert not observer.is_alive()
    finally:
        if observer.is_alive():
            observer.stop()
            observer.join(timeout=1)


@pytest.mark.native_process
@pytest.mark.skipif(os.name != "nt", reason="Windows native watcher lifecycle")
def test_windows_native_watcher_repeatedly_releases_synchronous_reads(
    tmp_path: Path,
) -> None:
    async def exercise() -> None:
        async def callback(_path: Path) -> None:
            return

        for index in range(80):
            root = tmp_path / str(index)
            root.mkdir()
            source = root / "source.txt"
            source.write_text("ready", encoding="utf-8")
            watcher = file_watcher.PrivateProjectWatcher()
            await watcher.replace(ProjectWatchPlan((source,), ()), callback)
            await watcher.close()

    asyncio.run(exercise())


def test_native_watcher_shares_one_exact_path_between_project_owners(
    tmp_path: Path,
) -> None:
    class Observer:
        def __init__(self) -> None:
            self.watch = object()
            self.schedules = 0
            self.added = 0
            self.removed = 0
            self.unscheduled = 0
            self.started = False
            self.stopped = False

        def start(self) -> None:
            self.started = True

        def schedule(self, _handler: object, _path: str, *, recursive: bool) -> object:
            assert recursive is False
            self.schedules += 1
            return self.watch

        def add_handler_for_watch(self, _handler: object, watch: object) -> None:
            assert watch is self.watch
            self.added += 1

        def remove_handler_for_watch(self, _handler: object, watch: object) -> None:
            assert watch is self.watch
            self.removed += 1

        def unschedule(self, watch: object) -> None:
            assert watch is self.watch
            self.unscheduled += 1

        def stop(self) -> None:
            self.stopped = True

        def join(self, timeout: float | None = None) -> None:
            return

        def is_alive(self) -> bool:
            return False

    observer = Observer()
    registry = file_watcher._WatchdogRegistry(observer)
    registry.start()
    first = registry.add(tmp_path, False, object())
    second = registry.add(tmp_path, False, object())

    assert observer.started
    assert observer.schedules == 1
    assert observer.added == 1
    assert registry.remove(first) is False
    assert registry.remove(second) is True
    registry.close()
    assert observer.removed == 1
    assert observer.unscheduled == 1
    assert observer.stopped


def test_emitter_stop_failure_retains_registration_for_retry_and_reacquisition(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.txt"
    source.write_text("source", encoding="utf-8")

    class Emitter:
        def __init__(self, watch: object, *, blocked: bool) -> None:
            self.watch = watch
            self.blocked = blocked
            self.alive = True

        def is_alive(self) -> bool:
            return self.alive

    class Observer:
        def __init__(self, *, blocked: bool) -> None:
            self.watch = object()
            self.emitter = Emitter(self.watch, blocked=blocked)
            self.emitters: set[Emitter] = set()
            self.event_queue: queue.Queue[object] = queue.Queue()
            self.handler: Any | None = None
            self.alive = False
            self.unscheduled = 0

        def start(self) -> None:
            self.alive = True

        def schedule(
            self,
            _handler: object,
            _path: str,
            *,
            recursive: bool,
        ) -> object:
            assert not recursive
            self.handler = _handler
            self.emitters.add(self.emitter)
            return self.watch

        def unschedule(self, watch: object) -> None:
            assert watch is self.watch
            assert not self.emitter.is_alive()
            self.emitters.remove(self.emitter)
            self.unscheduled += 1

        def stop(self) -> None:
            self.alive = False

        def join(self, timeout: float | None = None) -> None:
            return

        def is_alive(self) -> bool:
            return self.alive

    first = Observer(blocked=True)
    replacement = Observer(blocked=False)
    observers = iter((first, replacement))

    def prepare(emitter: Emitter) -> None:
        if emitter.blocked:
            raise ProcessCleanupError("injected emitter stop failure")
        emitter.alive = False

    monkeypatch.setattr(file_watcher, "_new_watchdog_observer", lambda: next(observers))
    monkeypatch.setattr(file_watcher, "_prepare_watchdog_emitter_stop", prepare)
    monkeypatch.setattr(file_watcher, "_SHARED_WATCHDOG", None)
    plan = ProjectWatchPlan((source,), ())

    async def exercise() -> None:
        owner = file_watcher._watchdog_owner(
            plan,
            asyncio.get_running_loop(),
            lambda _path: None,
        )
        assert owner is not None
        with pytest.raises(ProcessCleanupError, match="injected emitter stop failure"):
            owner.stop()
        assert first.unscheduled == 0
        assert file_watcher._SHARED_WATCHDOG is not None

        with pytest.raises(ProcessCleanupError, match="still retiring"):
            file_watcher._watchdog_owner(
                plan,
                asyncio.get_running_loop(),
                lambda _path: None,
            )

        first.emitter.blocked = False
        owner.stop()
        assert first.unscheduled == 1
        assert file_watcher._SHARED_WATCHDOG is None

        delivered = asyncio.Event()
        next_owner = file_watcher._watchdog_owner(
            plan,
            asyncio.get_running_loop(),
            lambda _path: delivered.set(),
        )
        assert next_owner is not None
        assert replacement.handler is not None

        class Mutation:
            event_type = "modified"
            src_path = str(source)
            dest_path = None

        replacement.handler.on_any_event(Mutation())
        await asyncio.wait_for(delivered.wait(), timeout=1)
        next_owner.stop()
        assert replacement.unscheduled == 1
        assert file_watcher._SHARED_WATCHDOG is None

    asyncio.run(exercise())


def test_partial_registration_rollback_preserves_an_unrelated_live_owner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    survivor_root = tmp_path / "survivor"
    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    survivor_root.mkdir()
    first_root.mkdir()
    second_root.mkdir()
    survivor_source = survivor_root / "source.txt"
    first_source = first_root / "source.txt"
    second_source = second_root / "source.txt"
    survivor_source.write_text("survivor", encoding="utf-8")
    first_source.write_text("first", encoding="utf-8")
    second_source.write_text("second", encoding="utf-8")

    class Emitter:
        def __init__(self, observer: Observer, watch: object) -> None:
            self.observer = observer
            self.watch = watch
            self.alive = True

        def is_alive(self) -> bool:
            return self.alive

    class Observer:
        def __init__(self) -> None:
            self.blocked = True
            self.emitters: set[Emitter] = set()
            self.event_queue: queue.Queue[object] = queue.Queue()
            self.handlers: dict[str, Any] = {}
            self.alive = False
            self.schedules = 0
            self.stopped = False

        def start(self) -> None:
            self.alive = True

        def schedule(
            self,
            _handler: object,
            _path: str,
            *,
            recursive: bool,
        ) -> object:
            assert not recursive
            self.schedules += 1
            if self.schedules == 3:
                raise OSError("injected second registration failure")
            watch = object()
            self.emitters.add(Emitter(self, watch))
            self.handlers[_path] = _handler
            return watch

        def unschedule(self, watch: object) -> None:
            emitter = next(
                candidate for candidate in self.emitters if candidate.watch is watch
            )
            assert not emitter.is_alive()
            self.emitters.remove(emitter)

        def stop(self) -> None:
            self.alive = False
            self.stopped = True

        def join(self, timeout: float | None = None) -> None:
            return

        def is_alive(self) -> bool:
            return self.alive

    retained = Observer()

    def prepare(emitter: Emitter) -> None:
        if emitter.observer.blocked:
            raise ProcessCleanupError("injected rollback cleanup failure")
        emitter.alive = False

    monkeypatch.setattr(file_watcher, "_new_watchdog_observer", lambda: retained)
    monkeypatch.setattr(file_watcher, "_prepare_watchdog_emitter_stop", prepare)
    monkeypatch.setattr(file_watcher, "_SHARED_WATCHDOG", None)
    plan = ProjectWatchPlan((first_source, second_source), ())

    async def exercise() -> None:
        delivered = asyncio.Event()
        survivor = file_watcher._watchdog_owner(
            ProjectWatchPlan((survivor_source,), ()),
            asyncio.get_running_loop(),
            lambda _path: delivered.set(),
        )
        assert survivor is not None

        with pytest.raises(
            ProcessCleanupError,
            match="injected rollback cleanup failure",
        ) as captured:
            file_watcher._watchdog_owner(
                plan,
                asyncio.get_running_loop(),
                lambda _path: None,
            )
        assert isinstance(captured.value.__cause__, OSError)
        assert str(captured.value.__cause__) == "injected second registration failure"
        assert file_watcher._SHARED_WATCHDOG is not None
        assert file_watcher._SHARED_WATCHDOG.cleanup_pending

        retained.blocked = False
        owner = file_watcher._watchdog_owner(
            plan,
            asyncio.get_running_loop(),
            lambda _path: None,
        )
        assert owner is not None
        assert not retained.stopped
        assert retained.schedules == 5

        class Mutation:
            event_type = "modified"
            src_path = str(survivor_source)
            dest_path = None

        retained.handlers[str(survivor_root.absolute())].on_any_event(Mutation())
        await asyncio.wait_for(delivered.wait(), timeout=1)
        owner.stop()
        assert not retained.stopped
        survivor.stop()
        assert retained.stopped
        assert file_watcher._SHARED_WATCHDOG is None

    asyncio.run(exercise())


def test_recursive_registration_failure_keeps_the_shallow_watch(
    tmp_path: Path,
) -> None:
    class Observer:
        def __init__(self) -> None:
            self.shallow_watch = object()
            self.unscheduled = 0

        def start(self) -> None:
            return

        def schedule(self, _handler: object, _path: str, *, recursive: bool) -> object:
            if recursive:
                raise OSError("recursive schedule failed")
            return self.shallow_watch

        def add_handler_for_watch(self, _handler: object, _watch: object) -> None:
            return

        def remove_handler_for_watch(self, _handler: object, watch: object) -> None:
            assert watch is self.shallow_watch

        def unschedule(self, watch: object) -> None:
            assert watch is self.shallow_watch
            self.unscheduled += 1

        def stop(self) -> None:
            return

        def join(self, timeout: float | None = None) -> None:
            return

        def is_alive(self) -> bool:
            return False

    observer = Observer()
    registry = file_watcher._WatchdogRegistry(observer)
    registry.start()
    shallow = registry.add(tmp_path, False, object())

    with pytest.raises(OSError, match="recursive schedule failed"):
        registry.add(tmp_path, True, object())

    assert observer.unscheduled == 0
    assert registry.remove(shallow)
    registry.close()
    assert observer.unscheduled == 1


def test_first_registration_failure_closes_the_shared_observer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Handler:
        pass

    class Observer:
        def __init__(self) -> None:
            self.started = False
            self.stopped = False
            self.joined = False

        def start(self) -> None:
            self.started = True

        def schedule(self, _handler: object, _path: str, *, recursive: bool) -> object:
            assert recursive
            raise OSError("first schedule failed")

        def stop(self) -> None:
            self.stopped = True

        def join(self, timeout: float | None = None) -> None:
            self.joined = True

        def is_alive(self) -> bool:
            return False

    observer = Observer()
    monkeypatch.setattr(file_watcher, "FileSystemEventHandler", Handler)
    monkeypatch.setattr(file_watcher, "_new_watchdog_observer", lambda: observer)
    monkeypatch.setattr(file_watcher, "_SHARED_WATCHDOG", None)
    root = tmp_path / "view"
    root.mkdir()

    async def exercise() -> None:
        with pytest.raises(OSError, match="first schedule failed"):
            file_watcher._watchdog_owner(
                ProjectWatchPlan((), (root,)),
                asyncio.get_running_loop(),
                lambda _path: None,
            )

    asyncio.run(exercise())

    assert observer.started
    assert observer.stopped
    assert observer.joined
    assert file_watcher._SHARED_WATCHDOG is None


def test_start_failure_retains_timed_out_observer_for_next_acquisition(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.txt"
    source.write_text("source", encoding="utf-8")

    class Observer:
        def __init__(self, *, fail_start: bool, hung: bool) -> None:
            self.fail_start = fail_start
            self.hung = hung
            self.alive = False
            self.watch = object()
            self.stop_calls = 0
            self.join_timeouts: list[float | None] = []

        def start(self) -> None:
            self.alive = True
            if self.fail_start:
                raise OSError("watchdog start failed")

        def schedule(
            self,
            _handler: object,
            _path: str,
            *,
            recursive: bool,
        ) -> object:
            assert not recursive
            return self.watch

        def remove_handler_for_watch(
            self,
            _handler: object,
            watch: object,
        ) -> None:
            assert watch is self.watch

        def unschedule(self, watch: object) -> None:
            assert watch is self.watch

        def stop(self) -> None:
            self.stop_calls += 1
            if not self.hung:
                self.alive = False

        def join(self, timeout: float | None = None) -> None:
            self.join_timeouts.append(timeout)

        def is_alive(self) -> bool:
            return self.alive

    failed = Observer(fail_start=True, hung=True)
    replacement = Observer(fail_start=False, hung=False)
    observers = iter((failed, replacement))
    monkeypatch.setattr(file_watcher, "_new_watchdog_observer", lambda: next(observers))
    monkeypatch.setattr(file_watcher, "_SHARED_WATCHDOG", None)
    plan = ProjectWatchPlan((source,), ())

    async def exercise() -> None:
        with pytest.raises(
            ProcessCleanupError,
            match="Watchdog observer did not stop",
        ) as captured:
            file_watcher._watchdog_owner(
                plan,
                asyncio.get_running_loop(),
                lambda _path: None,
            )
        assert isinstance(captured.value.__cause__, OSError)
        assert str(captured.value.__cause__) == "watchdog start failed"
        initial_stop_attempts = failed.stop_calls
        assert initial_stop_attempts > 0
        _assert_bounded_join(failed.join_timeouts)
        assert file_watcher._SHARED_WATCHDOG is not None
        assert file_watcher._SHARED_WATCHDOG.cleanup_pending

        failed.alive = False
        owner = file_watcher._watchdog_owner(
            plan,
            asyncio.get_running_loop(),
            lambda _path: None,
        )
        assert owner is not None
        assert failed.stop_calls > initial_stop_attempts
        _assert_bounded_join(failed.join_timeouts)
        assert replacement.alive
        owner.stop()
        assert replacement.stop_calls > 0
        _assert_bounded_join(replacement.join_timeouts)
        assert not replacement.alive
        assert file_watcher._SHARED_WATCHDOG is None

    asyncio.run(exercise())


def test_project_watcher_surfaces_bounded_native_teardown_and_retries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.txt"
    source.write_text("source", encoding="utf-8")

    class Observer:
        def __init__(self) -> None:
            self.watch = object()
            self.alive = True
            self.stop_calls = 0
            self.join_timeouts: list[float | None] = []

        def start(self) -> None:
            return

        def schedule(
            self,
            _handler: object,
            _path: str,
            *,
            recursive: bool,
        ) -> object:
            assert not recursive
            return self.watch

        def remove_handler_for_watch(
            self,
            _handler: object,
            watch: object,
        ) -> None:
            assert watch is self.watch

        def unschedule(self, watch: object) -> None:
            assert watch is self.watch

        def stop(self) -> None:
            self.stop_calls += 1

        def join(self, timeout: float | None = None) -> None:
            self.join_timeouts.append(timeout)

        def is_alive(self) -> bool:
            return self.alive

    observer = Observer()
    monkeypatch.setattr(file_watcher, "_new_watchdog_observer", lambda: observer)
    monkeypatch.setattr(file_watcher, "_SHARED_WATCHDOG", None)
    monkeypatch.setattr(file_watcher, "_COALESCE_SECONDS", 0)

    async def exercise() -> None:
        watcher = file_watcher.PrivateProjectWatcher()
        delivered = asyncio.Event()

        async def callback(_path: Path) -> None:
            delivered.set()

        await watcher.replace(ProjectWatchPlan((source,), ()), callback)
        await asyncio.wait_for(delivered.wait(), timeout=1)

        with pytest.raises(
            ProcessCleanupError,
            match="Watchdog observer did not stop",
        ):
            await asyncio.wait_for(watcher.close(), timeout=1)
        initial_stop_attempts = observer.stop_calls
        assert initial_stop_attempts > 0
        _assert_bounded_join(observer.join_timeouts)
        assert file_watcher._SHARED_WATCHDOG is not None
        assert watcher._observer is not None
        assert watcher._callback is None
        assert watcher._notify_task is None or watcher._notify_task.done()
        assert not watcher._pending

        observer.alive = False
        await asyncio.wait_for(watcher.close(), timeout=1)
        assert observer.stop_calls > initial_stop_attempts
        _assert_bounded_join(observer.join_timeouts)
        assert file_watcher._SHARED_WATCHDOG is None
        assert watcher._observer is None
        assert watcher._notify_task is None or watcher._notify_task.done()
        assert not watcher._pending

    asyncio.run(exercise())


def test_missing_watch_root_matches_creation_of_its_ancestor(tmp_path: Path) -> None:
    root = tmp_path / "view" / "generated" / "src"
    plan = ProjectWatchPlan((), (root,))

    assert file_watcher._matches(plan, tmp_path / "view")
    assert not file_watcher._matches(plan, tmp_path / "other")


def test_project_watcher_drains_an_event_arriving_during_callback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = tmp_path / "first.txt"
    second = tmp_path / "second.txt"
    first.write_text("first", encoding="utf-8")
    second.write_text("second", encoding="utf-8")

    class Observer:
        def stop(self) -> None:
            pass

        def join(self) -> None:
            pass

    monkeypatch.setattr(file_watcher, "_watchdog_owner", lambda *_args: Observer())
    monkeypatch.setattr(file_watcher, "_COALESCE_SECONDS", 0)

    async def exercise() -> None:
        entered = asyncio.Event()
        second_delivered = asyncio.Event()
        release = asyncio.Event()
        calls: list[Path] = []
        watcher = file_watcher.PrivateProjectWatcher()

        async def callback(path: Path) -> None:
            calls.append(path)
            if len(calls) == 1:
                entered.set()
                await release.wait()
            elif len(calls) == 2:
                second_delivered.set()

        await watcher.replace(ProjectWatchPlan((first, second), ()), callback)
        try:
            await wait_for_event(entered)
            watcher._signal(second)
            release.set()
            await asyncio.wait_for(second_delivered.wait(), timeout=1)
            assert calls == [first, second]
        finally:
            release.set()
            await watcher.close()

    asyncio.run(exercise())


def test_project_watcher_ignores_signals_while_replacing_its_owner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = tmp_path / "first.txt"
    second = tmp_path / "second.txt"
    queued = tmp_path / "queued.txt"
    for path in (first, second, queued):
        path.write_text(path.stem, encoding="utf-8")
    stop_started = threading.Event()
    release_stop = threading.Event()
    owners = 0

    class Owner:
        def __init__(self, gated: bool) -> None:
            self._gated = gated

        def stop(self) -> None:
            if self._gated:
                stop_started.set()
                assert release_stop.wait(timeout=2)

        def join(self) -> None:
            return

    def owner(*_args: object) -> Owner:
        nonlocal owners
        selected = Owner(gated=owners == 0)
        owners += 1
        return selected

    monkeypatch.setattr(file_watcher, "_watchdog_owner", owner)
    monkeypatch.setattr(file_watcher, "_COALESCE_SECONDS", 0)

    async def exercise() -> None:
        watcher = file_watcher.PrivateProjectWatcher()
        first_delivered = asyncio.Event()
        replacement_delivered = asyncio.Event()
        replacement_paths: list[Path] = []

        async def first_callback(_path: Path) -> None:
            first_delivered.set()

        async def replacement_callback(path: Path) -> None:
            replacement_paths.append(path)
            replacement_delivered.set()

        await watcher.replace(ProjectWatchPlan((first,), ()), first_callback)
        await asyncio.wait_for(first_delivered.wait(), timeout=1)
        replacing = asyncio.create_task(
            watcher.replace(
                ProjectWatchPlan((second,), ()),
                replacement_callback,
            )
        )
        try:
            assert await asyncio.to_thread(stop_started.wait, 1)
            watcher._signal(queued)
            release_stop.set()
            await replacing
            await asyncio.wait_for(replacement_delivered.wait(), timeout=1)
            assert replacement_paths == [second.absolute()]
        finally:
            release_stop.set()
            await asyncio.gather(replacing, return_exceptions=True)
            await watcher.close()

    asyncio.run(exercise())


def test_project_watcher_ignores_a_queued_callback_while_closing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.txt"
    queued = tmp_path / "queued.txt"
    source.write_text("source", encoding="utf-8")
    queued.write_text("queued", encoding="utf-8")
    stop_started = threading.Event()
    release_stop = threading.Event()

    class Owner:
        def stop(self) -> None:
            stop_started.set()
            assert release_stop.wait(timeout=2)

        def join(self) -> None:
            return

    monkeypatch.setattr(file_watcher, "_watchdog_owner", lambda *_args: Owner())
    monkeypatch.setattr(file_watcher, "_COALESCE_SECONDS", 0)

    async def exercise() -> None:
        watcher = file_watcher.PrivateProjectWatcher()
        delivered = asyncio.Event()
        delivered_paths: list[Path] = []

        async def callback(path: Path) -> None:
            delivered_paths.append(path)
            delivered.set()

        await watcher.replace(ProjectWatchPlan((source,), ()), callback)
        await asyncio.wait_for(delivered.wait(), timeout=1)
        notify_started = asyncio.Event()
        release_notify = asyncio.Event()
        notify = watcher._notify

        async def gated_notify(generation: int) -> None:
            notify_started.set()
            await release_notify.wait()
            await notify(generation)

        monkeypatch.setattr(watcher, "_notify", gated_notify)
        watcher._signal(queued)
        await asyncio.wait_for(notify_started.wait(), timeout=1)
        closing = asyncio.create_task(watcher.close())
        try:
            assert await asyncio.to_thread(stop_started.wait, 1)
            release_stop.set()
            await closing
            assert delivered_paths == [source.absolute()]
        finally:
            release_notify.set()
            release_stop.set()
            await asyncio.gather(closing, return_exceptions=True)

    asyncio.run(exercise())


def test_project_watcher_restarts_when_plan_semantics_change(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "view"
    artifacts = root / ".artifacts"
    artifacts.mkdir(parents=True)

    class Observer:
        def __init__(self) -> None:
            self.stopped = False

        def stop(self) -> None:
            self.stopped = True

        def join(self) -> None:
            pass

    owners: list[Observer] = []

    def owner(*_args: object) -> Observer:
        observer = Observer()
        owners.append(observer)
        return observer

    monkeypatch.setattr(file_watcher, "_watchdog_owner", owner)

    async def exercise() -> None:
        watcher = file_watcher.PrivateProjectWatcher()

        async def callback(_path: Path) -> None:
            pass

        await watcher.replace(ProjectWatchPlan((root,), ()), callback)
        await watcher.replace(ProjectWatchPlan((), (root,)), callback)
        await watcher.replace(ProjectWatchPlan((), (root,), (artifacts,)), callback)
        try:
            assert len(owners) == 3
            assert owners[0].stopped
            assert owners[1].stopped
            assert not owners[2].stopped
        finally:
            await watcher.close()

    asyncio.run(exercise())


def test_project_watcher_resubscribes_as_a_missing_root_is_created(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "view" / "generated" / "src"
    (tmp_path / "view").mkdir()

    class Observer:
        def stop(self) -> None:
            return

        def join(self) -> None:
            return

    owners: list[Observer] = []

    def owner(*_args: object) -> Observer:
        observer = Observer()
        owners.append(observer)
        return observer

    monkeypatch.setattr(file_watcher, "_watchdog_owner", owner)

    async def exercise() -> None:
        watcher = file_watcher.PrivateProjectWatcher()

        async def callback(_path: Path) -> None:
            return

        await watcher.replace(ProjectWatchPlan((), (root,)), callback)
        root.parent.mkdir(exist_ok=True)
        await watcher.replace(ProjectWatchPlan((), (root,)), callback)
        root.mkdir()
        await watcher.replace(ProjectWatchPlan((), (root,)), callback)
        try:
            assert len(owners) == 3
        finally:
            await watcher.close()

    asyncio.run(exercise())


def test_slow_native_shutdown_does_not_block_the_event_loop(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = threading.Event()
    release = threading.Event()

    class Owner:
        def stop(self) -> None:
            started.set()
            assert release.wait(timeout=1)

        def join(self) -> None:
            return

    monkeypatch.setattr(file_watcher, "_watchdog_owner", lambda *_args: Owner())

    async def exercise() -> None:
        watcher = file_watcher.PrivateProjectWatcher()

        async def callback(_path: Path) -> None:
            return

        await watcher.replace(ProjectWatchPlan((tmp_path,), ()), callback)
        closing = asyncio.create_task(watcher.close())
        try:
            assert await asyncio.to_thread(started.wait, 1)
            heartbeat = asyncio.Event()
            asyncio.get_running_loop().call_soon(heartbeat.set)
            await wait_for_event(heartbeat)
            assert not closing.done()
            release.set()
            await closing
        finally:
            release.set()
            await asyncio.gather(closing, return_exceptions=True)

    asyncio.run(exercise())
