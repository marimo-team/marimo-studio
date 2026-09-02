"""Protect cleanup ownership for work tied to an HTTP request."""

from __future__ import annotations

import asyncio
from typing import Any, cast

import pytest
from starlette.requests import Request

from marimo_studio._server.request_lifecycle import (
    RequestCleanupError,
    run_while_connected,
)


class _Peer:
    def __init__(self) -> None:
        self.messages: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

    async def receive(self) -> dict[str, Any]:
        return await self.messages.get()


def test_request_cancellation_drains_cleanup_through_repeated_cancellation() -> None:
    async def exercise() -> None:
        peer = _Peer()
        started = asyncio.Event()
        cleaning = asyncio.Event()
        release = asyncio.Event()
        cleaned = asyncio.Event()

        async def operation() -> None:
            started.set()
            try:
                await asyncio.Future()
            finally:
                cleaning.set()
                await release.wait()
                cleaned.set()

        running = asyncio.create_task(
            run_while_connected(cast(Request, peer), operation())
        )
        await asyncio.wait_for(started.wait(), timeout=1)
        running.cancel()
        await asyncio.wait_for(cleaning.wait(), timeout=1)
        running.cancel()
        await asyncio.sleep(0)
        assert not running.done()

        release.set()
        with pytest.raises(asyncio.CancelledError):
            await running
        assert cleaned.is_set()

    asyncio.run(exercise())


def test_disconnect_surfaces_operation_cleanup_failure() -> None:
    async def exercise() -> None:
        peer = _Peer()
        started = asyncio.Event()

        async def operation() -> None:
            started.set()
            try:
                await asyncio.Future()
            finally:
                raise OSError("operation cleanup failed")

        running = asyncio.create_task(
            run_while_connected(cast(Request, peer), operation())
        )
        await asyncio.wait_for(started.wait(), timeout=1)
        await peer.messages.put({"type": "http.disconnect"})
        with pytest.raises(RequestCleanupError) as raised:
            await running
        assert len(raised.value.errors) == 1
        assert str(raised.value.errors[0]) == "operation cleanup failed"

    asyncio.run(exercise())


def test_operation_failure_remains_the_primary_result() -> None:
    async def exercise() -> None:
        peer = _Peer()

        async def operation() -> None:
            raise ValueError("operation failed")

        with pytest.raises(ValueError, match="operation failed"):
            await run_while_connected(cast(Request, peer), operation())

    asyncio.run(exercise())
