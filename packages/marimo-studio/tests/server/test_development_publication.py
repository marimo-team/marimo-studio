from __future__ import annotations

import asyncio
import threading
from typing import Any

import pytest

from marimo_studio._processes.cancellation import current_provider_cancellation
from marimo_studio._server.development.coordinator import DevelopmentCoordinator


def test_two_subscribers_share_one_publication_task() -> None:
    calls = 0
    publication_started = threading.Event()
    release = threading.Event()

    def publish() -> str:
        nonlocal calls
        calls += 1
        publication_started.set()
        assert release.wait(timeout=2)
        return "published"

    async def exercise() -> tuple[str, str]:
        coordinator = DevelopmentCoordinator()
        first = asyncio.create_task(coordinator.publish("dashboard", 1, publish))
        assert await asyncio.to_thread(publication_started.wait, 1)
        second_started = asyncio.Event()

        async def join_publication() -> str:
            second_started.set()
            return await coordinator.publish("dashboard", 1, publish)

        second = asyncio.create_task(join_publication())
        await asyncio.wait_for(second_started.wait(), timeout=1)
        release.set()
        try:
            result = await asyncio.gather(first, second)
            return result[0], result[1]
        finally:
            await coordinator.close()

    assert asyncio.run(exercise()) == ("published", "published")
    assert calls == 1


def test_publication_profiles_keep_distinct_result_namespaces() -> None:
    development_started = threading.Event()
    production_started = threading.Event()
    release = threading.Event()

    def development_operation() -> tuple[str, str]:
        development_started.set()
        assert release.wait(timeout=2)
        return "development", "event"

    def production_operation() -> dict[str, str]:
        production_started.set()
        assert release.wait(timeout=2)
        return {"profile": "production"}

    async def exercise() -> tuple[tuple[str, str], dict[str, str]]:
        coordinator = DevelopmentCoordinator()
        development = asyncio.create_task(
            coordinator.publish("dashboard", 3, development_operation)
        )
        assert await asyncio.to_thread(development_started.wait, 1)
        production = asyncio.create_task(
            coordinator.publish(
                "dashboard",
                3,
                production_operation,
                profile="production",
            )
        )
        try:
            assert await asyncio.to_thread(production_started.wait, 1)
            release.set()
            return await development, await production
        finally:
            release.set()
            await coordinator.close()

    assert asyncio.run(exercise()) == (
        ("development", "event"),
        {"profile": "production"},
    )


def test_completed_publication_can_retry_the_same_generation() -> None:
    calls: list[str] = []

    async def exercise() -> tuple[str, str]:
        coordinator = DevelopmentCoordinator()
        try:
            failed = await coordinator.publish(
                "dashboard",
                7,
                lambda: calls.append("failed") or "failed",
            )
            repaired = await coordinator.publish(
                "dashboard",
                7,
                lambda: calls.append("repaired") or "repaired",
            )
            return failed, repaired
        finally:
            await coordinator.close()

    assert asyncio.run(exercise()) == ("failed", "repaired")
    assert calls == ["failed", "repaired"]


def test_completed_baseline_refreshes_for_a_new_subscriber() -> None:
    calls: list[str] = []

    async def exercise() -> tuple[str, str]:
        coordinator = DevelopmentCoordinator()
        try:
            first = await coordinator.baseline(
                "dashboard",
                7,
                lambda: calls.append("first") or "first",
            )
            refreshed = await coordinator.baseline(
                "dashboard",
                7,
                lambda: calls.append("refreshed") or "refreshed",
            )
            return first, refreshed
        finally:
            await coordinator.close()

    assert asyncio.run(exercise()) == ("first", "refreshed")
    assert calls == ["first", "refreshed"]


def test_last_baseline_waiter_cancels_and_drains_provider_work() -> None:
    started = threading.Event()
    cancelled = threading.Event()
    finished = threading.Event()

    def capture() -> str:
        control = current_provider_cancellation()
        assert control is not None
        unregister = control.register(cancelled.set)
        started.set()
        try:
            assert cancelled.wait(timeout=2)
            finished.set()
            return "stopped"
        finally:
            unregister()

    async def exercise() -> None:
        coordinator = DevelopmentCoordinator()
        waiting = asyncio.create_task(coordinator.baseline("dashboard", 0, capture))
        assert await asyncio.to_thread(started.wait, 1)
        waiting.cancel()
        try:
            with pytest.raises(asyncio.CancelledError):
                await waiting
            assert finished.is_set()
        finally:
            await coordinator.close()

    asyncio.run(exercise())


def test_repeated_cancellation_drains_a_baseline_waiter_blocked_on_the_lock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = threading.Event()
    cancelled = threading.Event()
    finished = threading.Event()

    def capture() -> str:
        control = current_provider_cancellation()
        assert control is not None
        unregister = control.register(cancelled.set)
        started.set()
        try:
            assert cancelled.wait(timeout=2)
            finished.set()
            return "stopped"
        finally:
            unregister()

    async def exercise() -> None:
        coordinator = DevelopmentCoordinator()
        release_entered = asyncio.Event()
        release_waiter = coordinator._publications._release_baseline_waiter

        async def gated_release(*args: Any) -> None:
            release_entered.set()
            await release_waiter(*args)

        monkeypatch.setattr(
            coordinator._publications,
            "_release_baseline_waiter",
            gated_release,
        )
        waiting = asyncio.create_task(coordinator.baseline("dashboard", 0, capture))
        assert await asyncio.to_thread(started.wait, 1)
        baseline = coordinator._publications._baselines[("dashboard", 0)]

        await coordinator._lock.acquire()
        try:
            waiting.cancel()
            await release_entered.wait()
            waiting.cancel()
            await asyncio.sleep(0)
            still_releasing = not waiting.done()
            waiting.cancel()
            await asyncio.sleep(0)
        finally:
            coordinator._lock.release()

        try:
            with pytest.raises(asyncio.CancelledError):
                await waiting
            assert still_releasing
            assert baseline.waiters == 0
            assert baseline.task.done()
            assert not baseline.waiter_releases
            assert cancelled.is_set()
            assert finished.is_set()
            assert not coordinator._publications._baselines
        finally:
            await coordinator.close()

        assert baseline.task.done()
        assert not baseline.waiter_releases
        assert not coordinator._publications._baselines

    asyncio.run(exercise())
