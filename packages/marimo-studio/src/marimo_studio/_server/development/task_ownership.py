"""Run and drain cancellation-owned development tasks."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any, TypeVar

from marimo_studio._processes.provider_operation import find_process_cleanup_error
from marimo_studio.view_providers import ProviderCancellation

_T = TypeVar("_T")


async def drain_future(future: asyncio.Future[Any]) -> None:
    while not future.done():
        try:
            await asyncio.shield(future)
        except asyncio.CancelledError:
            continue
        except BaseException:
            break


async def run_owned_worker(
    control: ProviderCancellation,
    operation: Callable[[], _T],
) -> _T:
    worker = asyncio.create_task(asyncio.to_thread(operation))
    try:
        return await asyncio.shield(worker)
    except asyncio.CancelledError as cancellation:
        control.cancel()
        await drain_future(worker)
        if worker.done() and not worker.cancelled():
            try:
                worker.result()
            except BaseException as error:
                cleanup = find_process_cleanup_error(error)
                if cleanup is not None:
                    raise cleanup from cancellation
        raise cancellation
