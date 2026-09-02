from __future__ import annotations

import asyncio
import hashlib
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

import marimo_studio._server.runtime.catalog as catalog_module
from marimo_studio._delivery.browser_ports import (
    BrowserRuntimeCell,
    BrowserRuntimeProjection,
)
from marimo_studio._notebook.records import CellRef, LiveCellSnapshot
from marimo_studio._server.ports import SessionState
from marimo_studio._server.presentation.service import PresentationSnapshot
from marimo_studio._server.records import ServerContext, ServerHandle
from marimo_studio._server.runtime.catalog import (
    RuntimeEvidenceProjection,
    RuntimeProjection,
    RuntimeProvider,
    RuntimeRegistry,
    ServerRuntime,
    WasmRuntime,
)
from marimo_studio.errors._internal import RuntimeSyncError


def _snapshot(
    tmp_path: Path,
    *,
    runtime: str = "server",
    source: str = "value = 1\n",
) -> PresentationSnapshot:
    reference = CellRef("0" * 64, "1" * 64)
    cell = SimpleNamespace(runtime_id="runtime-cell", ref=reference)
    workspace = SimpleNamespace(
        notebook=tmp_path / "notebook.py",
        default_runtime=runtime,
        preserve_session=False,
        runtimes=(runtime,),
    )
    resolved = SimpleNamespace(
        notebook=SimpleNamespace(cells=(cell,)),
        runtime_cell_refs=lambda _cells: {str(reference): cell.runtime_id},
        workspace=workspace,
    )
    symbols = SimpleNamespace(
        cells=(reference,),
        dependency_closure=lambda _producer: (reference,),
    )
    return cast(
        PresentationSnapshot,
        SimpleNamespace(
            resolved=resolved,
            symbols=symbols,
            notebook_source=source,
            revision=hashlib.sha256(source.encode()).hexdigest(),
        ),
    )


def _context(tmp_path: Path) -> ServerContext:
    return ServerContext(
        notebook=tmp_path / "notebook.py",
        file_key="notebook.py",
        base_url="",
        mode="run",
        dev=False,
        routing_query=(),
        user_config={},
        config_overrides={},
        server_token="test-token",
        handle=ServerHandle(object()),
    )


class _BlockingBrowser:
    version = "1.0.0"
    commit = "release"

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.started = threading.Event()
        self.release = threading.Event()

    def project(self, notebook: Path, source: str) -> BrowserRuntimeProjection:
        del notebook
        self.calls.append(source)
        if len(self.calls) == 1:
            self.started.set()
            assert self.release.wait(timeout=3)
        return BrowserRuntimeProjection(
            instance=hashlib.sha256(source.encode()).hexdigest(),
            version=self.version,
            commit=self.commit,
            code=source,
            execution_cells=(BrowserRuntimeCell("cell", source),),
            bootstrap_cell_id="cell",
        )


def test_runtime_config_skips_evidence_dependency_closures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    flags: list[bool] = []
    closure_builds = 0

    class RecordingSessions:
        async def live_cells(
            self,
            _context: ServerContext,
            _session_id: str | None,
            *,
            include_dependency_closures: bool,
        ) -> LiveCellSnapshot | None:
            flags.append(include_dependency_closures)
            return None

    original = catalog_module._static_dependency_closures

    def count_closures(
        snapshot: PresentationSnapshot,
        bindings: dict[str, str],
    ) -> dict[str, tuple[str, ...]]:
        nonlocal closure_builds
        closure_builds += 1
        return original(snapshot, bindings)

    monkeypatch.setattr(catalog_module, "_static_dependency_closures", count_closures)
    monkeypatch.setattr(
        catalog_module,
        "presentation_revision_url",
        lambda *_args, **_kwargs: "/",
    )
    monkeypatch.setattr(
        catalog_module,
        "presentation_revision_capability",
        lambda *_args: "capability",
    )
    runtime = ServerRuntime(cast(SessionState, RecordingSessions()))
    snapshot = _snapshot(tmp_path)
    context = _context(tmp_path)

    asyncio.run(
        runtime.project(snapshot, context, None, None, "presentation", "runtime")
    )
    assert flags == [False]
    assert closure_builds == 0

    asyncio.run(
        runtime.project_evidence(
            snapshot,
            context,
            None,
            None,
            "presentation",
            "runtime",
        )
    )
    assert flags == [False, True]
    assert closure_builds == 1


