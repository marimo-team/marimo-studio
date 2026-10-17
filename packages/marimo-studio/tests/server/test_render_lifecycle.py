from __future__ import annotations

import asyncio
import gc
import os
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Mapping
from pathlib import Path, PurePosixPath
from types import SimpleNamespace
from typing import Any

import pytest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Route
from starlette.testclient import TestClient

import marimo_studio._server.presentation.renders as renders_module
from marimo_studio._server.presentation.render_routes import render_file_response
from marimo_studio._server.presentation.renders import RenderStore, RenderUnavailable
from marimo_studio._views.renders import RenderBundle
from marimo_studio.view_providers import (
    ProjectDiagnostic,
    RenderFile,
    RenderRequest,
    RenderResult,
    Representation,
)
from marimo_studio.view_providers._host.registry import ProviderRegistry

from ..provider_test_support import ProviderStub, candidate

TEMPLATE = PurePosixPath("card.txt")
OUTPUT = PurePosixPath("card.svg")

# The provider command records its PID, then outlives any reasonable test, so
# only render cancellation can stop it.
_SLOW_COMMAND = (
    "import os, pathlib, sys, time; "
    "pathlib.Path(sys.argv[1]).write_text(str(os.getpid())); "
    "time.sleep(60)"
)


def _card(
    request: RenderRequest,
    text: str,
    warnings: tuple[ProjectDiagnostic, ...] = (),
) -> RenderResult:
    request.output_root.joinpath(OUTPUT).write_text(
        f'<svg xmlns="http://www.w3.org/2000/svg"><text>{text}</text></svg>',
        encoding="utf-8",
    )
    return RenderResult(
        (RenderFile(OUTPUT, "image/svg+xml"),), main=OUTPUT, diagnostics=warnings
    )


class SlowRenderer(ProviderStub):
    def __init__(self, marker: Path) -> None:
        super().__init__("test-slow/card", "default")
        self.marker = marker

    def render(self, request: RenderRequest) -> RenderResult:
        request.runner.run(
            [sys.executable, "-c", _SLOW_COMMAND, str(self.marker)],
            cwd=request.template_root,
            timeout=120,
        )
        return _card(request, "late")


class GatedRenderer(ProviderStub):
    """Render a card once the test opens the gate or the render is cancelled."""

    def __init__(self) -> None:
        super().__init__("test-gated/card", "default")
        self.started = threading.Event()
        self.gate = threading.Event()
        self.cancelled = threading.Event()
        self.calls = 0

    def render(self, request: RenderRequest) -> RenderResult:
        self.calls += 1
        self.started.set()
        while not self.gate.wait(0.01):
            if request.cancellation.cancelled:
                self.cancelled.set()
                break
        return _card(request, str(dict(request.values)))


class CardRenderer(ProviderStub):
    """Render a card from ``text(values)``."""

    def __init__(
        self,
        text: Callable[[Mapping[str, object]], str],
        warning: Callable[[Mapping[str, object]], str] | None = None,
    ) -> None:
        super().__init__("test-card/card", "default")
        self.text = text
        self.warning = warning
        self.calls = 0

    def render(self, request: RenderRequest) -> RenderResult:
        self.calls += 1
        warnings = (
            ()
            if self.warning is None
            else (
                ProjectDiagnostic("card-note", "warning", self.warning(request.values)),
            )
        )
        return _card(request, self.text(request.values), warnings)


class _Lease:
    def __enter__(self) -> _Lease:
        return self

    def __exit__(self, *_error: object) -> None:
        return None

    def copy_template(self, destination: Path) -> None:
        destination.mkdir()
        destination.joinpath(TEMPLATE).write_text("Card", encoding="utf-8")


def _store(
    monkeypatch: pytest.MonkeyPatch,
    renderer: ProviderStub,
    *,
    max_bytes: int | None = None,
    abandoned_grace: float = 0.05,
) -> tuple[RenderStore, Any, Any]:
    registry = ProviderRegistry(
        (candidate("card", renderer, distribution="test-renderer"),)
    )
    monkeypatch.setattr(renders_module, "provider_registry", lambda: registry)
    presentation = SimpleNamespace(lease_artifact=lambda _view, _revision: _Lease())
    snapshot = SimpleNamespace(
        view_name="card",
        sites=(),
        artifact=SimpleNamespace(
            artifact_revision="sha256:card",
            provider=SimpleNamespace(key=registry.ids[0]),
        ),
    )
    store = (
        RenderStore(abandoned_grace=abandoned_grace)
        if max_bytes is None
        else RenderStore(max_bytes=max_bytes, abandoned_grace=abandoned_grace)
    )
    return store, presentation, snapshot


