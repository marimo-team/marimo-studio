"""Own source subscriptions and serialized native watcher transitions."""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from marimo_studio._processes.ownership import (
    propagate_cancellation,
    settle_ownership,
)
from marimo_studio._server.development.ports import (
    FileChangeCallback,
    ProjectWatcher,
    ProjectWatchPlan,
)
from marimo_studio._server.development.source_changes import (
    SourceChange,
    SourceChangeProducer,
)
from marimo_studio.view_providers import (
    ProjectInspection,
    ProviderCancellation,
    ViewProject,
)

ActiveMonitor = Callable[[], Awaitable[bool]]


class SourceWatcherOwner:
    """Serialize one native watcher's replace and close lifecycle."""

    def __init__(self, watcher: ProjectWatcher) -> None:
        self._watcher = watcher
        self._lock = asyncio.Lock()

    async def replace_if(
        self,
        plan: ProjectWatchPlan,
        callback: FileChangeCallback,
        active: ActiveMonitor,
    ) -> bool:
        """Replace the plan only while the monitor retains a live subscriber."""
        async with self._lock:
            if not await active():
                return False
            try:
                await self._watcher.replace(plan, callback)
            except BaseException:
                await self._watcher.close()
                raise
            if await active():
                return True
            await self._watcher.close()
            return False

    async def close(self) -> None:
        async with self._lock:
            await self._watcher.close()


@dataclass(frozen=True)
class SourcePoll:
    generation: int
    change: SourceChange


@dataclass(frozen=True)
class ProjectCatalog:
    project: ViewProject
    inspection: ProjectInspection
    input_id: str
    generation: int


@dataclass
class _SourceMonitor:
    producer: SourceChangeProducer
    watcher: SourceWatcherOwner
    generation: int
    journal: deque[SourcePoll]
    subscribers: set[object]
    task: asyncio.Task[None] | None = None
    scan_control: ProviderCancellation | None = None
    scan_task: asyncio.Task[Any] | None = None
    rebuild: bool = False
    changed: asyncio.Event = field(default_factory=asyncio.Event)
    error: Exception | None = None
    activation_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    scan_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    probe_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    probe_task: asyncio.Task[bool] | None = None
    last_probe: float = 0.0


@dataclass
class _SourceCreation:
    control: ProviderCancellation
    task: asyncio.Task[SourceChangeProducer]
    waiters: int = 0


class _SubscriptionOwner(Protocol):
    async def _poll(
        self,
        key: str | None,
        after: int,
        expected: _SourceMonitor,
    ) -> SourcePoll | None: ...

    async def _unsubscribe(
        self,
        key: str | None,
        expected: _SourceMonitor,
        token: object,
    ) -> None: ...


class SourceSubscription:
    """Track one subscriber's cursor in a shared source journal."""

    def __init__(
        self,
        owner: _SubscriptionOwner,
        key: str | None,
        generation: int,
        monitor: _SourceMonitor,
        token: object,
    ) -> None:
        self._owner = owner
        self._key = key
        self._generation = generation
        self._monitor = monitor
        self._token = token
        self._closed = False
        self._close_lock = asyncio.Lock()

    @property
    def generation(self) -> int:
        return self._generation

    async def poll(self) -> SourcePoll | None:
        if self._closed:
            return None
        event = await self._owner._poll(
            self._key,
            self._generation,
            self._monitor,
        )
        if event is not None:
            self._generation = event.generation
        return event

    async def close(self) -> None:
        cancellation: asyncio.CancelledError | None = None
        async with self._close_lock:
            if self._closed:
                return
            _result, cancellation = await settle_ownership(
                self._owner._unsubscribe(
                    self._key,
                    self._monitor,
                    self._token,
                )
            )
            self._closed = True
        propagate_cancellation(cancellation)
