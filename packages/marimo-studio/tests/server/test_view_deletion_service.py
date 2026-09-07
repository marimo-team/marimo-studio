from __future__ import annotations

import asyncio
import threading
from collections.abc import AsyncGenerator, AsyncIterator, Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path
from typing import Any, cast

import pytest

import marimo_studio._server.studio.deletion as deletion_service
import marimo_studio._workspace.mutation_lock as mutation_locks
from marimo_studio._server.development.coordinator import DevelopmentCoordinator
from marimo_studio._server.presentation.service import NotebookPresentation
from marimo_studio._views.api import prepare_view
from marimo_studio._views.sources import read_source
from marimo_studio._workspace import load_studio
from marimo_studio._workspace.models import StudioWorkspace
from marimo_studio.errors import ViewDeletionError, WorkspaceGenerationConflictError
from marimo_studio.errors._internal import ViewDeletionCapacityError


async def _wait_for_event(event: threading.Event) -> None:
    while not event.is_set():
        await asyncio.sleep(0)


class _Development:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    @asynccontextmanager
    async def deleting_view(self, view_name: str) -> AsyncIterator[None]:
        self.events.append(f"development-enter:{view_name}")
        try:
            yield
        finally:
            self.events.append(f"development-exit:{view_name}")


class _Presentation:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    @contextmanager
    def deleting_view(self, view_name: str) -> Iterator[Callable[[], None]]:
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


def _owners(studio: StudioWorkspace, name: str) -> tuple[str, str]:
    return studio.catalog_generation, studio.view_generations[name]