async def _render(
    store: RenderStore,
    presentation: Any,
    snapshot: Any,
    values: Mapping[str, object],
    *,
    holder: str | None = None,
    alive: Callable[[str], bool] = lambda _session: True,
    outputs: Mapping[str, Representation] | None = None,
) -> RenderBundle:
    return await store.render(
        presentation,
        snapshot,
        TEMPLATE,
        values,
        outputs or {},
        {},
        holder=holder,
        alive=alive,
    )


def _pid_is_live(pid: int) -> bool:
    result = subprocess.run(
        ["ps", "-o", "stat=", "-p", str(pid)],
        check=False,
        capture_output=True,
        text=True,
    )
    state = result.stdout.strip()
    return bool(state) and not state.startswith("Z")


async def _started(marker: Path) -> int:
    deadline = time.monotonic() + 15
    while not marker.is_file() or not marker.read_text(encoding="utf-8"):
        assert time.monotonic() < deadline, "The provider command never started"
        await asyncio.sleep(0.02)
    return int(marker.read_text(encoding="utf-8"))


async def _stopped(pid: int) -> None:
    deadline = time.monotonic() + 15
    while _pid_is_live(pid):
        assert time.monotonic() < deadline, "The provider command kept running"
        await asyncio.sleep(0.02)


@pytest.mark.native_process
@pytest.mark.skipif(os.name == "nt", reason="ps reports POSIX process state")
def test_an_abandoned_render_stops_its_provider_command_after_its_grace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    marker = tmp_path / "render-pid"
    store, presentation, snapshot = _store(monkeypatch, SlowRenderer(marker))

    async def exercise() -> None:
        render = asyncio.create_task(
            _render(store, presentation, snapshot, {"total": 1})
        )
        pid = await _started(marker)
        render.cancel()
        with pytest.raises(asyncio.CancelledError):
            await render
        await _stopped(pid)

    try:
        asyncio.run(exercise())
    finally:
        store.close()


