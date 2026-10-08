from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import time
from pathlib import Path, PurePosixPath
from types import SimpleNamespace
from typing import Any

import pytest

import marimo_studio._server.presentation.document_renders as renders_module
from marimo_studio._server.presentation.document_renders import (
    DocumentRenders,
    RenderUnavailable,
)
from marimo_studio.view_providers import BuildResult, RenderRequest
from marimo_studio.view_providers._host.registry import ProviderRegistry

from ..provider_test_support import ProviderStub, candidate

pytestmark = pytest.mark.native_process

TEMPLATE = PurePosixPath("card.txt")

# The provider command records its PID, then outlives any reasonable test, so
# only render cancellation can stop it.
_SLOW_COMMAND = (
    "import os, pathlib, sys, time; "
    "pathlib.Path(sys.argv[1]).write_text(str(os.getpid())); "
    "time.sleep(60)"
)


class SlowRenderer(ProviderStub):
    def __init__(self, marker: Path) -> None:
        super().__init__("test-slow/card", "default")
        self.marker = marker

    def render(self, request: RenderRequest) -> BuildResult:
        request.runner.run(
            [sys.executable, "-c", _SLOW_COMMAND, str(self.marker)],
            cwd=request.template_root,
            timeout=120,
        )
        return BuildResult(None, ())


class _Lease:
    def __enter__(self) -> _Lease:
        return self

    def __exit__(self, *_error: object) -> None:
        return None

    def copy_template(self, destination: Path) -> None:
        destination.mkdir()
        destination.joinpath(TEMPLATE).write_text("Card", encoding="utf-8")


def _pid_is_live(pid: int) -> bool:
    result = subprocess.run(
        ["ps", "-o", "stat=", "-p", str(pid)],
        check=False,
        capture_output=True,
        text=True,
    )
    state = result.stdout.strip()
    return bool(state) and not state.startswith("Z")


def _render_owner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[DocumentRenders, Any, Any, Path]:
    marker = tmp_path / "render-pid"
    registry = ProviderRegistry(
        (candidate("card", SlowRenderer(marker), distribution="test-slow"),)
    )
    monkeypatch.setattr(renders_module, "provider_registry", lambda: registry)
    presentation = SimpleNamespace(lease_artifact=lambda _view, _revision: _Lease())
    snapshot = SimpleNamespace(
        view_name="card",
        artifact=SimpleNamespace(
            artifact_revision="sha256:card",
            template=SimpleNamespace(document=TEMPLATE),
            provider=SimpleNamespace(key=registry.ids[0]),
        ),
    )
    return DocumentRenders(), presentation, snapshot, marker


async def _started(marker: Path) -> int:
    deadline = time.monotonic() + 15
    while not marker.is_file() or not marker.read_text(encoding="utf-8"):
        assert time.monotonic() < deadline, "The provider command never started"
        await asyncio.sleep(0.02)
    return int(marker.read_text(encoding="utf-8"))


@pytest.mark.skipif(os.name == "nt", reason="ps reports POSIX process state")
def test_a_cancelled_render_stops_its_provider_command_before_returning(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    renders, presentation, snapshot, marker = _render_owner(tmp_path, monkeypatch)

    async def exercise() -> int:
        render = asyncio.create_task(
            renders.render(presentation, snapshot, {"total": 1}, {}, {})
        )
        pid = await _started(marker)
        render.cancel()
        with pytest.raises(asyncio.CancelledError):
            await render
        return pid

    try:
        pid = asyncio.run(exercise())
        assert not _pid_is_live(pid)
    finally:
        renders.close()


@pytest.mark.skipif(os.name == "nt", reason="ps reports POSIX process state")
def test_closing_the_render_owner_stops_active_renders(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    renders, presentation, snapshot, marker = _render_owner(tmp_path, monkeypatch)

    async def exercise() -> int:
        render = asyncio.create_task(
            renders.render(presentation, snapshot, {"total": 1}, {}, {})
        )
        pid = await _started(marker)
        await asyncio.to_thread(renders.close)
        with pytest.raises(RenderUnavailable):
            await render
        return pid

    pid = asyncio.run(exercise())

    assert not _pid_is_live(pid)
