"""Share source monitoring and rebuilds across browsers for one notebook.

Browsers share one provider inspection and source monitor per view, plus one
in-flight rebuild for each view, source version, and build profile. Newer source
cancels work for older source. A browser that falls behind receives a complete
current state instead of an unbounded sequence of missed updates.

Project reads, Source writes, presentation capture, and validation ask this
coordinator to confirm that the view source they observed is still current.
View deletion and notebook shutdown stop new work, drain provider operations
and rebuilds, and close every file watcher before the filesystem mutation or
scope close completes.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from time import monotonic
from typing import Any

from marimo_studio._processes.cancellation import provider_cancellation
from marimo_studio._processes.ownership import (
    propagate_cancellation,
    settle_ownership,
)
from marimo_studio._processes.provider_operation import (
    process_cleanup_errors,
    raise_process_cleanup,
)
from marimo_studio._server.development.ports import (
    ProjectWatcherFactory,
)
from marimo_studio._server.development.publication_registry import (
    PublicationOwners,
    PublicationRegistry,
    ViewPublicationOwners,
)
from marimo_studio._server.development.source_changes import (
    SourceChange,
    SourceChangeProducer,
)
from marimo_studio._server.development.source_ownership import (
    ProjectCatalog,
    SourcePoll,
    SourceSubscription,
    _SourceCreation,
    _SourceMonitor,
)
from marimo_studio._server.development.source_registry import (
    SourceMonitorRegistry,
    SourceOwners,
    ViewSourceOwners,
)
from marimo_studio._server.development.task_ownership import (
    drain_future,
    run_owned_worker,
)
from marimo_studio._workspace.models import StudioWorkspace
from marimo_studio.errors import ConfigurationError
from marimo_studio.errors._internal import ViewDeletionInProgress
from marimo_studio.view_providers import (
    BuildProfile,
    ProviderCancellation,
)

_CATALOG_PROBE_INTERVAL = 0.5
_CATALOG_RECONCILIATION_LIMIT = 32


@dataclass(frozen=True)
class _DevelopmentOwners:
    publications: PublicationOwners
    sources: SourceOwners


class DevelopmentCleanupError(RuntimeError):
    """Report release failures after every development owner was attempted."""

    def __init__(self, errors: tuple[Exception, ...]) -> None:
        self.errors = errors
        details = "; ".join(str(error) for error in errors)
        super().__init__(f"Development cleanup failed: {details}")


@dataclass
class _ViewDeletion:
    committed: bool = False

    def commit(self) -> None:
        self.committed = True


class DevelopmentCoordinator:
    """Own shared source polling and publication for one notebook."""

    def __init__(
        self,
        *,
        project_watcher: ProjectWatcherFactory | None = None,
        interval: float = 0.05,
    ) -> None:
        if project_watcher is None:
            from marimo_studio._server.development.watcher import PrivateProjectWatcher

            project_watcher = PrivateProjectWatcher
        self._interval = min(max(interval, 0), 0.1)
        self._lock = asyncio.Lock()
        self._deleting_views: set[str] = set()
        self._closed = False
        self._close_lock = asyncio.Lock()
        self._cleanup_error: DevelopmentCleanupError | None = None
        self._source_monitors = SourceMonitorRegistry(project_watcher)
        self._publications = PublicationRegistry(
            self._lock,
            self._require_view_locked,
        )

    async def subscribe(
        self,
        studio: StudioWorkspace,
        view_name: str | None,
    ) -> SourceSubscription:
        subscription: SourceSubscription | None = None
        creation: _SourceCreation | None = None
        async with self._lock:
            self._require_source_locked(view_name)
            subscription, creation = self._source_monitors.subscribe_locked(
                view_name,
                self,
                lambda control: asyncio.create_task(
                    self._construct_source(studio, view_name, control)
                ),
            )

        if subscription is not None:
            return await self._activate_subscription(subscription)
        assert creation is not None

        try:
            producer = await asyncio.shield(creation.task)
        except BaseException:
            _result, cancellation = await settle_ownership(
                self._release_creation_waiter(view_name, creation)
            )
            propagate_cancellation(cancellation)
            raise

        return await self._claim_source_creation(
            view_name,
            creation,
            producer,
        )

    async def _claim_source_creation(
        self,
        view_name: str | None,
        creation: _SourceCreation,
        producer: SourceChangeProducer,
    ) -> SourceSubscription:
        claimed = False
        try:
            async with self._lock:
                self._require_source_locked(view_name)
                subscription = self._source_monitors.claim_creation_locked(
                    view_name,
                    creation,
                    producer,
                    self,
                )
                claimed = True
                if subscription is None:
                    if view_name is None:
                        raise RuntimeError("Source monitor creation was superseded")
                    raise ViewDeletionInProgress(view_name)
            return await self._activate_subscription(subscription)
        except BaseException:
            if not claimed:
                _result, cancellation = await settle_ownership(
                    self._release_creation_waiter(view_name, creation)
                )
                propagate_cancellation(cancellation)
            raise

    async def _activate_subscription(
        self,
        subscription: SourceSubscription,
    ) -> SourceSubscription:
        try:
            started = await self._start_monitor(
                subscription._key,
                subscription._monitor,
            )
            if not started:
                async with self._lock:
                    self._ensure_open()
                    if subscription._key is not None and (
                        subscription._key in self._deleting_views
                        or not self._source_monitors.contains_locked(
                            subscription._key,
                            subscription._monitor,
                        )
                    ):
                        raise ViewDeletionInProgress(subscription._key)
                raise RuntimeError("Source monitor activation was superseded")
        except BaseException:
            await settle_ownership(
                self._unsubscribe(
                    subscription._key,
                    subscription._monitor,
                    subscription._token,
                )
            )
            raise
        return subscription

    async def _start_monitor(
        self,
        key: str | None,
        monitor: _SourceMonitor,
    ) -> bool:
        async with monitor.activation_lock:
            async with self._lock:
                if not self._monitor_active_locked(key, monitor):
                    return False
                if monitor.task is not None:
                    if not monitor.task.done():
                        return True
                    monitor.task = None
                plan = monitor.producer.watch_plan
            started = await monitor.watcher.replace_if(
                plan,
                lambda path: self._watch_changed(key, monitor, path),
                lambda: self._monitor_active(key, monitor),
            )
            if not started:
                return False
            async with self._lock:
                if self._monitor_active_locked(key, monitor) and monitor.task is None:
                    monitor.task = asyncio.create_task(self._scan_source(key, monitor))
                    return True
            await monitor.watcher.close()
            return False

    async def _monitor_active(
        self,
        key: str | None,
        monitor: _SourceMonitor,
    ) -> bool:
        async with self._lock:
            return self._monitor_active_locked(key, monitor)

    def _monitor_active_locked(
        self,
        key: str | None,
        monitor: _SourceMonitor,
    ) -> bool:
        return (
            not self._closed
            and self._source_monitors.contains_locked(key, monitor)
            and bool(monitor.subscribers)
            and not (key is not None and key in self._deleting_views)
        )

    async def _close_idle_watcher(
        self,
        key: str | None,
        monitor: _SourceMonitor,
    ) -> None:
        async with monitor.activation_lock:
            async with self._lock:
                retained = self._source_monitors.contains_locked(key, monitor)
                if retained and (monitor.subscribers or monitor.task is not None):
                    return
            await monitor.watcher.close()

    async def project_catalog(
        self,
        studio: StudioWorkspace,
        view_name: str,
    ) -> ProjectCatalog:
        """Return one refreshed provider catalog for server project reads."""
        subscription = await self.subscribe(studio, view_name)
        try:
            async with self._lock:
                monitor = self._source_monitors.monitor_locked(view_name)
                if monitor is None:
                    raise RuntimeError("Source monitor disappeared during inspection")
            for _attempt in range(_CATALOG_RECONCILIATION_LIMIT):
                catalog_current = getattr(
                    monitor.producer,
                    "catalog_current",
                    lambda: True,
                )
                if monitor.error is None and await self._catalog_current(
                    monitor,
                    catalog_current,
                ):
                    break
                generation = monitor.generation
                await self._scan_monitor(view_name, monitor)
                if monitor.error is not None or monitor.generation == generation:
                    break
            async with monitor.scan_lock:
                if monitor.error is not None:
                    raise ConfigurationError(
                        "Source monitoring failed for view "
                        f"{view_name!r}: {monitor.error}"
                    ) from monitor.error
                project, inspection, input_id = monitor.producer.catalog()
                async with self._lock:
                    if (
                        view_name in self._deleting_views
                        or not self._source_monitors.contains_locked(
                            view_name,
                            monitor,
                        )
                    ):
                        raise ViewDeletionInProgress(view_name)
                    generation = monitor.generation
            return ProjectCatalog(project, inspection, input_id, generation)
        finally:
            await subscription.close()

    async def retained_provider(self, view_name: str) -> str | None:
        """Return the provider from the monitor's last valid workspace."""
        async with self._lock:
            monitor = self._source_monitors.monitor_locked(view_name)
            if monitor is None:
                return None
            project = monitor.producer.studio.views.get(view_name)
            return project.provider if project is not None else None

    async def _construct_source(
        self,
        studio: StudioWorkspace,
        view_name: str | None,
        control: ProviderCancellation,
    ) -> SourceChangeProducer:
        def construct() -> SourceChangeProducer:
            with provider_cancellation(control):
                return SourceChangeProducer(studio, view_name)

        return await run_owned_worker(control, construct)

    async def _release_creation_waiter(
        self,
        key: str | None,
        creation: _SourceCreation,
    ) -> None:
        cancel = False
        settle = False
        async with self._lock:
            cancel = self._source_monitors.release_creation_waiter_locked(
                key,
                creation,
            )
            settle = creation.waiters == 0
        if cancel:
            creation.control.cancel()
            creation.task.cancel()
        if settle:
            results = await asyncio.gather(creation.task, return_exceptions=True)
            errors = process_cleanup_errors(results)
            if errors:
                raise errors[0]

    async def _poll(
        self,
        key: str | None,
        after: int,
        expected: _SourceMonitor,
    ) -> SourcePoll | None:
        probe = False
        async with self._lock:
            if self._closed:
                return None
            if key is not None and key in self._deleting_views:
                return None
            monitor = self._source_monitors.monitor_locked(key)
            if monitor is None or monitor is not expected:
                return None
            if monitor.journal and after < monitor.journal[0].generation - 1:
                return SourcePoll(
                    monitor.generation,
                    SourceChange("resync", ()),
                )
            pending = next(
                (event for event in monitor.journal if event.generation > after),
                None,
            )
            if pending is not None:
                return pending
            now = monotonic()
            if now - monitor.last_probe >= _CATALOG_PROBE_INTERVAL:
                monitor.last_probe = now
                probe = True
        catalog_current = getattr(monitor.producer, "catalog_current", lambda: True)
        if probe and (
            monitor.error is not None
            or not await self._catalog_current(monitor, catalog_current)
        ):
            await self._scan_monitor(key, monitor)
            async with self._lock:
                if self._closed or not self._source_monitors.contains_locked(
                    key,
                    monitor,
                ):
                    return None
                return next(
                    (event for event in monitor.journal if event.generation > after),
                    None,
                )
        return None

    async def _catalog_current(
        self,
        monitor: _SourceMonitor,
        probe: Callable[[], bool],
    ) -> bool:
        async with monitor.probe_lock:
            task = monitor.probe_task
            if task is None:
                task = asyncio.create_task(asyncio.to_thread(probe))
                monitor.probe_task = task
        try:
            return await asyncio.shield(task)
        finally:
            async with monitor.probe_lock:
                if monitor.probe_task is task and task.done():
                    monitor.probe_task = None

    async def refresh(self, view_name: str) -> None:
        """Refresh one monitor after a caller directly observes changed metadata."""
        while True:
            async with self._lock:
                monitor = self._source_monitors.monitor_locked(view_name)
                if monitor is None or view_name in self._deleting_views:
                    return
            await self._scan_monitor(view_name, monitor)
            async with self._lock:
                if self._source_monitors.monitor_locked(view_name) is monitor:
                    return

    async def _watch_changed(
        self,
        key: str | None,
        expected: _SourceMonitor,
        _path: Path,
    ) -> None:
        async with self._lock:
            if self._closed or not self._source_monitors.contains_locked(
                key,
                expected,
            ):
                return
            expected.changed.set()

    async def _scan_source(
        self,
        key: str | None,
        monitor: _SourceMonitor,
    ) -> None:
        while True:
            await monitor.changed.wait()
            monitor.changed.clear()
            if self._interval > 0:
                await asyncio.sleep(self._interval)
            await self._scan_monitor(key, monitor)

    async def _scan_monitor(
        self,
        key: str | None,
        monitor: _SourceMonitor,
    ) -> None:
        owner = asyncio.current_task()
        if owner is None:
            raise RuntimeError("Source scan has no task owner")
        async with monitor.scan_lock:
            control = ProviderCancellation()
            async with self._lock:
                if self._closed or not self._source_monitors.contains_locked(
                    key,
                    monitor,
                ):
                    return
                monitor.scan_control = control
                monitor.scan_task = owner

            def poll(
                scan_control: ProviderCancellation = control,
            ) -> SourceChange | None:
                with provider_cancellation(scan_control):
                    if monitor.rebuild:
                        monitor.producer = SourceChangeProducer(
                            monitor.producer.studio,
                            key,
                        )
                        monitor.rebuild = False
                        return SourceChange("resync", ())
                    return monitor.producer.poll()

            previous_error = monitor.error
            try:
                change = await run_owned_worker(control, poll)
                recovering = previous_error is not None
                await monitor.watcher.replace_if(
                    monitor.producer.watch_plan,
                    lambda path: self._watch_changed(key, monitor, path),
                    lambda: self._monitor_active(key, monitor),
                )
            except Exception as error:
                raise_process_cleanup(error)
                change = (
                    None
                    if previous_error is not None
                    and type(previous_error) is type(error)
                    and str(previous_error) == str(error)
                    else SourceChange("project", (), error=str(error))
                )
                monitor.error = error
            else:
                monitor.error = None
                if recovering and change is None:
                    change = SourceChange("project", ())
            finally:
                async with self._lock:
                    if monitor.scan_control is control:
                        monitor.scan_control = None
                    if monitor.scan_task is owner:
                        monitor.scan_task = None

            async with self._lock:
                if self._closed or not self._source_monitors.contains_locked(
                    key,
                    monitor,
                ):
                    return
                if change is not None:
                    monitor.generation += 1
                    event = SourcePoll(monitor.generation, change)
                    monitor.journal.append(event)
                    if key is not None and change.kind == "project":
                        self._publications.cancel_superseded_locked(
                            key,
                            monitor.generation,
                        )

    async def _unsubscribe(
        self,
        key: str | None,
        expected: _SourceMonitor,
        token: object,
    ) -> None:
        task: asyncio.Task[None] | None = None
        async with self._lock:
            task = self._source_monitors.remove_subscriber_locked(
                key,
                expected,
                token,
            )
        if task is not None:
            task.cancel()
            results = await asyncio.gather(task, return_exceptions=True)
            errors = process_cleanup_errors(results)
            if errors:
                raise errors[0]
        async with self._lock:
            close_watcher = self._source_monitors.idle_locked(key, expected)
        if close_watcher:
            await self._close_idle_watcher(key, expected)

    async def publish(
        self,
        view_name: str,
        generation: int,
        operation: Callable[[], Any],
        *,
        profile: BuildProfile = "development",
        warmup: bool = False,
    ) -> Any:
        return await self._publications.publish(
            view_name,
            generation,
            operation,
            profile=profile,
            warmup=warmup,
        )

    async def baseline(
        self,
        view_name: str,
        generation: int,
        operation: Callable[[], Any],
    ) -> Any:
        """Coalesce one generation's presentation baseline across subscribers."""
        return await self._publications.baseline(view_name, generation, operation)

    @asynccontextmanager
    async def deleting_view(self, view_name: str) -> AsyncIterator[_ViewDeletion]:
        """Drain view-scoped work while one deletion transaction is active."""
        async with self._lock:
            self._ensure_open()
            if view_name in self._deleting_views:
                raise ViewDeletionInProgress(view_name)
            self._deleting_views.add(view_name)
            source_owners = self._source_monitors.begin_view_deletion_locked(view_name)
            publication_owners = self._publications.begin_view_deletion_locked(
                view_name
            )
        deletion = _ViewDeletion()
        try:
            tasks: list[asyncio.Future[Any]] = []
            creation = source_owners.creation
            monitor = source_owners.monitor
            if creation is not None:
                creation.control.cancel()
                creation.task.cancel()
                tasks.append(creation.task)
            if monitor is not None:
                monitor.rebuild = True
                if monitor.scan_control is not None:
                    monitor.scan_control.cancel()
                    monitor.scan_control = None
                for task in (monitor.task, monitor.scan_task):
                    if task is not None and all(owner is not task for owner in tasks):
                        task.cancel()
                        tasks.append(task)
                monitor.task = None
                monitor.scan_task = None
            tasks.extend(publication_owners.tasks)
            if tasks:
                completed = asyncio.gather(*tasks, return_exceptions=True)
                try:
                    results = await asyncio.shield(completed)
                except asyncio.CancelledError as cancellation:
                    await drain_future(completed)
                    errors = process_cleanup_errors(completed.result())
                    if errors:
                        raise errors[0] from cancellation
                    raise
                errors = process_cleanup_errors(results)
                if errors:
                    raise errors[0]
            yield deletion
            deletion.commit()
        finally:
            _result, cancellation = await settle_ownership(
                self._finish_view_deletion(
                    view_name,
                    deletion,
                    source_owners,
                    publication_owners,
                )
            )
            propagate_cancellation(cancellation)

    async def _finish_view_deletion(
        self,
        view_name: str,
        deletion: _ViewDeletion,
        source_owners: ViewSourceOwners,
        publication_owners: ViewPublicationOwners,
    ) -> None:
        monitor = source_owners.monitor
        close_monitor = False
        restart_monitor = False
        async with self._lock:
            self._publications.finish_view_deletion_locked(
                view_name,
                publication_owners,
                committed=deletion.committed,
            )
            self._deleting_views.discard(view_name)
            close_monitor = self._source_monitors.finish_view_deletion_locked(
                view_name,
                monitor,
                committed=deletion.committed,
            )
            if (
                not deletion.committed
                and not self._closed
                and monitor is not None
                and self._source_monitors.contains_locked(view_name, monitor)
                and monitor.subscribers
                and monitor.task is None
            ):
                restart_monitor = True
        if close_monitor and monitor is not None:
            await self._close_idle_watcher(view_name, monitor)
        elif restart_monitor and monitor is not None:
            await self._start_monitor(view_name, monitor)

    def _ensure_open(self) -> None:
        if self._closed:
            raise RuntimeError("The development coordinator is closed")

    def _require_source_locked(self, view_name: str | None) -> None:
        self._ensure_open()
        if view_name is not None and view_name in self._deleting_views:
            raise ViewDeletionInProgress(view_name)

    def _require_view_locked(self, view_name: str) -> None:
        self._require_source_locked(view_name)

    async def close(self) -> None:
        async with self._close_lock:
            owners = await self._begin_close()
            if owners is None:
                if self._cleanup_error is not None:
                    raise self._cleanup_error
                return
            cleanup = asyncio.create_task(self._release_owners(owners))
            cancelled: asyncio.CancelledError | None = None
            try:
                errors = await asyncio.shield(cleanup)
            except asyncio.CancelledError as error:
                cancelled = error
                await drain_future(cleanup)
                errors = cleanup.result()
            _result, finish_cancellation = await settle_ownership(
                self._finish_close(errors)
            )
            if cancelled is None:
                cancelled = finish_cancellation
            if cancelled is not None:
                raise cancelled
            if self._cleanup_error is not None:
                raise self._cleanup_error

    async def _begin_close(self) -> _DevelopmentOwners | None:
        async with self._lock:
            if self._closed:
                return None
            self._closed = True
            owners = _DevelopmentOwners(
                publications=self._publications.begin_close_locked(),
                sources=self._source_monitors.begin_close_locked(),
            )
            for creation in owners.sources.creations:
                creation.control.cancel()
            for monitor in owners.sources.monitors:
                if monitor.scan_control is not None:
                    monitor.scan_control.cancel()
            return owners

    async def _release_owners(
        self,
        owners: _DevelopmentOwners,
    ) -> tuple[Exception, ...]:
        errors: list[Exception] = []
        for creation in owners.sources.creations:
            creation.task.cancel()
        for monitor in owners.sources.monitors:
            try:
                await monitor.watcher.close()
            except Exception as error:
                errors.append(error)

        monitor_tasks: list[asyncio.Task[Any]] = []
        for monitor in owners.sources.monitors:
            for task in (monitor.task, monitor.scan_task):
                if task is not None and all(
                    owner is not task for owner in monitor_tasks
                ):
                    task.cancel()
                    monitor_tasks.append(task)
        source_results = await asyncio.gather(
            *(creation.task for creation in owners.sources.creations),
            *monitor_tasks,
            *(
                monitor.probe_task
                for monitor in owners.sources.monitors
                if monitor.probe_task is not None
            ),
            return_exceptions=True,
        )
        errors.extend(process_cleanup_errors(source_results))
        errors.extend(await self._publications.release(owners.publications))
        return tuple(errors)

    async def _finish_close(self, errors: tuple[Exception, ...]) -> None:
        async with self._lock:
            self._source_monitors.clear_locked()
            self._publications.clear_locked()
            self._deleting_views.clear()
            if errors:
                self._cleanup_error = DevelopmentCleanupError(errors)
