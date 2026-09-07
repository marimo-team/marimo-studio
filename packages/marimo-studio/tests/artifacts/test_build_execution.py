"""Exercise build snapshots, scheduling, finalization, and cancellation."""

from __future__ import annotations

import asyncio
import shutil
from dataclasses import replace
from pathlib import Path, PurePosixPath
from threading import Event, Thread
from typing import Any

import pytest

import marimo_studio._artifacts.inputs as inputs_module
import marimo_studio._artifacts.publication as publication_module
import marimo_studio._artifacts.repository as repository_module
from marimo_studio._artifacts.paths import artifact_root
from marimo_studio._artifacts.repository import (
    read_build_state,
    read_published_artifact,
)
from marimo_studio._artifacts.retention import ArtifactLease
from marimo_studio._processes.cancellation import (
    ProviderOperationControl,
    provider_cancellation,
)
from marimo_studio._views.build import build_view_project
from marimo_studio._views.build import publish_view as publish_artifact_lease
from marimo_studio._views.inspection import inspection_request
from marimo_studio.view_providers import (
    BuildRequest,
    BuildResult,
    ProjectInput,
    ViewProject,
)
from marimo_studio.view_providers._host import provider_registry

from ..artifact_test_support import change_document, publish_artifact
from ..artifact_test_support import project as make_project


def test_snapshot_copies_the_inputs_accepted_by_its_source_capture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = make_project(tmp_path)
    provider = provider_registry().get(project.provider)
    inspection = replace(
        provider.inspect(inspection_request(project)),
        input_scope=(ProjectInput(PurePosixPath("."), "directory"),),
    )
    capture = inputs_module.project_input_state
    added = project.root / "extra.css"

    def add_at_capture(*args: Any, **kwargs: Any):
        if not added.exists():
            added.write_text("body { color: blue; }", encoding="utf-8")
        return capture(*args, **kwargs)

    monkeypatch.setattr(inputs_module, "project_input_state", add_at_capture)
    snapshot = inputs_module.snapshot_project(
        project,
        inspection,
        artifact_root(project) / "snapshot",
    )

    assert (snapshot.project.root / "extra.css").read_text(encoding="utf-8") == (
        "body { color: blue; }"
    )
    assert PurePosixPath("extra.css") in snapshot.input_digests


def test_provider_build_reads_one_immutable_input_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = make_project(tmp_path)
    live_document = project.root / "index.html"
    source_a = live_document.read_text(encoding="utf-8").replace(
        "</main>", "<p>generation-a</p></main>"
    )
    source_b = source_a.replace("generation-a", "generation-b")
    live_document.write_text(source_a, encoding="utf-8")
    provider = provider_registry().get(project.provider)

    def build_from_snapshot(request: BuildRequest) -> BuildResult:
        assert request.project.root != project.root
        assert request.cache_root == artifact_root(project) / ".cache"
        assert request.cache_root.is_dir()
        live_document.write_text(source_b, encoding="utf-8")
        snapshot_document = request.project.root / "index.html"
        assert snapshot_document.read_text(encoding="utf-8") == source_a
        shutil.copy2(snapshot_document, request.staging_root / "index.html")
        live_document.write_text(source_a, encoding="utf-8")
        return BuildResult(PurePosixPath("index.html"), ())

    monkeypatch.setattr(provider, "build", build_from_snapshot)
    with publish_artifact_lease(project, "development") as lease:
        document = lease.read_text(lease.artifact.document)

    assert document == source_a


def test_build_request_receives_the_owner_cancellation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = make_project(tmp_path)
    provider = provider_registry().get(project.provider)
    build = provider.build
    control = ProviderOperationControl()

    def capture_cancellation(request: BuildRequest) -> BuildResult:
        assert request.cancellation is control.cancellation
        return build(request)

    monkeypatch.setattr(provider, "build", capture_cancellation)
    with provider_cancellation(control):
        lease = publish_artifact_lease(project, "development")

    lease.close()


