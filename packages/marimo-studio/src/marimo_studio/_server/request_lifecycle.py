"""Tie long-running server work to the lifetime of its HTTP request."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Coroutine
from typing import Any, TypeVar, cast

from starlette.requests import Request

from marimo_studio._processes.ownership import (
    propagate_cancellation,
    settle_ownership,
)

_T = TypeVar("_T")


class RequestDisconnected(Exception):
    """Signal that the client closed its request before work completed."""


class RequestCleanupError(Exception):
    """Report failures raised while request-owned tasks were stopping."""

    def __init__(self, errors: tuple[Exception, ...]) -> None:
        self.errors = errors
        super().__init__(
            "Request cleanup failed: " + ", ".join(str(error) for error in errors)
        )


async def run_while_connected(
    request: Request,
    operation: Coroutine[Any, Any, _T],
) -> _T:
    """Run an operation and cancel it when the request peer disconnects."""
    disconnect_task = asyncio.create_task(_wait_for_disconnect(request))
    operation_task: asyncio.Task[_T] | None = None
    observed: set[asyncio.Task[Any]] = set()
    try:
        # Let an already queued disconnect win before starting expensive work.
        await asyncio.sleep(0)
        if disconnect_task.done():
            observed.add(disconnect_task)
            await disconnect_task
            raise RequestDisconnected
        operation_task = asyncio.create_task(operation)
        done, _pending = await asyncio.wait(
            (operation_task, disconnect_task),
            return_when=asyncio.FIRST_COMPLETED,
        )
        if operation_task in done:
            observed.add(operation_task)
            return await operation_task
        observed.add(disconnect_task)
        await disconnect_task
        operation_task.cancel()
        raise RequestDisconnected
    finally:
        if operation_task is None:
            operation.close()
        tasks: tuple[asyncio.Task[Any], ...] = (
            (disconnect_task,)
            if operation_task is None
            else (operation_task, disconnect_task)
        )
        for task in tasks:
            if not task.done():
                task.cancel()
        awaitables = cast(tuple[Awaitable[Any], ...], tasks)
        results, cancellation = await settle_ownership(
            asyncio.gather(*awaitables, return_exceptions=True)
        )
        errors = tuple(
            result
            for task, result in zip(tasks, results, strict=True)
            if task not in observed and isinstance(result, Exception)
        )
        if errors:
            error = RequestCleanupError(errors)
            if cancellation is not None:
                raise error from cancellation
            raise error
        propagate_cancellation(cancellation)


async def _wait_for_disconnect(request: Request) -> None:
    while True:
        message = await request.receive()
        if message["type"] == "http.disconnect":
            return
