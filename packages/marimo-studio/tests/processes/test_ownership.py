from __future__ import annotations

import asyncio

import pytest

from marimo_studio._processes.ownership import (
    propagate_cancellation,
    settle_ownership,
    settle_ownership_outcome,
)


def test_ownership_completion_returns_without_cancellation() -> None:
    async def exercise() -> None:
        async def operation() -> str:
            return "settled"

        result, cancellation = await settle_ownership(operation())

        assert result == "settled"
        assert cancellation is None

    asyncio.run(exercise())


def test_ownership_drains_through_repeated_caller_cancellation() -> None:
    async def exercise() -> None:
        entered = asyncio.Event()
        release = asyncio.Event()

        async def operation() -> str:
            entered.set()
            await release.wait()
            return "settled"

        settling = asyncio.create_task(settle_ownership(operation()))
        await asyncio.wait_for(entered.wait(), timeout=1)
        settling.cancel()
        await asyncio.sleep(0)
        settling.cancel()
        await asyncio.sleep(0)

        assert not settling.done()

        release.set()
        result, cancellation = await settling
        assert result == "settled"
        assert isinstance(cancellation, asyncio.CancelledError)

    asyncio.run(exercise())


def test_owned_task_cancellation_remains_terminal() -> None:
    async def exercise() -> None:
        entered = asyncio.Event()

        async def operation() -> None:
            entered.set()
            await asyncio.Future()

        owned = asyncio.create_task(operation())
        settling = asyncio.create_task(settle_ownership(owned))
        await asyncio.wait_for(entered.wait(), timeout=1)
        owned.cancel()

        with pytest.raises(asyncio.CancelledError):
            await settling

    asyncio.run(exercise())


def test_owned_failure_wins_after_caller_cancellation() -> None:
    async def exercise() -> None:
        entered = asyncio.Event()
        release = asyncio.Event()

        async def operation() -> None:
            entered.set()
            await release.wait()
            raise OSError("owned cleanup failed")

        settling = asyncio.create_task(settle_ownership(operation()))
        await asyncio.wait_for(entered.wait(), timeout=1)
        settling.cancel()
        await asyncio.sleep(0)
        release.set()

        with pytest.raises(OSError, match="owned cleanup failed"):
            await settling

    asyncio.run(exercise())


def test_ownership_outcome_retains_failure_and_cancellation() -> None:
    async def exercise() -> None:
        entered = asyncio.Event()
        release = asyncio.Event()

        async def operation() -> None:
            entered.set()
            await release.wait()
            raise OSError("owned cleanup failed")

        settling = asyncio.create_task(settle_ownership_outcome(operation()))
        await asyncio.wait_for(entered.wait(), timeout=1)
        settling.cancel()
        await asyncio.sleep(0)
        release.set()

        result, failure, cancellation = await settling
        assert result is None
        assert isinstance(failure, OSError)
        assert str(failure) == "owned cleanup failed"
        assert isinstance(cancellation, asyncio.CancelledError)

    asyncio.run(exercise())


def test_cancellation_propagates_after_owned_state_settles() -> None:
    cancellation = asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError) as raised:
        propagate_cancellation(cancellation)

    assert raised.value is cancellation
