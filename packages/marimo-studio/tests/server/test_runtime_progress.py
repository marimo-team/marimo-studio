from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, cast

import pytest
from marimo_export.progress import ProgressEvent
from starlette.responses import JSONResponse, Response
from starlette.testclient import TestClient

import marimo_studio._delivery.runtime_config as runtime_config_module
from marimo_studio import create_asgi_app
from marimo_studio._server.prepared_progress import PreparedProgress
from marimo_studio._server.runtime.progress import RuntimeProgress, RuntimeProgressSink
from marimo_studio._server.runtime.stream import runtime_config_stream
from marimo_studio.errors import PublicationError

from ..app_helpers import configured
from ..async_test_support import wait_for_event


def test_prepared_progress_counts_reused_and_captured_states() -> None:
    updates: list[RuntimeProgress] = []
    progress = PreparedProgress(updates.append)

    for event in (
        ProgressEvent(kind="inspection_started"),
        ProgressEvent(kind="plan_ready", completed=2, total=4),
        ProgressEvent(kind="state_started", completed=0, total=2, state="small"),
        ProgressEvent(kind="state_finished", completed=1, total=2, state="small"),
        ProgressEvent(kind="state_started", completed=1, total=2, state="large"),
        ProgressEvent(kind="state_finished", completed=2, total=2, state="large"),
        ProgressEvent(kind="prepared_committed", completed=4, total=4),
    ):
        progress(event)

    assert updates[0].to_dict() == {"message": "Inspecting notebook states"}
    assert [(value.completed, value.total) for value in updates[1:]] == [
        (None, None),
        (2, 4),
        (3, 4),
        (3, 4),
        (None, None),
        (None, None),
    ]
    assert updates[-1].message == "Notebook states prepared"
    assert updates[-2].message == "Finalizing prepared notebook states"


def test_prepared_progress_reports_cached_completion() -> None:
    updates: list[RuntimeProgress] = []
    progress = PreparedProgress(updates.append)

    progress(ProgressEvent(kind="plan_ready", completed=3, total=3))
    progress(ProgressEvent(kind="prepared_reused", completed=3, total=3))

    assert updates == [
        RuntimeProgress("Checking cached notebook states"),
        RuntimeProgress("Reusing prepared notebook states"),
    ]


def test_runtime_stream_delivers_progress_before_configuration_and_detaches() -> None:
    retained: list[RuntimeProgressSink] = []

    async def exercise() -> None:
        finish = asyncio.Event()

        async def configuration(progress: RuntimeProgressSink) -> Response:
            retained.append(progress)
            await asyncio.to_thread(progress, RuntimeProgress("Capturing states", 1, 3))
            await finish.wait()
            return JSONResponse({"runtime": {"id": "zero-python"}})

        response = runtime_config_stream(configuration)
        events = cast(AsyncIterator[bytes], response.body_iterator)
        first = json.loads(await asyncio.wait_for(anext(events), timeout=2))
        assert first == {
            "type": "progress",
            "progress": {"message": "Capturing states", "completed": 1, "total": 3},
        }
        finish.set()
        terminal = json.loads(await asyncio.wait_for(anext(events), timeout=2))
        assert terminal == {
            "type": "config",
            "config": {"runtime": {"id": "zero-python"}},
        }
        with pytest.raises(StopAsyncIteration):
            await anext(events)

    asyncio.run(exercise())
    retained[0](RuntimeProgress("Background publication refresh"))


def test_runtime_stream_coalesces_progress_for_a_slow_reader() -> None:
    async def exercise() -> None:
        first_read = asyncio.Event()

        async def configuration(progress: RuntimeProgressSink) -> Response:
            progress(RuntimeProgress("Starting"))
            await first_read.wait()
            for completed in range(1001):
                progress(RuntimeProgress("Capturing states", completed, 1000))
            return JSONResponse({"runtime": {"id": "zero-python"}})

        events = cast(
            AsyncIterator[bytes], runtime_config_stream(configuration).body_iterator
        )
        await anext(events)
        first_read.set()
        remaining = [json.loads(event) async for event in events]
        assert remaining == [
            {
                "type": "progress",
                "progress": {
                    "message": "Capturing states",
                    "completed": 1000,
                    "total": 1000,
                },
            },
            {"type": "config", "config": {"runtime": {"id": "zero-python"}}},
        ]

    asyncio.run(exercise())


