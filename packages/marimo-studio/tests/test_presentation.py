from __future__ import annotations

import asyncio
import threading
from pathlib import Path

import pytest

from marimo_studio._server.presentation import NotebookPresentation

from .app_helpers import configured


def test_snapshot_capture_keeps_the_event_loop_responsive(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    studio = configured(notebook_path)
    presentation = NotebookPresentation(studio.notebook)
    capture_started = threading.Event()
    release_capture = threading.Event()
    native_snapshot = presentation.snapshot

    def slow_snapshot(view_name: str | None):
        capture_started.set()
        assert release_capture.wait(timeout=1)
        return native_snapshot(view_name)

    monkeypatch.setattr(presentation, "snapshot", slow_snapshot)

    async def exercise() -> None:
        capture = asyncio.create_task(presentation.snapshot_async("dashboard"))
        assert await asyncio.to_thread(capture_started.wait, 1)
        heartbeat = asyncio.Event()
        asyncio.get_running_loop().call_soon(heartbeat.set)
        await asyncio.wait_for(heartbeat.wait(), timeout=0.1)
        release_capture.set()
        snapshot = await asyncio.wait_for(capture, timeout=1)
        assert snapshot.view_name == "dashboard"

    asyncio.run(exercise())
