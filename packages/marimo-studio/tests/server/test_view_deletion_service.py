from __future__ import annotations

import asyncio
import threading
from collections.abc import AsyncIterator, Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path
from typing import Any, cast

import pytest

import marimo_studio._server.studio.deletion as deletion_service
from marimo_studio._server.development.coordinator import DevelopmentCoordinator
from marimo_studio._server.presentation.service import NotebookPresentation
from marimo_studio._views.api import prepare_view
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
    def deleting_view(self, view_name: str) -> Iterator[None]:
        self.events.append(f"presentation-enter:{view_name}")
        try:
            yield
        finally:
            self.events.append(f"presentation-exit:{view_name}")


def _owners(studio: StudioWorkspace, name: str) -> tuple[str, str]:
    return studio.catalog_generation, studio.view_generations[name]


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

    assert validations == 2


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
