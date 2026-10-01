from __future__ import annotations

import asyncio
import threading
from collections.abc import (
    AsyncGenerator,
    AsyncIterator,
    Callable,
    Coroutine,
    Iterator,
)
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path
from typing import Any, cast

import pytest

import marimo_studio._server.studio.retirement as retirement_service
import marimo_studio._workspace.mutation_lock as mutation_locks
from marimo_studio._server.development.coordinator import DevelopmentCoordinator
from marimo_studio._server.presentation.service import NotebookPresentation
from marimo_studio._views.api import prepare_view
from marimo_studio._views.sources import read_source
from marimo_studio._workspace import load_studio
from marimo_studio._workspace.models import StudioWorkspace
from marimo_studio._workspace.ownership import PresentViewOwner
from marimo_studio.errors import (
    LastViewError,
    ViewDeletionError,
    WorkspaceGenerationConflictError,
)
from marimo_studio.errors._internal import ViewRetirementCapacityError


async def _wait_for_event(event: threading.Event) -> None:
    while not event.is_set():
        await asyncio.sleep(0)


class _Development:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    @asynccontextmanager
    async def retiring_view(self, view_name: str) -> AsyncIterator[None]:
        self.events.append(f"development-enter:{view_name}")
        try:
            yield
        finally:
            self.events.append(f"development-exit:{view_name}")


class _Presentation:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    @contextmanager
    def retiring_view(self, view_name: str) -> Iterator[Callable[[], None]]:
        released = False

        def release() -> None:
            nonlocal released
            released = True
            self.events.append(f"presentation-enter:{view_name}")

        try:
            yield release
        finally:
            if released:
                self.events.append(f"presentation-exit:{view_name}")


def _owner(studio: StudioWorkspace, name: str) -> PresentViewOwner:
    return PresentViewOwner(studio.catalog_generation, studio.view_generations[name])


def _admit(_current: StudioWorkspace) -> None:
    pass


def _retire(
    studio: StudioWorkspace,
    events: list[str],
    *,
    admit: Callable[[StudioWorkspace], None] = _admit,
    commit: Callable[[StudioWorkspace], retirement_service.RetiredView] | None = None,
    owner: PresentViewOwner | None = None,
) -> Coroutine[Any, Any, retirement_service.RetiredView]:
    return retirement_service.retire_owned_view(
        studio,
        "dashboard",
        owner=owner or _owner(studio, "dashboard"),
        admit=admit,
        commit=commit or (lambda _current: retirement_service.RetiredView(studio)),
        presentation=cast(NotebookPresentation, _Presentation(events)),
        development=cast(DevelopmentCoordinator, _Development(events)),
    )


def _busy_default_executor() -> tuple[ThreadPoolExecutor, threading.Event]:
    release = threading.Event()
    executor = ThreadPoolExecutor(max_workers=1)
    occupied = threading.Event()

    def occupy() -> None:
        occupied.set()
        assert release.wait(timeout=5)

    asyncio.get_running_loop().set_default_executor(executor)
    executor.submit(occupy)
    assert occupied.wait(timeout=1)
    return executor, release


_TEARDOWN = [
    "development-enter:dashboard",
    "presentation-enter:dashboard",
    "presentation-exit:dashboard",
    "development-exit:dashboard",
]