@pytest.mark.parametrize(
    "blocked_operation",
    ("artifact-state-read", "lease-release"),
)
def test_async_build_keeps_the_event_loop_live_during_result_finalization(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    blocked_operation: str,
) -> None:
    project = make_project(tmp_path)
    entered = Event()
    release = Event()

    def pause() -> None:
        entered.set()
        if not release.wait(timeout=2):
            raise RuntimeError("test artifact operation was not released")

    if blocked_operation == "artifact-state-read":
        read_artifact_state = repository_module.read_artifact_state

        def blocking_read_artifact_state(*args: Any, **kwargs: Any):
            pause()
            return read_artifact_state(*args, **kwargs)

        monkeypatch.setattr(
            repository_module,
            "read_artifact_state",
            blocking_read_artifact_state,
        )
    else:
        close_lease = ArtifactLease.close

        def blocking_close_lease(lease: ArtifactLease) -> None:
            pause()
            close_lease(lease)

        monkeypatch.setattr(ArtifactLease, "close", blocking_close_lease)

    async def exercise() -> None:
        loop = asyncio.get_running_loop()
        heartbeat = asyncio.Event()

        def schedule_heartbeat() -> None:
            if entered.wait(timeout=2):
                loop.call_soon_threadsafe(heartbeat.set)

        observer = Thread(target=schedule_heartbeat)
        observer.start()
        building = asyncio.create_task(build_view_project(project))
        try:
            await asyncio.wait_for(heartbeat.wait(), timeout=3)
            assert not building.done()
            release.set()
            built = await building
        finally:
            release.set()
            observer.join(timeout=2)
            await asyncio.gather(building, return_exceptions=True)

        assert not observer.is_alive()
        assert built.view == project.name

    asyncio.run(exercise())


def test_cancelled_async_build_does_not_publish_a_completed_candidate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = make_project(tmp_path)
    first = publish_artifact(project, "development")
    change_document(project, "cancelled generation")
    provider = provider_registry().get(project.provider)
    build = provider.build
    completed = Event()

    def finish_after_cancellation(request: BuildRequest) -> BuildResult:
        report = build(request)
        completed.set()
        cancelled = Event()
        unregister = request.cancellation.register(cancelled.set)
        try:
            if not cancelled.wait(timeout=2):
                raise RuntimeError("test build was not cancelled")
        finally:
            unregister()
        return report

    monkeypatch.setattr(provider, "build", finish_after_cancellation)

    async def exercise() -> None:
        task = asyncio.create_task(build_view_project(project))
        assert await asyncio.to_thread(completed.wait, 2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(exercise())

    retained = read_published_artifact(project, "development")
    assert retained is not None
    assert retained.artifact_revision == first.artifact_revision
    state = read_build_state(project, "development")
    assert state.phase == "failed"
    assert state.artifact_revision == first.artifact_revision
    assert [item.code for item in state.diagnostics] == ["build-cancelled"]


@pytest.mark.parametrize(
    "cache_hit",
    (False, True),
    ids=("new-publication", "cached-publication"),
)
def test_cancellation_before_receipt_commit_preserves_last_good(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    cache_hit: bool,
) -> None:
    project = make_project(tmp_path)
    first = publish_artifact(project, "development")
    if not cache_hit:
        change_document(project, "candidate awaiting receipt commit")
    write = publication_module.write_profile_state_if_active
    commit_started = Event()
    cancelled = Event()
    release = Event()

    def pause_receipt_commit(
        selected: ViewProject,
        state: Any,
        control: ProviderOperationControl,
    ) -> bool:
        assert selected == project
        unregister = control.cancellation.register(cancelled.set)
        commit_started.set()
        try:
            if not release.wait(timeout=2):
                raise RuntimeError("receipt commit was not released")
        finally:
            unregister()
        return write(selected, state, control)

    monkeypatch.setattr(
        publication_module,
        "write_profile_state_if_active",
        pause_receipt_commit,
    )

    async def exercise() -> None:
        task = asyncio.create_task(build_view_project(project))
        assert await asyncio.to_thread(commit_started.wait, 2)
        task.cancel()
        assert await asyncio.to_thread(cancelled.wait, 2)
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(exercise())

    retained = read_published_artifact(project, "development")
    assert retained is not None
    assert retained.artifact_revision == first.artifact_revision
    state = read_build_state(project, "development")
    assert state.phase == "failed"
    assert state.artifact_revision == first.artifact_revision
    assert [item.code for item in state.diagnostics] == ["build-cancelled"]
    revisions = artifact_root(project) / "revisions"
    assert {path.name for path in revisions.iterdir()} == {
        first.artifact_revision.removeprefix("sha256:")
    }
