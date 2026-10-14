from __future__ import annotations

import asyncio
import threading
from typing import Any, cast

import pytest

from marimo_studio._processes.cancellation import current_provider_cancellation
from marimo_studio._server.development.coordinator import DevelopmentCoordinator

from ..async_test_support import wait_for_event


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
            await wait_for_event(release_entered)
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


def test_a_warmup_preempted_before_its_slot_reports_supersede() -> None:
    from marimo_studio._server.development.publication_registry import (
        PublicationSuperseded,
    )

    held_started = threading.Barrier(3)
    release_held = threading.Event()

    def held() -> str:
        held_started.wait(timeout=2)
        assert release_held.wait(timeout=5)
        return "held"

    async def exercise() -> BaseException | str:
        coordinator = DevelopmentCoordinator()
        running = [
            asyncio.create_task(coordinator.publish(name, 1, held, warmup=True))
            for name in ("first", "second")
        ]
        try:
            await asyncio.to_thread(held_started.wait, 2)
            queued = asyncio.create_task(
                coordinator.publish("third", 1, lambda: "third", warmup=True)
            )
            await asyncio.sleep(0)
            assert await coordinator.publish("selected", 1, lambda: "ok") == "ok"
            (outcome,) = await asyncio.gather(queued, return_exceptions=True)
            return outcome
        finally:
            release_held.set()
            await asyncio.gather(*running, return_exceptions=True)
            await coordinator.close()

    assert isinstance(asyncio.run(exercise()), PublicationSuperseded)


def test_presentation_stream_serves_the_generation_after_a_superseded_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace

    from marimo_studio._server.development import routes
    from marimo_studio._server.development.publication_registry import (
        PublicationSuperseded,
    )
    from marimo_studio.errors import ConfigurationError

    async def unavailable_catalog(*_args: object) -> object:
        raise ConfigurationError("Provider inspection is unavailable.")

    async def publish(_view: str, generation: int, *_args: object, **_kwargs: object):
        if generation == 1:
            raise PublicationSuperseded
        return {"schema": 1, "phase": "published"}, "rev-2", "art-2"

    async def exercise() -> bytes:
        coordinator = DevelopmentCoordinator()
        monkeypatch.setattr(coordinator, "project_catalog", unavailable_catalog)
        monkeypatch.setattr(coordinator, "publish", publish)
        broker = routes._EventBroker()
        requests: asyncio.Queue[Any] = asyncio.Queue(maxsize=1)
        routes._request_presentation(requests, routes._PresentationRequest(1))
        producer = routes._start_producer(
            lambda: routes._produce_publication_events(
                cast(Any, SimpleNamespace(views={"dashboard": object()})),
                "dashboard",
                coordinator,
                requests,
                asyncio.Event(),
                broker,
            ),
            broker,
        )
        try:
            while requests.qsize():
                await asyncio.sleep(0.01)
            routes._request_presentation(requests, routes._PresentationRequest(2))
            while True:
                event = await broker.receive()
                assert isinstance(event, bytes), event
                if b'"kind":"presentation"' in event:
                    return event
        finally:
            producer.cancel()
            await asyncio.gather(producer, return_exceptions=True)
            await coordinator.close()

    presentation = asyncio.run(asyncio.wait_for(exercise(), timeout=5))
    assert b'"revision":"rev-2"' in presentation


def test_a_running_warmup_preempted_by_a_foreground_publication_reports_supersede() -> (
    None
):
    from marimo_studio._server.development.publication_registry import (
        PublicationSuperseded,
    )

    started = threading.Event()
    cancelled = threading.Event()

    def warm() -> dict[str, str]:
        control = current_provider_cancellation()
        assert control is not None
        control.register(cancelled.set)
        started.set()
        assert cancelled.wait(timeout=5)
        # Presentation publication returns a cancelled build as failed state.
        return {"phase": "failed"}

    async def exercise() -> BaseException | dict[str, str]:
        coordinator = DevelopmentCoordinator()
        warmup = asyncio.create_task(
            coordinator.publish("target", 1, warm, warmup=True)
        )
        try:
            assert await asyncio.to_thread(started.wait, 1)
            assert await coordinator.publish("selected", 1, lambda: "ok") == "ok"
            (outcome,) = await asyncio.gather(warmup, return_exceptions=True)
            return outcome
        finally:
            cancelled.set()
            await asyncio.gather(warmup, return_exceptions=True)
            await coordinator.close()

    assert isinstance(asyncio.run(exercise()), PublicationSuperseded)


def test_foreground_settled_waits_for_a_released_foreground_worker() -> None:
    started = threading.Event()
    release = threading.Event()

    def held() -> str:
        started.set()
        assert release.wait(timeout=5)
        return "done"

    async def exercise() -> None:
        coordinator = DevelopmentCoordinator()
        registry = coordinator._publications
        foreground = asyncio.create_task(coordinator.publish("selected", 1, held))
        try:
            assert await asyncio.to_thread(started.wait, 1)
            foreground.cancel()
            for _ in range(200):
                if not registry._publications:
                    break
                await asyncio.sleep(0.005)
            assert not registry._publications
            settled = asyncio.create_task(coordinator.foreground_settled())
            with pytest.raises(TimeoutError):
                await asyncio.wait_for(asyncio.shield(settled), timeout=0.1)
            release.set()
            await asyncio.wait_for(settled, timeout=2)
        finally:
            release.set()
            await asyncio.gather(foreground, return_exceptions=True)
            await coordinator.close()

    asyncio.run(exercise())
