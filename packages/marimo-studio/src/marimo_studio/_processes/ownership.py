"""Finish asynchronous ownership mutations before propagating cancellation."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from typing import TypeVar

_T = TypeVar("_T")


async def settle_ownership(
    operation: Awaitable[_T],
) -> tuple[_T, asyncio.CancelledError | None]:
    """Drain one ownership mutation and retain the first caller cancellation."""
    task = asyncio.ensure_future(operation)
    cancellation: asyncio.CancelledError | None = None
    while True:
        try:
            result = await asyncio.shield(task)
            return result, cancellation
        except asyncio.CancelledError as error:
            if task.cancelled():
                raise
            if cancellation is None:
                cancellation = error
            if task.done():
                return task.result(), cancellation


def propagate_cancellation(cancellation: asyncio.CancelledError | None) -> None:
    """Raise a deferred cancellation after the owned state is coherent."""
    if cancellation is not None:
        raise cancellation
