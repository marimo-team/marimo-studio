"""Tie long-running server work to the lifetime of its HTTP request."""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from typing import Any, TypeVar

from starlette.requests import Request

_T = TypeVar("_T")


class RequestDisconnected(Exception):
    """Signal that the client closed its request before work completed."""


async def run_while_connected(
    request: Request,
    operation: Coroutine[Any, Any, _T],
) -> _T:
    """Run an operation and cancel it when the request peer disconnects."""
    disconnect_task = asyncio.create_task(_wait_for_disconnect(request))
    operation_task: asyncio.Task[_T] | None = None
    try:
        # Let an already queued disconnect win before starting expensive work.
        await asyncio.sleep(0)
        if disconnect_task.done():
            await disconnect_task
            raise RequestDisconnected
        operation_task = asyncio.create_task(operation)
        done, _pending = await asyncio.wait(
            (operation_task, disconnect_task),
            return_when=asyncio.FIRST_COMPLETED,
        )
        if operation_task in done:
            return await operation_task
        await disconnect_task
        operation_task.cancel()
        raise RequestDisconnected
    finally:
        if operation_task is None:
            operation.close()
        tasks = (
            (disconnect_task,)
            if operation_task is None
            else (operation_task, disconnect_task)
        )
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(
            *tasks,
            return_exceptions=True,
        )


async def _wait_for_disconnect(request: Request) -> None:
    while True:
        message = await request.receive()
        if message["type"] == "http.disconnect":
            return


__all__ = ["RequestDisconnected", "run_while_connected"]