def test_retirement_admits_a_snapshot_before_acquiring_its_build_lock(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepare_view(notebook_path)
    prepare_view(notebook_path, "executive")
    studio = load_studio(notebook_path)
    presentation = NotebookPresentation(notebook_path)
    snapshot_held = threading.Event()
    retirement_waiting = threading.Event()
    snapshot_admitted = threading.Event()
    retiring_view = presentation.retiring_view

    @contextmanager
    def observe_retirement(name: str):
        retirement_waiting.set()
        with retiring_view(name) as release:
            yield release

    monkeypatch.setattr(presentation, "retiring_view", observe_retirement)

    def snapshot_owner() -> None:
        with presentation._coordination_lock("dashboard"):
            snapshot_held.set()
            assert retirement_waiting.wait(timeout=5)
            # A nonblocking attempt exposes the lock cycle and lets both owners settle.
            with mutation_locks._mutation_lock(
                studio.view_root, "dashboard.build.lock", blocking=False
            ) as acquired:
                if acquired:
                    snapshot_admitted.set()

    snapshot = threading.Thread(target=snapshot_owner)
    snapshot.start()

    async def exercise() -> None:
        assert await asyncio.to_thread(snapshot_held.wait, 5)
        result = await retirement_service.delete_owned_view(
            studio,
            "dashboard",
            owner=_owner(studio, "dashboard"),
            presentation=presentation,
            development=cast(DevelopmentCoordinator, _Development([])),
        )
        assert tuple(result.workspace.views) == ("executive",)

    try:
        asyncio.run(exercise())
    finally:
        retirement_waiting.set()
        snapshot.join(timeout=5)
        presentation.close()
    assert not snapshot.is_alive()
    assert snapshot_admitted.is_set()


def test_retirement_drains_development_while_other_sources_remain_available(
    notebook_path: Path,
) -> None:
    prepare_view(notebook_path)
    prepare_view(notebook_path, "executive")
    studio = load_studio(notebook_path)
    events: list[str] = []

    async def exercise() -> None:
        draining = asyncio.Event()
        release = asyncio.Event()

        class Development:
            @asynccontextmanager
            async def retiring_view(self, _name: str) -> AsyncGenerator[None, None]:
                draining.set()
                await release.wait()
                yield

        retirement = asyncio.create_task(
            retirement_service.delete_owned_view(
                studio,
                "dashboard",
                owner=_owner(studio, "dashboard"),
                presentation=cast(NotebookPresentation, _Presentation(events)),
                development=cast(DevelopmentCoordinator, Development()),
            )
        )
        try:
            await asyncio.wait_for(draining.wait(), timeout=5)
            document = await asyncio.wait_for(
                asyncio.to_thread(read_source, studio, "executive", "index.html"),
                timeout=2,
            )
            assert document.content
        finally:
            release.set()
            result = await retirement
        assert tuple(result.workspace.views) == ("executive",)

    asyncio.run(exercise())


def test_catalog_change_during_retirement_drain_preserves_presentation(
    notebook_path: Path,
) -> None:
    prepare_view(notebook_path)
    prepare_view(notebook_path, "executive")
    studio = load_studio(notebook_path)
    events: list[str] = []
    presentation = NotebookPresentation(notebook_path)
    retained = presentation.snapshot("dashboard")

    class Development:
        @asynccontextmanager
        async def retiring_view(self, _name: str) -> AsyncGenerator[None, None]:
            await asyncio.to_thread(prepare_view, notebook_path, "operations")
            try:
                yield
            except WorkspaceGenerationConflictError:
                events.append("development-rollback")
                raise

    async def exercise() -> None:
        with pytest.raises(WorkspaceGenerationConflictError):
            await retirement_service.delete_owned_view(
                studio,
                "dashboard",
                owner=_owner(studio, "dashboard"),
                presentation=presentation,
                development=cast(DevelopmentCoordinator, Development()),
            )

    try:
        asyncio.run(exercise())
        assert (
            presentation.snapshot_for_revision("dashboard", retained.revision)
            is retained
        )
    finally:
        presentation.close()

    assert events == ["development-rollback"]
    assert set(load_studio(notebook_path).views) == {
        "dashboard",
        "executive",
        "operations",
    }


@pytest.mark.parametrize("change", ["remove", "rename"])
def test_retirement_uses_dedicated_threads_when_the_default_executor_is_busy(
    notebook_path: Path,
    change: str,
) -> None:
    prepare_view(notebook_path)
    prepare_view(notebook_path, "executive")
    studio = load_studio(notebook_path)
    events: list[str] = []

    async def exercise() -> retirement_service.RetiredView:
        owner = _owner(studio, "executive")
        presentation = cast(NotebookPresentation, _Presentation(events))
        development = cast(DevelopmentCoordinator, _Development(events))
        executor, release = _busy_default_executor()
        try:
            if change == "remove":
                retirement = retirement_service.delete_owned_view(
                    studio,
                    "executive",
                    owner=owner,
                    presentation=presentation,
                    development=development,
                )
            else:
                retirement = retirement_service.rename_owned_view(
                    studio,
                    "executive",
                    "operations",
                    owner=owner,
                    presentation=presentation,
                    development=development,
                )
            return await asyncio.wait_for(retirement, timeout=5)
        finally:
            release.set()
            executor.shutdown(wait=True)

    retired = asyncio.run(exercise())

    assert "executive" not in retired.workspace.views
    assert events == [event.replace("dashboard", "executive") for event in _TEARDOWN]


def test_retirement_capacity_rejects_without_starting_an_unbounded_thread(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepare_view(notebook_path)
    studio = load_studio(notebook_path)
    admission_started = threading.Event()
    release_admission = threading.Event()

    def blocking_admit(_current: StudioWorkspace) -> None:
        if not admission_started.is_set():
            admission_started.set()
            assert release_admission.wait(timeout=2)

    monkeypatch.setattr(
        retirement_service,
        "_RETIREMENT_SLOTS",
        threading.BoundedSemaphore(1),
    )

    async def exercise() -> None:
        first = asyncio.create_task(_retire(studio, [], admit=blocking_admit))
        await asyncio.wait_for(_wait_for_event(admission_started), timeout=1)
        try:
            with pytest.raises(ViewRetirementCapacityError) as captured:
                await _retire(studio, [])
            assert captured.value.status_code == 503
            assert captured.value.transient is True
        finally:
            release_admission.set()
        assert (await first).workspace is studio
        assert (await _retire(studio, [])).workspace is studio

    try:
        asyncio.run(exercise())
    finally:
        release_admission.set()


def test_thread_start_failure_releases_retirement_capacity(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepare_view(notebook_path)
    studio = load_studio(notebook_path)
    start = threading.Thread.start
    starts = 0

    def start_after_failure(thread: threading.Thread) -> None:
        nonlocal starts
        starts += 1
        if starts == 1:
            raise RuntimeError("simulated thread start failure")
        start(thread)

    monkeypatch.setattr(
        retirement_service,
        "_RETIREMENT_SLOTS",
        threading.BoundedSemaphore(1),
    )
    monkeypatch.setattr(threading.Thread, "start", start_after_failure)

    async def exercise() -> None:
        with pytest.raises(RuntimeError, match="thread start failure"):
            await _retire(studio, [])
        assert (await _retire(studio, [])).workspace is studio

    asyncio.run(exercise())


def test_cancelled_retirement_drains_the_owned_thread_before_propagating(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepare_view(notebook_path)
    studio = load_studio(notebook_path)
    events: list[str] = []
    started = threading.Event()
    release = threading.Event()
    committed = threading.Event()
    slots = threading.BoundedSemaphore(1)

    def commit(_current: StudioWorkspace) -> retirement_service.RetiredView:
        started.set()
        assert release.wait(timeout=2)
        committed.set()
        return retirement_service.RetiredView(studio)

    monkeypatch.setattr(retirement_service, "_RETIREMENT_SLOTS", slots)

    async def exercise() -> None:
        retirement = asyncio.create_task(_retire(studio, events, commit=commit))
        await asyncio.wait_for(_wait_for_event(started), timeout=1)
        retirement.cancel()
        await asyncio.sleep(0)
        retirement.cancel()
        await asyncio.sleep(0)
        assert not retirement.done()

        release.set()
        with pytest.raises(asyncio.CancelledError):
            await retirement

    try:
        asyncio.run(exercise())
    finally:
        release.set()

    assert committed.is_set()
    assert events == _TEARDOWN
    assert slots.acquire(blocking=False)
    slots.release()


def test_cancelled_retirement_finishes_admission_before_teardown(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepare_view(notebook_path)
    studio = load_studio(notebook_path)
    events: list[str] = []
    admission_started = threading.Event()
    release_admission = threading.Event()
    committed = threading.Event()
    slots = threading.BoundedSemaphore(1)

    def admit(_current: StudioWorkspace) -> None:
        admission_started.set()
        assert release_admission.wait(timeout=2)

    def commit(_current: StudioWorkspace) -> retirement_service.RetiredView:
        committed.set()
        return retirement_service.RetiredView(studio)

    monkeypatch.setattr(retirement_service, "_RETIREMENT_SLOTS", slots)

    async def exercise() -> None:
        retirement = asyncio.create_task(
            _retire(studio, events, admit=admit, commit=commit)
        )
        await asyncio.wait_for(_wait_for_event(admission_started), timeout=1)
        retirement.cancel()
        await asyncio.sleep(0)
        retirement.cancel()
        await asyncio.sleep(0)
        assert not retirement.done()
        assert events == []

        release_admission.set()
        with pytest.raises(asyncio.CancelledError):
            await retirement

    try:
        asyncio.run(exercise())
    finally:
        release_admission.set()

    assert committed.is_set()
    assert events == _TEARDOWN
    assert slots.acquire(blocking=False)
    slots.release()


def test_committed_cleanup_warning_does_not_use_the_default_executor(
    notebook_path: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepare_view(notebook_path)
    prepare_view(notebook_path, "executive")
    studio = load_studio(notebook_path)
    events: list[str] = []
    cleanup = tmp_path / "retained-cleanup"

    def remove(*_args: Any, **_kwargs: Any) -> StudioWorkspace:
        raise ViewDeletionError(cleanup, committed_workspace=studio)

    monkeypatch.setattr(retirement_service, "delete_view", remove)

    async def exercise() -> retirement_service.RetiredView:
        executor, release = _busy_default_executor()
        try:
            return await asyncio.wait_for(
                retirement_service.delete_owned_view(
                    studio,
                    "dashboard",
                    owner=_owner(studio, "dashboard"),
                    presentation=cast(NotebookPresentation, _Presentation(events)),
                    development=cast(DevelopmentCoordinator, _Development(events)),
                ),
                timeout=5,
            )
        finally:
            release.set()
            executor.shutdown(wait=True)

    retired = asyncio.run(exercise())

    assert retired.workspace is studio
    assert retired.cleanup == cleanup
    assert events == _TEARDOWN


@pytest.mark.parametrize("rejection", ["stale-owner", "admission"])
def test_rejected_retirement_fails_before_server_teardown(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    rejection: str,
) -> None:
    prepare_view(notebook_path)
    studio = load_studio(notebook_path)
    events: list[str] = []
    slots = threading.BoundedSemaphore(1)

    def reject(_current: StudioWorkspace) -> None:
        raise LastViewError()

    def unexpected_commit(_current: StudioWorkspace) -> retirement_service.RetiredView:
        raise AssertionError("a rejected retirement reached the project mutation")

    monkeypatch.setattr(retirement_service, "_RETIREMENT_SLOTS", slots)

    async def exercise() -> None:
        with pytest.raises((WorkspaceGenerationConflictError, LastViewError)):
            if rejection == "stale-owner":
                await _retire(
                    studio,
                    events,
                    owner=PresentViewOwner(
                        "0" * 64, studio.view_generations["dashboard"]
                    ),
                    commit=unexpected_commit,
                )
            else:
                await _retire(studio, events, admit=reject, commit=unexpected_commit)

    asyncio.run(exercise())

    assert events == []
    assert slots.acquire(blocking=False)
    slots.release()