def test_runtime_registry_runs_provider_on_the_event_loop_owner(
    tmp_path: Path,
) -> None:
    projection_threads: list[int] = []
    evidence_threads: list[int] = []

    class RecordingProvider:
        id = "server"
        label = "Python"

        async def project(self, *_args: object) -> RuntimeProjection:
            projection_threads.append(threading.get_ident())
            return RuntimeProjection("server", "instance", {}, {})

        async def project_evidence(
            self,
            *_args: object,
        ) -> RuntimeEvidenceProjection:
            evidence_threads.append(threading.get_ident())
            return RuntimeEvidenceProjection("server", "instance", {}, {}, {}, {})

    provider = RecordingProvider()
    registry = RuntimeRegistry((cast(RuntimeProvider, provider),))
    snapshot = _snapshot(tmp_path)
    context = _context(tmp_path)

    async def exercise() -> int:
        event_loop_thread = threading.get_ident()
        await registry.project(snapshot, context, None, None)
        await registry.project_evidence(snapshot, context, None, None)
        return event_loop_thread

    event_loop_thread = asyncio.run(exercise())

    assert len(projection_threads) == 1
    assert len(evidence_threads) == 1
    assert projection_threads[0] == event_loop_thread
    assert evidence_threads[0] == event_loop_thread


def test_server_runtime_instance_stays_stable_across_binding_generations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reference = CellRef("0" * 64, "1" * 64)
    captures = iter(
        (
            LiveCellSnapshot(
                owner="session:first",
                generation="1" * 64,
                ids={reference: "runtime-cell"},
                names={},
                dependency_closures={},
                current_refs={"runtime-cell": reference},
            ),
            LiveCellSnapshot(
                owner="session:first",
                generation="2" * 64,
                ids={reference: "runtime-cell"},
                names={},
                dependency_closures={},
                current_refs={"runtime-cell": reference},
            ),
        )
    )

    class Sessions:
        async def live_cells(self, *_args: object, **_kwargs: object):
            return next(captures)

    monkeypatch.setattr(
        catalog_module,
        "presentation_revision_url",
        lambda *_args, **_kwargs: "/",
    )
    monkeypatch.setattr(
        catalog_module,
        "presentation_revision_capability",
        lambda *_args: "capability",
    )
    runtime = ServerRuntime(cast(SessionState, Sessions()))
    snapshot = _snapshot(tmp_path)
    context = _context(tmp_path)

    async def exercise() -> tuple[RuntimeProjection, RuntimeProjection]:
        first = await runtime.project(
            snapshot,
            context,
            "s_123456",
            "binding",
            "presentation",
            "runtime",
        )
        second = await runtime.project(
            snapshot,
            context,
            "s_123456",
            "binding",
            "presentation",
            "runtime",
        )
        return first, second

    first, second = asyncio.run(exercise())

    assert first.cell_refs == second.cell_refs
    assert first.instance == second.instance


def test_wasm_projection_burst_builds_the_running_and_latest_revision(
    tmp_path: Path,
) -> None:
    browser = _BlockingBrowser()
    registry = RuntimeRegistry((WasmRuntime(browser),))
    context = _context(tmp_path)

    async def project(source: str) -> RuntimeProjection:
        return await registry.project(
            _snapshot(tmp_path, runtime="wasm", source=source),
            context,
            "wasm",
            None,
            None,
            "presentation",
            "runtime",
        )

    async def exercise() -> list[BaseException | RuntimeProjection]:
        tasks = [asyncio.create_task(project("A"))]
        assert await asyncio.to_thread(browser.started.wait, 1)
        for source in ("B", "C", "D"):
            tasks.append(asyncio.create_task(project(source)))
            await asyncio.sleep(0)
        browser.release.set()
        return await asyncio.gather(*tasks, return_exceptions=True)

    try:
        results = asyncio.run(exercise())
    finally:
        browser.release.set()

    assert browser.calls == ["A", "D"]
    assert all(isinstance(result, RuntimeSyncError) for result in results[:-1])
    assert isinstance(results[-1], RuntimeProjection)
    assert results[-1].data["code"] == "D"


