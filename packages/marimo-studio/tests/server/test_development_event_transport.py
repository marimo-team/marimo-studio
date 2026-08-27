from __future__ import annotations

import asyncio
from typing import Any, cast

import pytest

from marimo_studio._server.development import routes as dev
from marimo_studio._server.support import (
    StreamingResponseCleanupError,
    _OwnedStreamingResponse,
)


async def _disconnect_after_first_body(response: _OwnedStreamingResponse) -> None:
    body_sent = asyncio.Event()

    async def send(message: dict[str, object]) -> None:
        if message["type"] == "http.response.body":
            body_sent.set()

    async def receive() -> dict[str, object]:
        await body_sent.wait()
        return {"type": "http.disconnect"}

    await response(
        cast(
            Any,
            {
                "type": "http",
                "asgi": {"spec_version": "2.4"},
            },
        ),
        cast(Any, receive),
        cast(Any, send),
    )


def test_event_broker_bounds_control_and_coalesced_state() -> None:
    async def exercise() -> None:
        broker = dev._EventBroker(control_limit=2)
        await broker.emit_control(b"control-1")
        await broker.emit_control(b"control-2")
        blocked_started = asyncio.Event()

        async def emit_blocked_control() -> None:
            blocked_started.set()
            await broker.emit_control(b"control-3")

        blocked = asyncio.create_task(emit_blocked_control())
        await asyncio.wait_for(blocked_started.wait(), timeout=1)
        assert not blocked.done()

        assert await broker.receive() == b"control-1"
        await blocked
        assert await broker.receive() == b"control-2"
        assert await broker.receive() == b"control-3"

        for generation in range(2_000):
            await broker.emit_source(
                "dashboard",
                "project",
                generation,
                b"source-detail",
                b"source-resync",
            )
            await broker.emit_publication(
                "dashboard",
                "build",
                generation,
                f"build-{generation}".encode(),
            )
        await broker.emit_heartbeat(b": keepalive\n\n")

        assert broker.retained_events <= 3
        assert await broker.receive() == b"source-resync"
        assert await broker.receive() == b"build-1999"
        assert await broker.receive() == b": keepalive\n\n"

    asyncio.run(exercise())


def test_event_broker_heartbeat_resets_the_idle_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def exercise() -> None:
        broker = dev._EventBroker()
        heartbeat_time = broker.last_activity + dev._HEARTBEAT_INTERVAL
        monkeypatch.setattr(dev.time, "monotonic", lambda: heartbeat_time)

        await broker.emit_heartbeat(b": keepalive\n\n")

        assert broker.last_activity == heartbeat_time
        assert await broker.receive() == b": keepalive\n\n"

    asyncio.run(exercise())


def test_streaming_response_closes_its_event_owner_after_delivery_failure() -> None:
    async def exercise() -> bool:
        closed = False

        async def events():
            nonlocal closed
            try:
                yield b"event: ready\n\n"
                await asyncio.Future()
            finally:
                closed = True

        async def send(message: dict[str, object]) -> None:
            if message["type"] == "http.response.body":
                raise OSError("client disconnected")

        response = _OwnedStreamingResponse(events())
        with pytest.raises(OSError, match="client disconnected"):
            await response.stream_response(cast(Any, send))
        return closed

    assert asyncio.run(exercise())


def test_streaming_response_closes_its_owner_on_asgi_disconnect() -> None:
    async def exercise() -> bool:
        closed = False

        async def events():
            nonlocal closed
            try:
                yield b"event: ready\n\n"
                await asyncio.Future()
            finally:
                closed = True

        response = _OwnedStreamingResponse(events())
        await _disconnect_after_first_body(response)
        return closed

    assert asyncio.run(exercise())


def test_streaming_response_reports_owner_failure_on_asgi_disconnect() -> None:
    async def exercise() -> None:
        async def events():
            try:
                yield b"event: ready\n\n"
                await asyncio.Future()
            finally:
                raise OSError("event owner close failed")

        response = _OwnedStreamingResponse(events())
        with pytest.raises(
            StreamingResponseCleanupError,
            match="event owner close failed",
        ):
            await _disconnect_after_first_body(response)

    asyncio.run(exercise())
