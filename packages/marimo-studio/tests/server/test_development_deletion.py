from __future__ import annotations

import asyncio
import threading
from typing import Any

import pytest

from marimo_studio._processes.cancellation import current_provider_cancellation
from marimo_studio._server.development.coordinator import DevelopmentCoordinator
from marimo_studio.errors._internal import ViewDeletionInProgress


def test_view_deletion_cancels_a_queued_warmup_before_it_starts() -> None:
    held_started = threading.Event()
    release_held = threading.Event()
    target_started = threading.Event()
    active = 0
    lock = threading.Lock()

    def held() -> str:
        nonlocal active
        with lock:
            active += 1
            if active == 2:
                held_started.set()
        try:
            assert release_held.wait(timeout=5)
            return "held"
        finally:
            with lock:
                active -= 1

    def target() -> str:
        target_started.set()
        return "target"

    async def exercise() -> None:
        coordinator = DevelopmentCoordinator()
        first = asyncio.create_task(coordinator.publish("first", 1, held, warmup=True))
        second = asyncio.create_task(
            coordinator.publish("second", 1, held, warmup=True)
        )
        queued: asyncio.Task[Any] | None = None
        try:
            assert await asyncio.to_thread(held_started.wait, 1)
            queued = asyncio.create_task(
                coordinator.publish("target", 1, target, warmup=True)
            )
            await asyncio.sleep(0.05)
            assert not target_started.is_set()

            async def delete() -> None:
                async with coordinator.deleting_view("target"):
                    pass

            await asyncio.wait_for(delete(), timeout=1)
            assert not release_held.is_set()
            assert not target_started.is_set()
        finally:
            release_held.set()
            pending: list[asyncio.Task[Any]] = [first, second]
            if queued is not None:
                pending.append(queued)
            await asyncio.gather(*pending, return_exceptions=True)
            await coordinator.close()

    asyncio.run(exercise())

    assert not target_started.is_set()


def test_deletion_evicts_completed_publication_before_same_name_recreation() -> None:
    calls: list[str] = []

    async def exercise() -> tuple[str, str]:
        coordinator = DevelopmentCoordinator()
        try:
            first = await coordinator.publish(
                "dashboard",
                0,
                lambda: calls.append("old") or "old",
            )
            async with coordinator.deleting_view("dashboard"):
                pass
            second = await coordinator.publish(
                "dashboard",
                0,
                lambda: calls.append("new") or "new",
            )
            return first, second
        finally:
            await coordinator.close()

    assert asyncio.run(exercise()) == ("old", "new")
    assert calls == ["old", "new"]


def test_deletion_guard_cancels_and_drains_a_generation_baseline() -> None:
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

        async def delete() -> None:
            async with coordinator.deleting_view("dashboard"):
                assert finished.is_set()

        try:
            await asyncio.wait_for(delete(), timeout=1)
            with pytest.raises(asyncio.CancelledError):
                await waiting
        finally:
            await coordinator.close()

    asyncio.run(exercise())


def test_deletion_guard_signals_and_awaits_a_blocking_external_provider() -> None:
    started = threading.Event()
    released = threading.Event()
    finished = threading.Event()

    def publish() -> str:
        control = current_provider_cancellation()
        assert control is not None
        unregister = control.register(released.set)
        started.set()
        try:
            assert released.wait(timeout=2)
            finished.set()
            return "stopped"
        finally:
            unregister()

    async def exercise() -> str:
        coordinator = DevelopmentCoordinator()
        publication = asyncio.create_task(coordinator.publish("dashboard", 1, publish))
        assert await asyncio.to_thread(started.wait, 1)

        async def delete() -> None:
            async with coordinator.deleting_view("dashboard"):
                assert finished.is_set()

        await asyncio.wait_for(delete(), timeout=1)
        try:
            return await publication
        finally:
            await coordinator.close()

    assert asyncio.run(exercise()) == "stopped"


def test_deletion_guard_rejects_publication_until_commit_or_rollback() -> None:
    started = threading.Event()
    released = threading.Event()
    finished = threading.Event()
    calls: list[str] = []

    def active_publication() -> str:
        control = current_provider_cancellation()
        assert control is not None
        unregister = control.register(released.set)
        calls.append("active")
        started.set()
        try:
            assert released.wait(timeout=2)
            finished.set()
            return "cancelled"
        finally:
            unregister()

    def late_publication() -> str:
        calls.append("late")
        return "published"

    async def exercise() -> tuple[str, str]:
        coordinator = DevelopmentCoordinator()
        active = asyncio.create_task(
            coordinator.publish("dashboard", 1, active_publication)
        )
        assert await asyncio.to_thread(started.wait, 1)
        try:
            with pytest.raises(RuntimeError, match="rollback"):
                async with coordinator.deleting_view("dashboard"):
                    assert finished.is_set()
                    with pytest.raises(ViewDeletionInProgress):
                        await coordinator.publish("dashboard", 2, late_publication)
                    raise RuntimeError("rollback")
            resumed = await coordinator.publish("dashboard", 3, late_publication)
            return await active, resumed
        finally:
            await coordinator.close()

    assert asyncio.run(exercise()) == ("cancelled", "published")
    assert calls == ["active", "late"]


def test_cancelled_deletion_guard_drains_the_publication_before_reopening() -> None:
    started = threading.Event()
    cancelled = threading.Event()
    finish = threading.Event()
    finished = threading.Event()

    def active_publication() -> str:
        control = current_provider_cancellation()
        assert control is not None
        unregister = control.register(cancelled.set)
        started.set()
        try:
            assert cancelled.wait(timeout=2)
            assert finish.wait(timeout=2)
            finished.set()
            return "stopped"
        finally:
            unregister()

    async def exercise() -> str:
        coordinator = DevelopmentCoordinator()
        publication = asyncio.create_task(
            coordinator.publish("dashboard", 1, active_publication)
        )
        assert await asyncio.to_thread(started.wait, 1)

        async def remove() -> None:
            async with coordinator.deleting_view("dashboard"):
                raise AssertionError("Deletion began before its publication drained")

        deletion = asyncio.create_task(remove())
        assert await asyncio.to_thread(cancelled.wait, 1)
        deletion.cancel()
        await asyncio.sleep(0)
        deletion.cancel()
        await asyncio.sleep(0)
        assert not deletion.done()
        with pytest.raises(ViewDeletionInProgress):
            await coordinator.publish("dashboard", 2, lambda: "late")
        finish.set()
        with pytest.raises(asyncio.CancelledError):
            await deletion
        assert finished.is_set()
        assert await coordinator.publish("dashboard", 3, lambda: "resumed") == "resumed"
        try:
            return await publication
        finally:
            await coordinator.close()

    assert asyncio.run(exercise()) == "stopped"
