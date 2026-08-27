"""Own development publication and presentation-baseline work."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from marimo_studio._processes.cancellation import provider_cancellation
from marimo_studio._processes.ownership import (
    propagate_cancellation,
    settle_ownership,
)
from marimo_studio._processes.provider_operation import process_cleanup_errors
from marimo_studio._processes.supervisor import ProcessCleanupError
from marimo_studio._server.development.task_ownership import run_owned_worker
from marimo_studio.view_providers import BuildProfile, ProviderCancellation

_INACTIVE_PUBLICATION_LIMIT = 2
_PublicationKey = tuple[str, int, BuildProfile]
_BaselineKey = tuple[str, int]


@dataclass
class _PublicationAdmission:
    foreground: bool
    cancelled: bool = False
    claimed: bool = False


@dataclass
class _Publication:
    control: ProviderCancellation
    task: asyncio.Task[Any]
    admission: _PublicationAdmission
    waiters: int = 0
    waiter_releases: set[asyncio.Future[None]] = field(default_factory=set)


@dataclass
class _Baseline:
    control: ProviderCancellation
    task: asyncio.Task[Any]
    waiters: int = 0
    waiter_releases: set[asyncio.Future[None]] = field(default_factory=set)


@dataclass(frozen=True)
class PublicationOwners:
    publications: tuple[_Publication, ...]
    baselines: tuple[_Baseline, ...]


@dataclass(frozen=True)
class ViewPublicationOwners:
    publications: tuple[tuple[_PublicationKey, _Publication], ...]
    baselines: tuple[tuple[_BaselineKey, _Baseline], ...]

    @property
    def tasks(self) -> tuple[asyncio.Future[Any], ...]:
        return (
            *(publication.task for _key, publication in self.publications),
            *(baseline.task for _key, baseline in self.baselines),
            *(
                release
                for _key, publication in self.publications
                for release in publication.waiter_releases
            ),
            *(
                release
                for _key, baseline in self.baselines
                for release in baseline.waiter_releases
            ),
        )


class PublicationRegistry:
    """Coalesce, admit, cancel, and release generation-scoped publications."""

    def __init__(
        self,
        lock: asyncio.Lock,
        require_view: Callable[[str], None],
    ) -> None:
        self._lock = lock
        self._require_view = require_view
        self._inactive_condition = asyncio.Condition(lock)
        self._inactive_active = 0
        self._publications: dict[_PublicationKey, _Publication] = {}
        self._baselines: dict[_BaselineKey, _Baseline] = {}

    async def publish(
        self,
        view_name: str,
        generation: int,
        operation: Callable[[], Any],
        *,
        profile: BuildProfile = "development",
        warmup: bool = False,
    ) -> Any:
        key = (view_name, generation, profile)
        release = asyncio.get_running_loop().create_future()
        while True:
            draining: asyncio.Task[Any] | None = None
            async with self._lock:
                self._require_view(view_name)
                publication = self._publications.get(key)
                if (
                    publication is not None
                    and not publication.task.done()
                    and not warmup
                    and publication.admission.cancelled
                ):
                    draining = publication.task
                elif publication is None or publication.task.done():
                    control = ProviderCancellation()
                    admission = _PublicationAdmission(foreground=not warmup)
                    task = asyncio.create_task(
                        self._run(control, operation, admission),
                    )
                    publication = _Publication(control, task, admission)
                    self._publications[key] = publication
                    self._prune_publications(view_name, generation)
                    if not warmup:
                        self._preempt_warmups(publication)
                elif not warmup and not publication.admission.foreground:
                    publication.admission.foreground = True
                    self._inactive_condition.notify_all()
                    self._preempt_warmups(publication)
                if draining is None:
                    publication.waiters += 1
                    publication.waiter_releases.add(release)
            if draining is None:
                break
            results = await asyncio.shield(
                asyncio.gather(draining, return_exceptions=True)
            )
            errors = process_cleanup_errors(results)
            if errors:
                raise errors[0]
        try:
            return await asyncio.shield(publication.task)
        finally:
            try:
                _result, cancellation = await settle_ownership(
                    self._release_publication_waiter(key, publication, release)
                )
            finally:
                if not release.done():
                    release.set_result(None)
            propagate_cancellation(cancellation)

    async def baseline(
        self,
        view_name: str,
        generation: int,
        operation: Callable[[], Any],
    ) -> Any:
        key = (view_name, generation)
        release = asyncio.get_running_loop().create_future()
        async with self._lock:
            self._require_view(view_name)
            baseline = self._baselines.get(key)
            if baseline is None or baseline.task.done():
                control = ProviderCancellation()
                task = asyncio.create_task(self._run(control, operation))
                baseline = _Baseline(control, task)
                self._baselines[key] = baseline
                self._prune_baselines(view_name, generation)
            baseline.waiters += 1
            baseline.waiter_releases.add(release)
        try:
            return await asyncio.shield(baseline.task)
        finally:
            try:
                _result, cancellation = await settle_ownership(
                    self._release_baseline_waiter(key, baseline, release)
                )
            finally:
                if not release.done():
                    release.set_result(None)
            propagate_cancellation(cancellation)

    def cancel_superseded_locked(self, view_name: str, generation: int) -> None:
        for (published_view, published_generation, _profile), publication in tuple(
            self._publications.items()
        ):
            if (
                published_view == view_name
                and published_generation < generation
                and not publication.task.done()
            ):
                self._cancel_publication(publication)
        for (baseline_view, baseline_generation), baseline in tuple(
            self._baselines.items()
        ):
            if (
                baseline_view == view_name
                and baseline_generation < generation
                and not baseline.task.done()
            ):
                baseline.control.cancel()

    def begin_view_deletion_locked(self, view_name: str) -> ViewPublicationOwners:
        owners = ViewPublicationOwners(
            tuple(
                (key, publication)
                for key, publication in self._publications.items()
                if key[0] == view_name and not publication.task.done()
            ),
            tuple(
                (key, baseline)
                for key, baseline in self._baselines.items()
                if key[0] == view_name and not baseline.task.done()
            ),
        )
        for _key, publication in owners.publications:
            self._cancel_publication(publication)
        for _key, baseline in owners.baselines:
            baseline.control.cancel()
            baseline.task.cancel()
        return owners

    def finish_view_deletion_locked(
        self,
        view_name: str,
        owners: ViewPublicationOwners,
        *,
        committed: bool,
    ) -> None:
        for key, publication in owners.publications:
            if self._publications.get(key) is publication and publication.task.done():
                self._publications.pop(key, None)
        for key, baseline in owners.baselines:
            if self._baselines.get(key) is baseline and baseline.task.done():
                self._baselines.pop(key, None)
        if committed:
            for key in tuple(self._publications):
                if key[0] == view_name:
                    self._publications.pop(key, None)
            for key in tuple(self._baselines):
                if key[0] == view_name:
                    self._baselines.pop(key, None)

    def begin_close_locked(self) -> PublicationOwners:
        owners = PublicationOwners(
            tuple(self._publications.values()),
            tuple(self._baselines.values()),
        )
        for publication in owners.publications:
            self._cancel_publication(publication)
        for baseline in owners.baselines:
            baseline.control.cancel()
        return owners

    async def release(
        self,
        owners: PublicationOwners,
    ) -> tuple[ProcessCleanupError, ...]:
        tasks = (
            *(publication.task for publication in owners.publications),
            *(baseline.task for baseline in owners.baselines),
        )
        waiters = (
            *(
                release
                for publication in owners.publications
                for release in publication.waiter_releases
                if not release.done()
            ),
            *(
                release
                for baseline in owners.baselines
                for release in baseline.waiter_releases
                if not release.done()
            ),
        )
        results: list[object] = []
        if tasks:
            _done, pending = await asyncio.wait(tasks, timeout=5)
            for task in pending:
                task.cancel()
            results.extend(await asyncio.gather(*tasks, return_exceptions=True))
        if waiters:
            results.extend(await asyncio.gather(*waiters, return_exceptions=True))
        return process_cleanup_errors(results)

    def clear_locked(self) -> None:
        self._publications.clear()
        self._baselines.clear()

    async def _run(
        self,
        control: ProviderCancellation,
        operation: Callable[[], Any],
        admission: _PublicationAdmission | None = None,
    ) -> Any:
        def run() -> Any:
            with provider_cancellation(control):
                return operation()

        claimed = admission is not None and await self._claim_slot(admission)
        try:
            return await run_owned_worker(control, run)
        finally:
            if claimed:
                await self._release_slot()

    async def _claim_slot(self, admission: _PublicationAdmission) -> bool:
        async with self._inactive_condition:
            while (
                self._inactive_active >= _INACTIVE_PUBLICATION_LIMIT
                and not admission.foreground
                and not admission.cancelled
            ):
                await self._inactive_condition.wait()
            if admission.cancelled:
                raise asyncio.CancelledError
            if admission.foreground:
                admission.claimed = True
                return False
            self._inactive_active += 1
            admission.claimed = True
            return True

    async def _release_slot(self) -> None:
        async with self._inactive_condition:
            self._inactive_active -= 1
            self._inactive_condition.notify_all()

    async def _release_baseline_waiter(
        self,
        key: tuple[str, int],
        baseline: _Baseline,
        release: asyncio.Future[None],
    ) -> None:
        settle = False
        async with self._lock:
            baseline.waiters -= 1
            baseline.waiter_releases.discard(release)
            if baseline.waiters == 0:
                settle = True
                if self._baselines.get(key) is baseline:
                    self._baselines.pop(key, None)
                if not baseline.task.done():
                    baseline.control.cancel()
                    baseline.task.cancel()
        if settle:
            results = await asyncio.gather(baseline.task, return_exceptions=True)
            errors = process_cleanup_errors(results)
            if errors:
                raise errors[0]

    async def _release_publication_waiter(
        self,
        key: _PublicationKey,
        publication: _Publication,
        release: asyncio.Future[None],
    ) -> None:
        settle = False
        async with self._lock:
            publication.waiters -= 1
            publication.waiter_releases.discard(release)
            if publication.waiters == 0:
                settle = True
                if self._publications.get(key) is publication:
                    self._publications.pop(key, None)
                if not publication.task.done():
                    self._cancel_publication(publication)
                    publication.task.cancel()
        if settle:
            results = await asyncio.gather(publication.task, return_exceptions=True)
            errors = process_cleanup_errors(results)
            if errors:
                raise errors[0]

    def _prune_publications(self, view_name: str, generation: int) -> None:
        for key, publication in tuple(self._publications.items()):
            if key[0] == view_name and key[1] < generation and publication.task.done():
                self._publications.pop(key, None)

    def _prune_baselines(self, view_name: str, generation: int) -> None:
        for key, baseline in tuple(self._baselines.items()):
            if key[0] == view_name and key[1] < generation and baseline.task.done():
                self._baselines.pop(key, None)

    def _cancel_publication(self, publication: _Publication) -> None:
        publication.control.cancel()
        publication.admission.cancelled = True
        if not publication.admission.claimed:
            publication.task.cancel()
        self._inactive_condition.notify_all()

    def _preempt_warmups(self, selected: _Publication) -> None:
        for publication in self._publications.values():
            if (
                publication is not selected
                and not publication.task.done()
                and not publication.admission.foreground
            ):
                self._cancel_publication(publication)
