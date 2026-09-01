"""Run synchronous provider work with async cancellation ownership."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence
from typing import TypeVar

from marimo_studio._processes.cancellation import (
    ProviderOperationControl,
    provider_cancellation,
)
from marimo_studio._processes.ownership import settle_ownership
from marimo_studio._processes.supervisor import ProcessCleanupError

_T = TypeVar("_T")


async def run_provider_operation(
    operation: Callable[[], _T],
    *,
    discard: Callable[[_T], None] | None = None,
) -> _T:
    """Cancel and drain provider work when its awaiting owner is cancelled."""
    control = ProviderOperationControl()

    def run() -> _T:
        with provider_cancellation(control):
            return operation()

    worker = asyncio.create_task(asyncio.to_thread(run))
    try:
        return await asyncio.shield(worker)
    except asyncio.CancelledError as cancellation:
        control.cancel()
        results, _repeated_cancellation = await settle_ownership(
            asyncio.gather(worker, return_exceptions=True)
        )
        result = results[0]
        if isinstance(result, BaseException):
            cleanup = find_process_cleanup_error(result)
            if cleanup is not None:
                raise cleanup from cancellation
        elif discard is not None:
            discard(result)
        raise cancellation


def find_process_cleanup_error(
    error: BaseException,
) -> ProcessCleanupError | None:
    """Return the terminal process cleanup failure from a wrapped exception."""
    pending = [error]
    seen: set[int] = set()
    while pending:
        current = pending.pop()
        identity = id(current)
        if identity in seen:
            continue
        seen.add(identity)
        if isinstance(current, ProcessCleanupError):
            return current
        if current.__cause__ is not None:
            pending.append(current.__cause__)
        if current.__context__ is not None:
            pending.append(current.__context__)
    return None


def process_cleanup_errors(
    results: Sequence[object],
) -> tuple[ProcessCleanupError, ...]:
    """Collect unique process cleanup failures from gathered task results."""
    errors: list[ProcessCleanupError] = []
    seen: set[int] = set()
    for result in results:
        if not isinstance(result, BaseException):
            continue
        error = find_process_cleanup_error(result)
        if error is not None and id(error) not in seen:
            seen.add(id(error))
            errors.append(error)
    return tuple(errors)


def raise_process_cleanup(error: BaseException) -> None:
    """Raise a wrapped process cleanup failure before fallback handling."""
    cleanup = find_process_cleanup_error(error)
    if cleanup is not None:
        if cleanup is error:
            raise cleanup
        raise cleanup from error
