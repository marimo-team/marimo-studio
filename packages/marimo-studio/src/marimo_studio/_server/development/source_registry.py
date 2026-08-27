"""Own source monitor membership and subscriber lifetimes."""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass

from marimo_studio._server.development.ports import ProjectWatcherFactory
from marimo_studio._server.development.source_changes import SourceChangeProducer
from marimo_studio._server.development.source_ownership import (
    SourceSubscription,
    SourceWatcherOwner,
    _SourceCreation,
    _SourceMonitor,
    _SubscriptionOwner,
)
from marimo_studio.view_providers import ProviderCancellation


@dataclass(frozen=True)
class SourceOwners:
    monitors: tuple[_SourceMonitor, ...]
    creations: tuple[_SourceCreation, ...]


@dataclass(frozen=True)
class ViewSourceOwners:
    creation: _SourceCreation | None
    monitor: _SourceMonitor | None


class SourceMonitorRegistry:
    """Create, retain, and retire notebook-scoped source monitors."""

    def __init__(self, watcher: ProjectWatcherFactory) -> None:
        self._watcher = watcher
        self._monitors: dict[str | None, _SourceMonitor] = {}
        self._creations: dict[str | None, _SourceCreation] = {}

    def monitor_locked(self, key: str | None) -> _SourceMonitor | None:
        return self._monitors.get(key)

    def subscribe_locked(
        self,
        key: str | None,
        owner: _SubscriptionOwner,
        create: Callable[[ProviderCancellation], asyncio.Task[SourceChangeProducer]],
    ) -> tuple[SourceSubscription | None, _SourceCreation | None]:
        monitor = self._monitors.get(key)
        if monitor is not None:
            return self._subscription(owner, key, monitor), None
        creation = self._creations.get(key)
        if creation is None:
            control = ProviderCancellation()
            creation = _SourceCreation(control, create(control))
            self._creations[key] = creation
        creation.waiters += 1
        return None, creation

    def claim_creation_locked(
        self,
        key: str | None,
        creation: _SourceCreation,
        producer: SourceChangeProducer,
        owner: _SubscriptionOwner,
    ) -> SourceSubscription | None:
        creation.waiters -= 1
        monitor = self._monitors.get(key)
        if monitor is None:
            if self._creations.get(key) is not creation:
                return None
            self._creations.pop(key, None)
            monitor = _SourceMonitor(
                producer=producer,
                watcher=SourceWatcherOwner(self._watcher()),
                generation=0,
                journal=deque(maxlen=16),
                subscribers=set(),
            )
            self._monitors[key] = monitor
        return self._subscription(owner, key, monitor)

    def release_creation_waiter_locked(
        self,
        key: str | None,
        creation: _SourceCreation,
    ) -> bool:
        creation.waiters -= 1
        if self._creations.get(key) is not creation or creation.waiters != 0:
            return False
        self._creations.pop(key, None)
        return not creation.task.done()

    def remove_subscriber_locked(
        self,
        key: str | None,
        expected: _SourceMonitor,
        token: object,
    ) -> asyncio.Task[None] | None:
        monitor = self._monitors.get(key)
        if monitor is not expected or token not in monitor.subscribers:
            return None
        monitor.subscribers.remove(token)
        if monitor.subscribers:
            return None
        task = monitor.task
        monitor.task = None
        monitor.changed.clear()
        return task

    def idle_locked(self, key: str | None, expected: _SourceMonitor) -> bool:
        monitor = self._monitors.get(key)
        return monitor is expected and not monitor.subscribers and monitor.task is None

    def contains_locked(self, key: str | None, expected: _SourceMonitor) -> bool:
        return self._monitors.get(key) is expected

    def begin_view_deletion_locked(self, view_name: str) -> ViewSourceOwners:
        return ViewSourceOwners(
            self._creations.pop(view_name, None),
            self._monitors.get(view_name),
        )

    def finish_view_deletion_locked(
        self,
        view_name: str,
        monitor: _SourceMonitor | None,
        *,
        committed: bool,
    ) -> bool:
        if (
            committed
            and monitor is not None
            and self._monitors.get(view_name) is monitor
        ):
            self._monitors.pop(view_name, None)
            return True
        return False

    def begin_close_locked(self) -> SourceOwners:
        return SourceOwners(
            tuple(self._monitors.values()),
            tuple(self._creations.values()),
        )

    def clear_locked(self) -> None:
        self._monitors.clear()
        self._creations.clear()

    @staticmethod
    def _subscription(
        owner: _SubscriptionOwner,
        key: str | None,
        monitor: _SourceMonitor,
    ) -> SourceSubscription:
        token = object()
        monitor.subscribers.add(token)
        return SourceSubscription(owner, key, monitor.generation, monitor, token)
