"""Watch one bounded Studio project through the mandatory watchdog runtime."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from threading import Event, Lock
from typing import Any

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from marimo_studio._processes.ownership import (
    propagate_cancellation,
    settle_ownership,
)
from marimo_studio._processes.provider_operation import process_cleanup_errors
from marimo_studio._processes.supervisor import ProcessCleanupError
from marimo_studio._server.development.ports import FileChangeCallback, ProjectWatchPlan

_COALESCE_SECONDS = 0.05
_WATCHDOG_JOIN_TIMEOUT = 2.0
_MUTATION_EVENTS = frozenset({"closed", "created", "deleted", "modified", "moved"})
_SHARED_WATCHDOG_LOCK = Lock()
_SHARED_WATCHDOG: _WatchdogRegistry | None = None


def _stop_watchdog_observer(observer: Any) -> None:
    observer.stop()
    observer.join(timeout=_WATCHDOG_JOIN_TIMEOUT)
    if observer.is_alive():
        raise ProcessCleanupError(
            f"Watchdog observer did not stop within {_WATCHDOG_JOIN_TIMEOUT:g} seconds"
        )


class _WatchdogEntry:
    def __init__(self, watch: Any, handler: Any) -> None:
        self.watch = watch
        self.handlers = {handler}


class _WatchdogRegistry:
    """Share one native observer across notebook-scoped project watchers."""

    def __init__(self, observer: Any) -> None:
        self._observer = observer
        self._entries: dict[tuple[Path, bool], _WatchdogEntry] = {}
        self._lock = Lock()
        self._cleanup_pending = False
        self._started = False

    def start(self) -> None:
        if self._started:
            return
        try:
            self._observer.start()
        except BaseException as start_error:
            try:
                self.close()
            except BaseException as cleanup_error:
                raise cleanup_error from start_error
            raise
        self._started = True

    def add(
        self,
        path: Path,
        recursive: bool,
        handler: Any,
    ) -> tuple[Path, bool, Any]:
        with self._lock:
            key = (path, recursive)
            entry = self._entries.get(key)
            if entry is None:
                watch = self._observer.schedule(
                    handler,
                    str(path),
                    recursive=recursive,
                )
                self._entries[key] = _WatchdogEntry(watch, handler)
                return path, recursive, handler
            self._observer.add_handler_for_watch(handler, entry.watch)
            entry.handlers.add(handler)
            return path, recursive, handler

    def remove(self, registration: tuple[Path, bool, Any]) -> bool:
        path, recursive, handler = registration
        with self._lock:
            key = (path, recursive)
            entry = self._entries.get(key)
            if entry is None or handler not in entry.handlers:
                return not self._entries
            self._observer.remove_handler_for_watch(handler, entry.watch)
            entry.handlers.remove(handler)
            if not entry.handlers:
                self._observer.unschedule(entry.watch)
                self._entries.pop(key)
            return not self._entries

    @property
    def empty(self) -> bool:
        with self._lock:
            return not self._entries

    @property
    def cleanup_pending(self) -> bool:
        return self._cleanup_pending

    def close(self) -> None:
        try:
            _stop_watchdog_observer(self._observer)
        except BaseException:
            self._cleanup_pending = True
            raise
        self._cleanup_pending = False
        self._started = False


class _SharedWatchdogOwner:
    def __init__(
        self,
        registrations: list[tuple[Path, bool, Any]],
        active: Event | None = None,
    ) -> None:
        self._registrations = registrations
        self._active = active

    def stop(self) -> None:
        global _SHARED_WATCHDOG
        if self._active is not None:
            self._active.clear()
        registrations = self._registrations
        self._registrations = []
        with _SHARED_WATCHDOG_LOCK:
            registry = _SHARED_WATCHDOG
            if registry is None:
                return
            for registration in registrations:
                registry.remove(registration)
            if registry.empty:
                registry.close()
                if _SHARED_WATCHDOG is registry:
                    _SHARED_WATCHDOG = None

    def join(self) -> None:
        return


def _matches(plan: ProjectWatchPlan, path: Path) -> bool:
    candidate = path.absolute()
    if any(
        candidate == excluded.absolute() or excluded.absolute() in candidate.parents
        for excluded in plan.excluded
    ):
        return False
    for target in plan.files:
        selected = target.absolute()
        if candidate == selected or (
            selected.is_dir() and candidate.parent == selected
        ):
            return True
    return any(
        candidate == root.absolute()
        or root.absolute() in candidate.parents
        or candidate in root.absolute().parents
        for root in plan.roots
    )


def _watchdog_event_is_mutation(event_type: str) -> bool:
    return event_type in _MUTATION_EVENTS


def _nearest_watch_directory(path: Path) -> Path | None:
    candidate = path if path.is_dir() else path.parent
    while not candidate.is_dir() and candidate != candidate.parent:
        candidate = candidate.parent
    return candidate.absolute() if candidate.is_dir() else None


def _watchdog_targets(plan: ProjectWatchPlan) -> tuple[set[Path], set[Path]]:
    recursive = {root.absolute() for root in plan.roots if root.is_dir()}
    shallow = {
        candidate
        for path in plan.files
        if (candidate := _nearest_watch_directory(path)) is not None
    }
    shallow.update(
        candidate
        for root in plan.roots
        if not root.is_dir()
        and (candidate := _nearest_watch_directory(root)) is not None
    )
    recursive = {
        root
        for root in recursive
        if not any(other != root and other in root.parents for other in recursive)
    }
    shallow = {
        root
        for root in shallow
        if not any(root == parent or parent in root.parents for parent in recursive)
    }
    return recursive, shallow


def _watchdog_owner(
    plan: ProjectWatchPlan,
    loop: asyncio.AbstractEventLoop,
    notify: Any,
) -> Any | None:
    active = Event()
    active.set()

    def on_any_event(event: Any) -> None:
        if not active.is_set() or not _watchdog_event_is_mutation(event.event_type):
            return
        candidates = [Path(os.fsdecode(event.src_path))]
        destination = getattr(event, "dest_path", None)
        if destination:
            candidates.append(Path(os.fsdecode(destination)))
        for candidate in candidates:
            if _matches(plan, candidate):
                try:
                    loop.call_soon_threadsafe(notify, candidate)
                except RuntimeError:
                    if active.is_set() and not loop.is_closed():
                        raise
                return

    class Handler(FileSystemEventHandler):
        def on_any_event(self, event: Any) -> None:
            on_any_event(event)

    handler = Handler()
    recursive, shallow = _watchdog_targets(plan)
    if not recursive and not shallow:
        return None
    global _SHARED_WATCHDOG
    registrations: list[tuple[Path, bool, Any]] = []
    registry_ready = False
    try:
        with _SHARED_WATCHDOG_LOCK:
            if _SHARED_WATCHDOG is not None and _SHARED_WATCHDOG.cleanup_pending:
                retained = _SHARED_WATCHDOG
                retained.close()
                if _SHARED_WATCHDOG is retained:
                    _SHARED_WATCHDOG = None
            if _SHARED_WATCHDOG is None:
                registry = _WatchdogRegistry(Observer())
                _SHARED_WATCHDOG = registry
                try:
                    registry.start()
                except BaseException:
                    if not registry.cleanup_pending and _SHARED_WATCHDOG is registry:
                        _SHARED_WATCHDOG = None
                    raise
            registry = _SHARED_WATCHDOG
            registry_ready = True
            for root in sorted(recursive, key=str):
                registrations.append(registry.add(root, True, handler))
            for root in sorted(shallow, key=str):
                registrations.append(registry.add(root, False, handler))
    except BaseException:
        if registry_ready:
            _SharedWatchdogOwner(registrations, active).stop()
        raise
    return _SharedWatchdogOwner(registrations, active)


class PrivateProjectWatcher:
    """Own one native observer for a replaceable project plan."""

    def __init__(self) -> None:
        self._plan = ProjectWatchPlan((), ())
        self._signature: tuple[tuple[str, str, str], ...] = ()
        self._callback: FileChangeCallback | None = None
        self._generation = 0
        self._notify_task: asyncio.Task[None] | None = None
        self._observer: Any | None = None
        self._pending: set[Path] = set()
        self._ownership_lock = asyncio.Lock()

    async def replace(
        self,
        plan: ProjectWatchPlan,
        callback: FileChangeCallback,
    ) -> None:
        selected = ProjectWatchPlan(
            tuple(sorted({path.absolute() for path in plan.files}, key=str)),
            tuple(sorted({path.absolute() for path in plan.roots}, key=str)),
            tuple(sorted({path.absolute() for path in plan.excluded}, key=str)),
        )
        signature = tuple(
            (role, str(path), "directory" if path.is_dir() else "file")
            for role, paths in (
                ("file", selected.files),
                ("root", selected.roots),
                ("excluded", selected.excluded),
            )
            for path in paths
        )
        recursive, shallow = _watchdog_targets(selected)
        signature = (
            *signature,
            *(("owner", str(path), "recursive") for path in sorted(recursive, key=str)),
            *(("owner", str(path), "shallow") for path in sorted(shallow, key=str)),
        )
        async with self._ownership_lock:
            if signature == self._signature and self._observer is not None:
                self._callback = callback
                self._plan = selected
                return
            self._callback = None
            cancellation = await self._stop_owner()
            self._plan = selected
            self._signature = signature
            self._generation += 1
            loop = asyncio.get_running_loop()
            observer, owner_cancellation = await settle_ownership(
                asyncio.to_thread(
                    _watchdog_owner,
                    selected,
                    loop,
                    self._signal,
                )
            )
            self._observer = observer
            self._callback = callback
            if observer is not None:
                path = selected.roots[0] if selected.roots else selected.files[0]
                self._signal(path)
            if cancellation is None:
                cancellation = owner_cancellation
        propagate_cancellation(cancellation)

    def _signal(self, path: Path) -> None:
        if self._callback is None:
            return
        self._pending.add(path)
        if self._notify_task is None or self._notify_task.done():
            self._notify_task = asyncio.create_task(self._notify(self._generation))

    async def _notify(self, generation: int) -> None:
        await asyncio.sleep(_COALESCE_SECONDS)
        while (
            generation == self._generation
            and self._callback is not None
            and self._pending
        ):
            path = min(self._pending, key=str)
            self._pending.clear()
            await self._callback(path)

    async def _stop_owner(self) -> asyncio.CancelledError | None:
        self._generation += 1
        if self._notify_task is not None:
            task = self._notify_task
            self._notify_task = None
            task.cancel()
            results, cancellation = await settle_ownership(
                asyncio.gather(task, return_exceptions=True)
            )
            errors = process_cleanup_errors(results)
            if errors:
                raise errors[0]
        else:
            cancellation = None
        if self._observer is not None:
            observer = self._observer
            _result, owner_cancellation = await settle_ownership(
                asyncio.to_thread(lambda: (observer.stop(), observer.join()))
            )
            self._observer = None
            if cancellation is None:
                cancellation = owner_cancellation
        self._pending.clear()
        return cancellation

    async def close(self) -> None:
        async with self._ownership_lock:
            self._callback = None
            cancellation = await self._stop_owner()
            self._plan = ProjectWatchPlan((), ())
            self._signature = ()
        propagate_cancellation(cancellation)