@pytest.mark.native_process
@pytest.mark.skipif(os.name == "nt", reason="ps reports POSIX process state")
def test_closing_the_render_store_stops_active_renders(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    marker = tmp_path / "render-pid"
    store, presentation, snapshot = _store(monkeypatch, SlowRenderer(marker))

    async def exercise() -> int:
        render = asyncio.create_task(
            _render(store, presentation, snapshot, {"total": 1})
        )
        pid = await _started(marker)
        await asyncio.to_thread(store.close)
        with pytest.raises(RenderUnavailable):
            await render
        return pid

    try:
        pid = asyncio.run(exercise())
    finally:
        store.close()

    assert not _pid_is_live(pid)


@pytest.mark.native_process
@pytest.mark.skipif(os.name == "nt", reason="ps reports POSIX process state")
def test_closing_the_render_store_ends_queued_renders_as_unavailable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    marker = tmp_path / "render-pid"
    store, presentation, snapshot = _store(monkeypatch, SlowRenderer(marker))

    async def exercise() -> list[Any]:
        # Two workers take the first renders, and the third waits in the queue.
        tasks = [
            asyncio.create_task(
                _render(store, presentation, snapshot, {"total": total})
            )
            for total in (1, 2, 3)
        ]
        await _started(marker)
        await asyncio.to_thread(store.close)
        return await asyncio.gather(*tasks, return_exceptions=True)

    try:
        results = asyncio.run(exercise())
    finally:
        store.close()

    assert all(isinstance(result, RenderUnavailable) for result in results), results


def test_a_shared_render_continues_while_another_request_waits_on_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    renderer = GatedRenderer()
    store, presentation, snapshot = _store(monkeypatch, renderer)

    async def exercise() -> RenderBundle:
        leaving = asyncio.create_task(
            _render(store, presentation, snapshot, {"total": 1})
        )
        staying = asyncio.create_task(
            _render(store, presentation, snapshot, {"total": 1})
        )
        await asyncio.to_thread(renderer.started.wait, 15)
        leaving.cancel()
        with pytest.raises(asyncio.CancelledError):
            await leaving
        renderer.gate.set()
        return await staying

    try:
        bundle = asyncio.run(exercise())
        assert not renderer.cancelled.is_set()
        assert store.file("card", bundle.id, OUTPUT) is not None
    finally:
        store.close()


def test_a_shared_render_stops_when_its_last_request_leaves(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    renderer = GatedRenderer()
    store, presentation, snapshot = _store(monkeypatch, renderer)

    async def exercise() -> None:
        requests = [
            asyncio.create_task(_render(store, presentation, snapshot, {"total": 1}))
            for _ in range(2)
        ]
        await asyncio.to_thread(renderer.started.wait, 15)
        for request in requests:
            request.cancel()
        results = await asyncio.gather(*requests, return_exceptions=True)
        assert all(isinstance(item, asyncio.CancelledError) for item in results)
        assert await asyncio.to_thread(renderer.cancelled.wait, 15)

    try:
        asyncio.run(exercise())
    finally:
        store.close()


def test_an_abandoned_render_leaves_nothing_in_the_asyncio_log(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    renderer = GatedRenderer()
    store, presentation, snapshot = _store(monkeypatch, renderer)

    async def exercise() -> None:
        leaving = asyncio.create_task(
            _render(store, presentation, snapshot, {"total": 1})
        )
        await asyncio.to_thread(renderer.started.wait, 15)
        leaving.cancel()
        with pytest.raises(asyncio.CancelledError):
            await leaving
        assert await asyncio.to_thread(renderer.cancelled.wait, 15)

    try:
        asyncio.run(exercise())
        # asyncio reports an unretrieved exception when its future is collected.
        gc.collect()
        assert [r.getMessage() for r in caplog.records if r.name == "asyncio"] == []
    finally:
        store.close()


def test_a_request_within_the_grace_continues_the_abandoned_render(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    renderer = GatedRenderer()
    store, presentation, snapshot = _store(monkeypatch, renderer, abandoned_grace=0.1)

    async def exercise() -> RenderBundle:
        leaving = asyncio.create_task(
            _render(store, presentation, snapshot, {"total": 1})
        )
        await asyncio.to_thread(renderer.started.wait, 15)
        leaving.cancel()
        with pytest.raises(asyncio.CancelledError):
            await leaving
        rejoining = asyncio.create_task(
            _render(store, presentation, snapshot, {"total": 1})
        )
        # Several grace periods pass while the rejoined request waits.
        await asyncio.sleep(0.5)
        assert not renderer.cancelled.is_set()
        renderer.gate.set()
        return await rejoining

    try:
        bundle = asyncio.run(exercise())
        assert renderer.calls == 1
        assert store.file("card", bundle.id, OUTPUT) is not None
    finally:
        store.close()


def test_an_abandoned_render_that_has_not_started_never_runs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    renderer = GatedRenderer()
    store, presentation, snapshot = _store(monkeypatch, renderer, abandoned_grace=30)

    async def exercise() -> None:
        # Two renders take both workers, so the third waits in the queue.
        running = [
            asyncio.create_task(
                _render(store, presentation, snapshot, {"total": total})
            )
            for total in (1, 2)
        ]
        while renderer.calls < 2:
            await asyncio.sleep(0.01)
        queued = asyncio.create_task(
            _render(store, presentation, snapshot, {"total": 3})
        )
        await asyncio.sleep(0.05)
        queued.cancel()
        with pytest.raises(asyncio.CancelledError):
            await queued
        renderer.gate.set()
        await asyncio.gather(*running)
        await asyncio.sleep(0.1)

    try:
        asyncio.run(exercise())
        assert renderer.calls == 2
    finally:
        store.close()


def test_an_abandoned_render_that_finishes_keeps_the_store_in_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    renderer = GatedRenderer()
    store, presentation, snapshot = _store(
        monkeypatch, renderer, max_bytes=1, abandoned_grace=30
    )

    async def exercise() -> RenderBundle:
        renderer.gate.set()
        first = await _render(store, presentation, snapshot, {"total": 1})
        renderer.gate.clear()
        renderer.started.clear()
        leaving = asyncio.create_task(
            _render(store, presentation, snapshot, {"total": 2})
        )
        await asyncio.to_thread(renderer.started.wait, 15)
        leaving.cancel()
        with pytest.raises(asyncio.CancelledError):
            await leaving
        renderer.gate.set()
        deadline = time.monotonic() + 15
        while store.file("card", first.id, OUTPUT) is not None:
            assert time.monotonic() < deadline, "The finished render kept every bundle"
            await asyncio.sleep(0.01)
        return first

    try:
        first = asyncio.run(exercise())
        assert store.file("card", first.id, OUTPUT) is None
    finally:
        store.close()


def test_a_request_after_the_grace_starts_a_new_render(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    renderer = GatedRenderer()
    store, presentation, snapshot = _store(monkeypatch, renderer)

    async def exercise() -> RenderBundle:
        leaving = asyncio.create_task(
            _render(store, presentation, snapshot, {"total": 1})
        )
        await asyncio.to_thread(renderer.started.wait, 15)
        leaving.cancel()
        with pytest.raises(asyncio.CancelledError):
            await leaving
        assert await asyncio.to_thread(renderer.cancelled.wait, 15)
        renderer.gate.set()
        return await _render(store, presentation, snapshot, {"total": 1})

    try:
        bundle = asyncio.run(exercise())
        assert renderer.calls == 2
        assert store.file("card", bundle.id, OUTPUT) is not None
    finally:
        store.close()


def test_renders_with_identical_files_share_one_bundle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    renderer = CardRenderer(
        lambda _values: "Same card", lambda values: f"Total {values['total']}"
    )
    store, presentation, snapshot = _store(monkeypatch, renderer)

    async def exercise() -> tuple[RenderBundle, RenderBundle]:
        first = await _render(store, presentation, snapshot, {"total": 1})
        second = await _render(store, presentation, snapshot, {"total": 2})
        return first, second

    try:
        first, second = asyncio.run(exercise())
        assert renderer.calls == 2
        assert first.id == second.id
        assert first.root == second.root
        assert [item.message for item in first.warnings] == ["Total 1"]
        assert [item.message for item in second.warnings] == ["Total 2"]
    finally:
        store.close()


def test_a_live_session_keeps_the_bundle_it_shows_through_eviction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    renderer = CardRenderer(lambda values: f"Total {values['total']}")
    # Every bundle exceeds the budget, so each render evicts all it may.
    store, presentation, snapshot = _store(monkeypatch, renderer, max_bytes=1)
    live = {"reader-a", "reader-b", "reader-c"}

    async def render(total: int, holder: str) -> RenderBundle:
        return await _render(
            store,
            presentation,
            snapshot,
            {"total": total},
            holder=holder,
            alive=lambda session: session in live,
        )

    async def exercise() -> tuple[bool, bool, bool]:
        shown = await render(1, "reader-a")
        await render(2, "reader-b")
        kept_while_alive = store.file("card", shown.id, OUTPUT) is not None
        live.discard("reader-a")
        other = await render(3, "reader-c")
        evicted_after_end = store.file("card", shown.id, OUTPUT) is None
        current = store.file("card", other.id, OUTPUT) is not None
        return kept_while_alive, evicted_after_end, current

    try:
        assert asyncio.run(exercise()) == (True, True, True)
    finally:
        store.close()


def test_a_session_releases_its_previous_bundle_when_it_shows_another(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    renderer = CardRenderer(lambda values: f"Total {values['total']}")
    store, presentation, snapshot = _store(monkeypatch, renderer, max_bytes=1)

    async def exercise() -> tuple[bool, bool]:
        first = await _render(
            store, presentation, snapshot, {"total": 1}, holder="reader"
        )
        second = await _render(
            store, presentation, snapshot, {"total": 2}, holder="reader"
        )
        await _render(store, presentation, snapshot, {"total": 3}, holder="other")
        return (
            store.file("card", first.id, OUTPUT) is None,
            store.file("card", second.id, OUTPUT) is not None,
        )

    try:
        assert asyncio.run(exercise()) == (True, True)
    finally:
        store.close()


class PageRenderer(ProviderStub):
    """Render an HTML page and an SVG image, which may run reader data as script."""

    def __init__(self) -> None:
        super().__init__("test-page/card", "default")

    def render(self, request: RenderRequest) -> RenderResult:
        page = PurePosixPath("card.html")
        request.output_root.joinpath(page).write_text(
            "<script>parent.document.title = 'escaped'</script>", encoding="utf-8"
        )
        _card(request, "card")
        return RenderResult(
            (RenderFile(page, "text/html"), RenderFile(OUTPUT, "image/svg+xml")),
            main=page,
        )


@pytest.mark.parametrize(
    ("path", "media_type"),
    (("card.html", "text/html"), ("card.svg", "image/svg+xml")),
)
def test_rendered_files_open_in_a_sandboxed_origin(
    monkeypatch: pytest.MonkeyPatch, path: str, media_type: str
) -> None:
    store, presentation, snapshot = _store(monkeypatch, PageRenderer())

    def serve(request: Request) -> Response:
        return render_file_response(store, "card", request.path_params["route"])

    app = Starlette(routes=[Route("/renders/{route:path}", serve)])
    try:
        bundle = asyncio.run(_render(store, presentation, snapshot, {}))
        with TestClient(app) as client:
            response = client.get(f"/renders/{bundle.id}/{path}")
    finally:
        store.close()

    assert response.status_code == 200
    assert response.headers["content-type"].startswith(media_type)
    assert response.headers["content-security-policy"] == "sandbox allow-scripts"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["cache-control"] == "private, max-age=31536000, immutable"
    assert response.headers["etag"].startswith('"sha256:')


def test_renders_of_one_revision_verify_its_template_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    renderer = CardRenderer(lambda values: f"Total {values['total']}")
    store, _presentation, snapshot = _store(monkeypatch, renderer)
    leases: list[str] = []

    def lease_artifact(_view: str, revision: str) -> _Lease:
        leases.append(revision)
        return _Lease()

    presentation = SimpleNamespace(lease_artifact=lease_artifact)

    async def exercise() -> None:
        for total in (1, 2, 3):
            await _render(store, presentation, snapshot, {"total": total})

    try:
        asyncio.run(exercise())
        assert renderer.calls == 3
        assert leases == ["sha256:card"]
    finally:
        store.close()