def test_cancelled_wasm_projection_burst_drops_obsolete_queued_builds(
    tmp_path: Path,
) -> None:
    browser = _BlockingBrowser()
    registry = RuntimeRegistry((WasmRuntime(browser),))
    context = _context(tmp_path)

    async def project(source: str) -> RuntimeProjection:
        return await registry.project(
            _snapshot(tmp_path, runtime="wasm", source=source),
            context,
            "wasm",
            None,
            None,
            "presentation",
            "runtime",
        )

    async def exercise() -> RuntimeProjection:
        first = asyncio.create_task(project("A"))
        assert await asyncio.to_thread(browser.started.wait, 1)
        first.cancel()
        await asyncio.gather(first, return_exceptions=True)
        for source in ("B", "C", "D"):
            stale = asyncio.create_task(project(source))
            await asyncio.sleep(0)
            stale.cancel()
            await asyncio.gather(stale, return_exceptions=True)
        latest = asyncio.create_task(project("Z"))
        await asyncio.sleep(0)
        browser.release.set()
        return await latest

    try:
        result = asyncio.run(exercise())
    finally:
        browser.release.set()

    assert browser.calls == ["A", "Z"]
    assert result.data["code"] == "Z"


def test_wasm_runtime_close_drains_the_active_projection(
    tmp_path: Path,
) -> None:
    browser = _BlockingBrowser()
    runtime = WasmRuntime(browser)
    context = _context(tmp_path)
    snapshot = _snapshot(tmp_path, runtime="wasm", source="A")

    async def exercise() -> None:
        projection = asyncio.create_task(
            runtime.project(
                snapshot,
                context,
                None,
                None,
                "presentation",
                "runtime",
            )
        )
        assert await asyncio.to_thread(browser.started.wait, 1)
        closing = asyncio.create_task(runtime.close())
        await asyncio.sleep(0)
        assert not closing.done()
        browser.release.set()
        await closing
        result = await asyncio.gather(projection, return_exceptions=True)
        assert isinstance(result[0], RuntimeSyncError)
        with pytest.raises(RuntimeSyncError, match="shutting down"):
            await runtime.project(
                snapshot,
                context,
                None,
                None,
                "presentation",
                "runtime",
            )

    try:
        asyncio.run(exercise())
    finally:
        browser.release.set()


def test_runtime_registry_close_rejects_an_inflight_server_capture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = asyncio.Event()
    release = asyncio.Event()

    class Sessions:
        async def live_cells(self, *_args: object, **_kwargs: object):
            started.set()
            await release.wait()
            return None

    monkeypatch.setattr(
        catalog_module,
        "presentation_revision_url",
        lambda *_args, **_kwargs: "/",
    )
    monkeypatch.setattr(
        catalog_module,
        "presentation_revision_capability",
        lambda *_args: "capability",
    )
    registry = RuntimeRegistry((ServerRuntime(cast(SessionState, Sessions())),))
    snapshot = _snapshot(tmp_path)
    context = _context(tmp_path)

    async def project() -> RuntimeProjection:
        return await registry.project(
            snapshot,
            context,
            "server",
            "s_123456",
            "binding",
            "presentation",
            "runtime",
        )

    async def exercise() -> None:
        projection = asyncio.create_task(project())
        await started.wait()
        await registry.close()
        release.set()
        result = await asyncio.gather(projection, return_exceptions=True)
        assert isinstance(result[0], RuntimeSyncError)
        with pytest.raises(RuntimeSyncError, match="shutting down"):
            await project()

    asyncio.run(exercise())
