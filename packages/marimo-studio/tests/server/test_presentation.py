from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path
from threading import Event, Thread
from types import SimpleNamespace
from typing import Any, cast

import pytest

from marimo_studio._processes.supervisor import ProcessCleanupError
from marimo_studio._server.development import routes as development_routes
from marimo_studio._server.development.coordinator import DevelopmentCoordinator
from marimo_studio._server.development.ports import (
    FileChangeCallback,
    ProjectWatcher,
    ProjectWatchPlan,
)
from marimo_studio._server.presentation import access as presentation_access
from marimo_studio._server.presentation import service as presentation_service
from marimo_studio._server.presentation.service import NotebookPresentation
from marimo_studio._views.build import publish_view as publish_artifact
from marimo_studio._workspace.mutation_lock import (
    view_mutation_lock,
    workspace_catalog_lock,
)
from marimo_studio.errors import ViewProjectError
from marimo_studio.errors._internal import RuntimeSyncError
from marimo_studio.view_providers import BuildProfile

from ..app_helpers import configured, created_one_view
from ..async_test_support import wait_for_event


class _Watcher:
    async def replace(
        self,
        plan: ProjectWatchPlan,
        callback: FileChangeCallback,
    ) -> None:
        del plan, callback
        return None

    async def close(self) -> None:
        return None


def _watcher_factory() -> ProjectWatcher:
    return _Watcher()


