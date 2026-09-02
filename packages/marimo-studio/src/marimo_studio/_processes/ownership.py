"""Finish asynchronous ownership mutations before propagating cancellation."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from typing import TypeVar, cast

_T = TypeVar("_T")


async def settle_ownership(
    operation: Awaitable[_T],
) -> tuple[_T, asyncio.CancelledError | None]:
    """Drain one ownership mutation and retain the first caller cancellation."""
    result, failure, cancellation = await settle_ownership_outcome(operation)
    if failure is not None:
        raise failure
    return cast(_T, result), cancellation


async def settle_ownership_outcome(
    operation: Awaitable[_T],
) -> tuple[_T | None, BaseException | None, asyncio.CancelledError | None]:
    """Drain one ownership mutation and return its terminal outcome."""
    task = asyncio.ensure_future(operation)
    cancellation: asyncio.CancelledError | None = None
    while True:
        try:
            result = await asyncio.shield(task)
            return result, None, cancellation
        except asyncio.CancelledError as error:
            if task.cancelled():
                raise
            if cancellation is None:
                cancellation = error
            if task.done():
                try:
                    return task.result(), None, cancellation
                except BaseException as failure:
                    return None, failure, cancellation
        except BaseException as failure:
            return None, failure, cancellation


def propagate_cancellation(cancellation: asyncio.CancelledError | None) -> None:
    """Raise a deferred cancellation after the owned state is coherent."""
    if cancellation is not None:
        raise cancellation