def test_deletion_admits_a_snapshot_before_acquiring_its_build_lock(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepare_view(notebook_path)
    prepare_view(notebook_path, "executive")
    studio = load_studio(notebook_path)
    presentation = NotebookPresentation(notebook_path)
    snapshot_held = threading.Event()
    deletion_waiting = threading.Event()
    snapshot_admitted = threading.Event()
    deleting_view = presentation.deleting_view

    @contextmanager
    def observe_deletion(name: str):
        deletion_waiting.set()
        with deleting_view(name) as release:
            yield release

    monkeypatch.setattr(presentation, "deleting_view", observe_deletion)

    def snapshot_owner() -> None:
        with presentation._coordination_lock("dashboard"):
            snapshot_held.set()
            assert deletion_waiting.wait(timeout=5)
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
        catalog_generation, view_generation = _owners(studio, "dashboard")
        result = await deletion_service.delete_owned_view(
            studio,
            "dashboard",
            expected_catalog_generation=catalog_generation,
            expected_generation=view_generation,
            presentation=presentation,
            development=cast(DevelopmentCoordinator, _Development([])),
        )
        assert tuple(result.workspace.views) == ("executive",)

    try:
        asyncio.run(exercise())
    finally:
        deletion_waiting.set()
        snapshot.join(timeout=5)
        presentation.close()
    assert not snapshot.is_alive()
    assert snapshot_admitted.is_set()


def test_deletion_drains_development_while_other_sources_remain_available(
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
            async def deleting_view(self, _name: str) -> AsyncGenerator[None, None]:
                draining.set()
                await release.wait()
                yield

        catalog_generation, view_generation = _owners(studio, "dashboard")
        deletion = asyncio.create_task(
            deletion_service.delete_owned_view(
                studio,
                "dashboard",
                expected_catalog_generation=catalog_generation,
                expected_generation=view_generation,
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
            result = await deletion
        assert tuple(result.workspace.views) == ("executive",)

    asyncio.run(exercise())


def test_catalog_change_during_deletion_drain_preserves_presentation(
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
        async def deleting_view(self, _name: str) -> AsyncGenerator[None, None]:
            await asyncio.to_thread(prepare_view, notebook_path, "operations")
            try:
                yield
            except WorkspaceGenerationConflictError:
                events.append("development-rollback")
                raise

    async def exercise() -> None:
        catalog_generation, view_generation = _owners(studio, "dashboard")
        with pytest.raises(WorkspaceGenerationConflictError):
            await deletion_service.delete_owned_view(
                studio,
                "dashboard",
                expected_catalog_generation=catalog_generation,
                expected_generation=view_generation,
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


def test_deletion_uses_a_dedicated_thread_when_the_default_executor_is_busy(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepare_view(notebook_path)
    studio = load_studio(notebook_path)
    events: list[str] = []
    deletion_threads: list[int] = []
    occupied = threading.Event()
    release = threading.Event()

    def occupy_default_executor() -> None:
        occupied.set()
        assert release.wait(timeout=2)

    def validate(*_args: Any, **_kwargs: Any) -> StudioWorkspace:
        return studio

    def remove(*_args: Any, **_kwargs: Any) -> StudioWorkspace:
        deletion_threads.append(threading.get_ident())
        return studio

    monkeypatch.setattr(deletion_service, "validate_view_deletion_owner", validate)
    monkeypatch.setattr(deletion_service, "delete_view", remove)

    async def exercise() -> None:
        loop = asyncio.get_running_loop()
        event_loop_thread = threading.get_ident()
        executor = ThreadPoolExecutor(max_workers=1)
        loop.set_default_executor(executor)
        blocker = loop.run_in_executor(None, occupy_default_executor)
        try:
            await asyncio.wait_for(_wait_for_event(occupied), timeout=1)
            catalog_generation, view_generation = _owners(studio, "dashboard")
            result = await asyncio.wait_for(
                deletion_service.delete_owned_view(
                    studio,
                    "dashboard",
                    expected_catalog_generation=catalog_generation,
                    expected_generation=view_generation,
                    presentation=cast(
                        NotebookPresentation,
                        _Presentation(events),
                    ),
                    development=cast(
                        DevelopmentCoordinator,
                        _Development(events),
                    ),
                ),
                timeout=1,
            )
            assert result.workspace is studio
            assert deletion_threads and deletion_threads[0] != event_loop_thread
        finally:
            release.set()
            await blocker
            executor.shutdown(wait=True)

    asyncio.run(exercise())

    assert events == [
        "development-enter:dashboard",
        "presentation-enter:dashboard",
        "presentation-exit:dashboard",
        "development-exit:dashboard",
    ]


def test_deletion_capacity_rejects_without_starting_an_unbounded_thread(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepare_view(notebook_path)
    studio = load_studio(notebook_path)
    events: list[str] = []
    validation_started = threading.Event()
    release_validation = threading.Event()
    validations = 0

    def validate(*_args: Any, **_kwargs: Any) -> StudioWorkspace:
        nonlocal validations
        validations += 1
        if validations == 1:
            validation_started.set()
            assert release_validation.wait(timeout=2)
        return studio

    def remove(*_args: Any, **_kwargs: Any) -> StudioWorkspace:
        return studio

    monkeypatch.setattr(
        deletion_service,
        "_DELETION_SLOTS",
        threading.BoundedSemaphore(1),
    )
    monkeypatch.setattr(deletion_service, "validate_view_deletion_owner", validate)
    monkeypatch.setattr(deletion_service, "delete_view", remove)

    async def delete() -> deletion_service.ViewDeletionResult:
        catalog_generation, view_generation = _owners(studio, "dashboard")
        return await deletion_service.delete_owned_view(
            studio,
            "dashboard",
            expected_catalog_generation=catalog_generation,
            expected_generation=view_generation,
            presentation=cast(NotebookPresentation, _Presentation(events)),
            development=cast(DevelopmentCoordinator, _Development(events)),
        )

    async def exercise() -> None:
        first = asyncio.create_task(delete())
        await asyncio.wait_for(_wait_for_event(validation_started), timeout=1)
        try:
            with pytest.raises(ViewDeletionCapacityError) as captured:
                await delete()
            assert captured.value.status_code == 503
            assert captured.value.transient is True
        finally:
            release_validation.set()
        assert (await first).workspace is studio
        assert (await delete()).workspace is studio

    try:
        asyncio.run(exercise())
    finally:
        release_validation.set()


def test_thread_start_failure_releases_deletion_capacity(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepare_view(notebook_path)
    studio = load_studio(notebook_path)
    events: list[str] = []
    start = threading.Thread.start
    starts = 0

    def start_after_failure(thread: threading.Thread) -> None:
        nonlocal starts
        starts += 1
        if starts == 1:
            raise RuntimeError("simulated thread start failure")
        start(thread)

    def validate(*_args: Any, **_kwargs: Any) -> StudioWorkspace:
        return studio

    def remove(*_args: Any, **_kwargs: Any) -> StudioWorkspace:
        return studio

    monkeypatch.setattr(
        deletion_service,
        "_DELETION_SLOTS",
        threading.BoundedSemaphore(1),
    )
    monkeypatch.setattr(threading.Thread, "start", start_after_failure)
    monkeypatch.setattr(deletion_service, "validate_view_deletion_owner", validate)
    monkeypatch.setattr(deletion_service, "delete_view", remove)

    async def delete() -> deletion_service.ViewDeletionResult:
        catalog_generation, view_generation = _owners(studio, "dashboard")
        return await deletion_service.delete_owned_view(
            studio,
            "dashboard",
            expected_catalog_generation=catalog_generation,
            expected_generation=view_generation,
            presentation=cast(NotebookPresentation, _Presentation(events)),
            development=cast(DevelopmentCoordinator, _Development(events)),
        )

    async def exercise() -> None:
        with pytest.raises(RuntimeError, match="thread start failure"):
            await delete()
        assert (await delete()).workspace is studio

    asyncio.run(exercise())

    assert starts == 2


def test_cancelled_deletion_drains_the_owned_thread_before_propagating(
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

    def validate(*_args: Any, **_kwargs: Any) -> StudioWorkspace:
        return studio

    def remove(*_args: Any, **_kwargs: Any) -> StudioWorkspace:
        started.set()
        assert release.wait(timeout=2)
        committed.set()
        return studio

    monkeypatch.setattr(deletion_service, "_DELETION_SLOTS", slots)
    monkeypatch.setattr(deletion_service, "validate_view_deletion_owner", validate)
    monkeypatch.setattr(deletion_service, "delete_view", remove)

    async def exercise() -> None:
        catalog_generation, view_generation = _owners(studio, "dashboard")
        deletion = asyncio.create_task(
            deletion_service.delete_owned_view(
                studio,
                "dashboard",
                expected_catalog_generation=catalog_generation,
                expected_generation=view_generation,
                presentation=cast(NotebookPresentation, _Presentation(events)),
                development=cast(DevelopmentCoordinator, _Development(events)),
            )
        )
        await asyncio.wait_for(_wait_for_event(started), timeout=1)
        deletion.cancel()
        await asyncio.sleep(0)
        deletion.cancel()
        await asyncio.sleep(0)
        assert not deletion.done()

        release.set()
        with pytest.raises(asyncio.CancelledError):
            await deletion

    try:
        asyncio.run(exercise())
    finally:
        release.set()

    assert committed.is_set()
    assert events[-1] == "development-exit:dashboard"
    assert slots.acquire(blocking=False)
    slots.release()


def test_cancelled_deletion_finishes_prevalidation_before_teardown(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepare_view(notebook_path)
    studio = load_studio(notebook_path)
    events: list[str] = []
    validation_started = threading.Event()
    release_validation = threading.Event()
    committed = threading.Event()
    slots = threading.BoundedSemaphore(1)

    def validate(*_args: Any, **_kwargs: Any) -> StudioWorkspace:
        validation_started.set()
        assert release_validation.wait(timeout=2)
        return studio

    def remove(*_args: Any, **_kwargs: Any) -> StudioWorkspace:
        committed.set()
        return studio

    monkeypatch.setattr(deletion_service, "_DELETION_SLOTS", slots)
    monkeypatch.setattr(deletion_service, "validate_view_deletion_owner", validate)
    monkeypatch.setattr(deletion_service, "delete_view", remove)

    async def exercise() -> None:
        catalog_generation, view_generation = _owners(studio, "dashboard")
        deletion = asyncio.create_task(
            deletion_service.delete_owned_view(
                studio,
                "dashboard",
                expected_catalog_generation=catalog_generation,
                expected_generation=view_generation,
                presentation=cast(NotebookPresentation, _Presentation(events)),
                development=cast(DevelopmentCoordinator, _Development(events)),
            )
        )
        await asyncio.wait_for(_wait_for_event(validation_started), timeout=1)
        deletion.cancel()
        await asyncio.sleep(0)
        deletion.cancel()
        await asyncio.sleep(0)
        assert not deletion.done()
        assert events == []

        release_validation.set()
        with pytest.raises(asyncio.CancelledError):
            await deletion

    try:
        asyncio.run(exercise())
    finally:
        release_validation.set()

    assert committed.is_set()
    assert events == [
        "development-enter:dashboard",
        "presentation-enter:dashboard",
        "presentation-exit:dashboard",
        "development-exit:dashboard",
    ]
    assert slots.acquire(blocking=False)
    slots.release()


def test_committed_cleanup_warning_does_not_use_the_default_executor(
    notebook_path: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepare_view(notebook_path)
    studio = load_studio(notebook_path)
    events: list[str] = []
    cleanup = tmp_path / "retained-cleanup"
    occupied = threading.Event()
    release = threading.Event()
    slots = threading.BoundedSemaphore(1)

    def occupy_default_executor() -> None:
        occupied.set()
        assert release.wait(timeout=2)

    def validate(*_args: Any, **_kwargs: Any) -> StudioWorkspace:
        return studio

    def remove(*_args: Any, **_kwargs: Any) -> StudioWorkspace:
        raise ViewDeletionError(cleanup, committed_workspace=studio)

    monkeypatch.setattr(deletion_service, "_DELETION_SLOTS", slots)
    monkeypatch.setattr(deletion_service, "validate_view_deletion_owner", validate)
    monkeypatch.setattr(deletion_service, "delete_view", remove)

    async def exercise() -> None:
        loop = asyncio.get_running_loop()
        executor = ThreadPoolExecutor(max_workers=1)
        loop.set_default_executor(executor)
        blocker = loop.run_in_executor(None, occupy_default_executor)
        try:
            await asyncio.wait_for(_wait_for_event(occupied), timeout=1)
            catalog_generation, view_generation = _owners(studio, "dashboard")
            result = await asyncio.wait_for(
                deletion_service.delete_owned_view(
                    studio,
                    "dashboard",
                    expected_catalog_generation=catalog_generation,
                    expected_generation=view_generation,
                    presentation=cast(NotebookPresentation, _Presentation(events)),
                    development=cast(DevelopmentCoordinator, _Development(events)),
                ),
                timeout=1,
            )
            assert result.workspace is studio
            assert result.cleanup == cleanup
        finally:
            release.set()
            await blocker
            executor.shutdown(wait=True)

    asyncio.run(exercise())

    assert events == [
        "development-enter:dashboard",
        "presentation-enter:dashboard",
        "presentation-exit:dashboard",
        "development-exit:dashboard",
    ]
    assert slots.acquire(blocking=False)
    slots.release()


def test_stale_owner_fails_before_server_teardown(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepare_view(notebook_path)
    studio = load_studio(notebook_path)
    events: list[str] = []
    slots = threading.BoundedSemaphore(1)

    def reject(*_args: Any, **_kwargs: Any) -> StudioWorkspace:
        raise WorkspaceGenerationConflictError()

    def unexpected_remove(*_args: Any, **_kwargs: Any) -> StudioWorkspace:
        raise AssertionError("stale deletion reached the project mutation")

    monkeypatch.setattr(deletion_service, "_DELETION_SLOTS", slots)
    monkeypatch.setattr(deletion_service, "validate_view_deletion_owner", reject)
    monkeypatch.setattr(deletion_service, "delete_view", unexpected_remove)

    async def exercise() -> None:
        catalog_generation, view_generation = _owners(studio, "dashboard")
        with pytest.raises(WorkspaceGenerationConflictError):
            await deletion_service.delete_owned_view(
                studio,
                "dashboard",
                expected_catalog_generation=catalog_generation,
                expected_generation=view_generation,
                presentation=cast(NotebookPresentation, _Presentation(events)),
                development=cast(DevelopmentCoordinator, _Development(events)),
            )

    asyncio.run(exercise())

    assert events == []
    assert slots.acquire(blocking=False)
    slots.release()