@pytest.mark.parametrize("failure", ["public", "unexpected", "superseded"])
def test_runtime_stream_terminates_with_an_error(failure: str) -> None:
    async def exercise() -> list[dict[str, Any]]:
        async def configuration(_progress: RuntimeProgressSink) -> Response:
            if failure == "public":
                raise PublicationError("A configured state could not be captured")
            if failure == "superseded":
                raise asyncio.CancelledError
            raise ValueError("private implementation detail")

        events = cast(
            AsyncIterator[bytes], runtime_config_stream(configuration).body_iterator
        )
        return [json.loads(event) async for event in events]

    messages = asyncio.run(exercise())
    assert len(messages) == 1
    assert messages[0]["type"] == "error"
    if failure == "public":
        assert messages[0]["error"] == PublicationError.code
        assert messages[0]["message"] == "A configured state could not be captured"
    elif failure == "superseded":
        assert messages[0]["error"] == "runtime-sync-pending"
        assert messages[0]["transient"] is True
    else:
        assert messages[0]["error"] == "runtime-config-failed"
        assert messages[0]["message"] == "The runtime could not start."


def test_disconnecting_the_runtime_stream_cancels_and_settles_preparation() -> None:
    retained: list[RuntimeProgressSink] = []

    async def exercise() -> None:
        body_sent = asyncio.Event()
        stopped = asyncio.Event()

        async def configuration(progress: RuntimeProgressSink) -> Response:
            retained.append(progress)
            progress(RuntimeProgress("Capturing states", 1, 3))
            try:
                await asyncio.Event().wait()
            finally:
                await asyncio.to_thread(progress, RuntimeProgress("Releasing capture"))
                stopped.set()
            raise AssertionError("Preparation should end on disconnect")

        async def send(message: dict[str, object]) -> None:
            if message["type"] == "http.response.body":
                body_sent.set()

        async def receive() -> dict[str, object]:
            await wait_for_event(body_sent)
            return {"type": "http.disconnect"}

        await asyncio.wait_for(
            runtime_config_stream(configuration)(
                cast(Any, {"type": "http", "asgi": {"spec_version": "2.4"}}),
                cast(Any, receive),
                cast(Any, send),
            ),
            timeout=2,
        )
        assert stopped.is_set()

    asyncio.run(exercise())
    retained[0](RuntimeProgress("Background publication refresh"))


def test_runtime_config_negotiates_streaming(notebook_path: Path) -> None:
    studio = configured(notebook_path)
    with TestClient(create_asgi_app(studio.notebook)) as client:
        response = client.get(
            "/_marimo-studio/views/dashboard/config",
            headers={"Accept": "application/x-ndjson"},
        )

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/x-ndjson"
    messages = [json.loads(line) for line in response.text.splitlines()]
    assert messages[0] == {
        "type": "progress",
        "progress": {"message": "Connecting to Python"},
    }
    assert messages[-1]["type"] == "config"
    assert messages[-1]["config"]["runtime"]["id"] == "server"


def test_runtime_config_stream_preserves_configuration_size_errors(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    studio = configured(notebook_path)
    monkeypatch.setattr(runtime_config_module, "RUNTIME_CONFIG_MAX_BYTES", 1)

    with TestClient(create_asgi_app(studio.notebook)) as client:
        response = client.get(
            "/_marimo-studio/views/dashboard/config",
            headers={"Accept": "application/x-ndjson"},
        )

    terminal = json.loads(response.text.splitlines()[-1])
    assert response.status_code == 200
    assert terminal["type"] == "error"
    assert terminal["error"] == "runtime-config-too-large"
    assert terminal["max_bytes"] == 1
    assert terminal["bytes"] > 1