def test_snapshot_capture_keeps_the_event_loop_responsive(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    studio = configured(notebook_path)
    presentation = NotebookPresentation(studio.notebook)
    capture_started = Event()
    release_capture = Event()
    native_snapshot = presentation.snapshot

    def slow_snapshot(
        view_name: str | None,
        *,
        profile: BuildProfile = "development",
    ):
        capture_started.set()
        assert release_capture.wait(timeout=1)
        return native_snapshot(view_name, profile=profile)

    monkeypatch.setattr(presentation, "snapshot", slow_snapshot)

    async def exercise() -> None:
        capture = asyncio.create_task(presentation.snapshot_async("dashboard"))
        assert await asyncio.to_thread(capture_started.wait, 1)
        heartbeat = asyncio.Event()
        asyncio.get_running_loop().call_soon(heartbeat.set)
        await asyncio.wait_for(heartbeat.wait(), timeout=1)
        release_capture.set()
        snapshot = await asyncio.wait_for(capture, timeout=1)
        assert snapshot.view_name == "dashboard"

    asyncio.run(exercise())


def test_snapshot_capture_surfaces_process_cleanup_failure(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    studio = configured(notebook_path)
    presentation = NotebookPresentation(studio.notebook)

    def fail(*_args: object, **_kwargs: object) -> object:
        raise ProcessCleanupError("snapshot provider process survived")

    monkeypatch.setattr(presentation_service, "capture_presentations", fail)
    try:
        with pytest.raises(
            ProcessCleanupError,
            match="snapshot provider process survived",
        ):
            presentation.snapshot("dashboard")
    finally:
        presentation.close()


def test_capability_revision_check_surfaces_process_cleanup_failure() -> None:
    async def snapshot(*_args: object, **_kwargs: object) -> object:
        try:
            raise ProcessCleanupError("capability provider process survived")
        except ProcessCleanupError as cleanup:
            raise ViewProjectError("snapshot failed") from cleanup

    handler = object.__new__(presentation_access.PresentationCapabilityHandler)
    cast(Any, handler)._notebooks = SimpleNamespace(
        get=lambda _notebook: SimpleNamespace(
            presentation=SimpleNamespace(snapshot_async=snapshot)
        )
    )

    async def exercise() -> None:
        with pytest.raises(
            ProcessCleanupError,
            match="capability provider process survived",
        ):
            await cast(Any, handler)._current_revision_matches(
                SimpleNamespace(
                    view="dashboard",
                    target="/config",
                    capability=object(),
                ),
                SimpleNamespace(notebook=Path("analysis.py")),
                SimpleNamespace(mode="run"),
            )

    asyncio.run(exercise())


def test_presentation_cache_separates_development_and_production_profiles(
    notebook_path: Path,
) -> None:
    studio = configured(notebook_path)
    presentation = NotebookPresentation(studio.notebook)
    try:
        development = presentation.snapshot("dashboard")
        production = presentation.snapshot("dashboard", profile="production")

        assert development.artifact.profile == "development"
        assert production.artifact.profile == "production"
        assert development.revision != production.revision
        assert presentation.snapshot("dashboard") is development
        assert presentation.snapshot("dashboard", profile="production") is production
    finally:
        presentation.close()


def test_display_snapshot_refreshes_an_immediate_notebook_edit(
    notebook_path: Path,
) -> None:
    studio = configured(notebook_path)
    development = DevelopmentCoordinator(project_watcher=_watcher_factory)
    presentation = NotebookPresentation(studio.notebook, development=development)

    async def exercise() -> None:
        try:
            first = await presentation.display_snapshot_async("dashboard")
            notebook_path.write_text(
                notebook_path.read_text(encoding="utf-8") + "\n",
                encoding="utf-8",
            )

            current = await presentation.display_snapshot_async("dashboard")

            assert current.revision != first.revision
        finally:
            presentation.close()
            await development.close()

    asyncio.run(exercise())


def test_last_good_cache_observes_a_publication_completed_in_the_same_generation(
    notebook_path: Path,
) -> None:
    studio = configured(notebook_path)
    project = studio.view("dashboard")
    coordinator = DevelopmentCoordinator()
    presentation = NotebookPresentation(
        studio.notebook,
        development=coordinator,
    )

    async def exercise() -> None:
        try:
            initial = await presentation.display_snapshot_async("dashboard")
            source = project.root / "index.html"
            source.write_text(
                source.read_text(encoding="utf-8").replace(
                    "</main>",
                    "<h1>Published repair</h1></main>",
                ),
                encoding="utf-8",
            )
            await coordinator.refresh("dashboard")
            retained = await presentation.display_snapshot_async("dashboard")
            with await asyncio.to_thread(publish_artifact, project, "development"):
                pass
            repaired = await presentation.display_snapshot_async("dashboard")

            assert retained.revision == initial.revision
            assert repaired.revision != retained.revision
            assert "Published repair" in repaired.document
        finally:
            presentation.close()
            await coordinator.close()

    asyncio.run(exercise())


def test_first_preview_reports_provider_failure_and_recovers_after_repair(
    notebook_path: Path,
) -> None:
    studio = created_one_view(notebook_path)
    manifest = studio.view("dashboard").manifest
    original = manifest.read_text(encoding="utf-8")
    manifest.write_text(original + "\n[options]\nunknown = true\n", encoding="utf-8")
    coordinator = DevelopmentCoordinator(project_watcher=_watcher_factory)
    presentation = NotebookPresentation(studio.notebook, development=coordinator)

    async def exercise() -> None:
        try:
            with pytest.raises(ViewProjectError, match="undeclared option") as failure:
                await presentation.display_snapshot_async("dashboard")
            assert failure.value.source == manifest
            assert not failure.value.transient

            manifest.write_text(original, encoding="utf-8")
            await coordinator.refresh("dashboard")
            recovered = await presentation.display_snapshot_async("dashboard")
            assert recovered.view_name == "dashboard"
            assert "marimo-cell" in recovered.document
        finally:
            presentation.close()
            await coordinator.close()

    asyncio.run(exercise())


def test_snapshot_reconciliation_is_bounded_during_continuous_churn(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    studio = configured(notebook_path)
    coordinator = DevelopmentCoordinator(project_watcher=_watcher_factory)
    presentation = NotebookPresentation(studio.notebook, development=coordinator)
    baseline = presentation.snapshot("dashboard")
    calls = 0

    async def changing_catalog(*_args: object, **_kwargs: object):
        nonlocal calls
        calls += 1
        catalog = await native_catalog(studio, "dashboard")
        return replace(catalog, generation=calls)

    native_catalog = coordinator.project_catalog
    monkeypatch.setattr(coordinator, "project_catalog", changing_catalog)
    monkeypatch.setattr(
        presentation,
        "_resolve_snapshot",
        lambda *_args, **_kwargs: baseline,
    )

    async def exercise() -> None:
        try:
            with pytest.raises(RuntimeSyncError, match="kept changing"):
                await presentation.snapshot_async("dashboard")
        finally:
            presentation.close()
            await coordinator.close()

    asyncio.run(exercise())


def test_development_event_and_snapshot_share_one_typed_publication(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    studio = configured(notebook_path)
    coordinator = DevelopmentCoordinator(project_watcher=_watcher_factory)
    presentation = NotebookPresentation(studio.notebook, development=coordinator)
    started = Event()
    release = Event()
    second_waiter = asyncio.Event()
    calls = 0
    waiters = 0
    native_publish = presentation_service.publish_presentation
    coordinate_publication = coordinator.publish

    def publish(*args: Any, **kwargs: Any):
        nonlocal calls
        calls += 1
        started.set()
        assert release.wait(timeout=2)
        return native_publish(*args, **kwargs)

    monkeypatch.setattr(development_routes, "_publish_presentation", publish)
    monkeypatch.setattr(presentation_service, "publish_presentation", publish)

    async def observed_publication(*args: Any, **kwargs: Any):
        nonlocal waiters
        waiters += 1
        if waiters == 2:
            second_waiter.set()
        return await coordinate_publication(*args, **kwargs)

    monkeypatch.setattr(coordinator, "publish", observed_publication)

    async def exercise() -> None:
        try:
            catalog = await coordinator.project_catalog(studio, "dashboard")
            event = asyncio.create_task(
                development_routes._prepare_presentation(
                    studio,
                    "dashboard",
                    catalog.generation,
                    coordinator,
                )
            )
            assert await asyncio.to_thread(started.wait, 1)
            snapshot = asyncio.create_task(presentation.snapshot_async("dashboard"))
            await wait_for_event(second_waiter)
            release.set()
            event_result, snapshot_result = await asyncio.gather(event, snapshot)

            assert isinstance(event_result, tuple)
            assert len(event_result) == 3
            assert snapshot_result.view_name == "dashboard"
            assert event_result[1] == snapshot_result.revision
            assert calls == 1
        finally:
            release.set()
            presentation.close()
            await coordinator.close()

    asyncio.run(exercise())


def test_unstable_document_stamps_use_runtime_sync_or_last_good_snapshot(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    studio = configured(notebook_path)
    coordinator = DevelopmentCoordinator(project_watcher=_watcher_factory)
    presentation = NotebookPresentation(studio.notebook, development=coordinator)

    def missing_document(*_args: object) -> object:
        raise FileNotFoundError("document replaced")

    async def exercise() -> None:
        fresh: NotebookPresentation | None = None
        try:
            retained = await presentation.display_snapshot_async("dashboard")
            monkeypatch.setattr(presentation, "_document_stamps", missing_document)
            assert await presentation.display_snapshot_async("dashboard") is retained

            fresh = NotebookPresentation(studio.notebook, development=coordinator)
            monkeypatch.setattr(fresh, "_document_stamps", missing_document)
            with pytest.raises(RuntimeSyncError, match="documents changed"):
                await fresh.snapshot_async("dashboard")
        finally:
            presentation.close()
            if fresh is not None:
                fresh.close()
            await coordinator.close()

    asyncio.run(exercise())


def test_catalog_presentation_view_order_allows_snapshot_owner_to_finish(
    tmp_path: Path,
) -> None:
    presentation = NotebookPresentation(tmp_path / "analysis.py")
    view_root = tmp_path / "views"
    presentation_held = Event()
    catalog_held = Event()
    snapshot_finished = Event()
    deletion_finished = Event()

    def snapshot_owner() -> None:
        with presentation._coordination_lock("dashboard"):
            presentation_held.set()
            assert catalog_held.wait(timeout=1)
            with view_mutation_lock(view_root, "dashboard"):
                snapshot_finished.set()

    def deletion_owner() -> None:
        assert presentation_held.wait(timeout=1)
        with workspace_catalog_lock(view_root):
            catalog_held.set()
            with (
                presentation.deleting_view("dashboard") as release_artifacts,
                view_mutation_lock(view_root, "dashboard"),
            ):
                release_artifacts()
                deletion_finished.set()

    snapshot = Thread(target=snapshot_owner)
    deletion = Thread(target=deletion_owner)
    snapshot.start()
    deletion.start()
    snapshot.join(timeout=2)
    deletion.join(timeout=2)

    assert snapshot_finished.is_set()
    assert deletion_finished.is_set()
    assert not snapshot.is_alive()
    assert not deletion.is_alive()
