from __future__ import annotations

import asyncio
import shutil
import threading
from collections import Counter
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from marimo_studio._processes.cancellation import current_provider_cancellation
from marimo_studio._processes.supervisor import ProcessCleanupError
from marimo_studio._server.development import routes as dev_module
from marimo_studio._server.development.coordinator import DevelopmentCoordinator
from marimo_studio._views.api import prepare_view
from marimo_studio._workspace import load_studio

from ..app_helpers import configured


def test_catalog_probes_are_coalesced_off_the_event_loop() -> None:
    async def exercise() -> None:
        coordinator = DevelopmentCoordinator()
        monitor: Any = SimpleNamespace(probe_lock=asyncio.Lock(), probe_task=None)
        started = threading.Event()
        release = threading.Event()
        caller = threading.get_ident()
        threads: list[int] = []

        def probe() -> bool:
            threads.append(threading.get_ident())
            started.set()
            assert release.wait(timeout=2)
            return True

        first = asyncio.create_task(coordinator._catalog_current(monitor, probe))
        second = asyncio.create_task(coordinator._catalog_current(monitor, probe))
        assert await asyncio.to_thread(started.wait, 1)
        await asyncio.sleep(0)
        assert not first.done()
        assert not second.done()

        release.set()
        assert await asyncio.gather(first, second) == [True, True]
        assert len(threads) == 1
        assert threads[0] != caller
        await coordinator.close()

    asyncio.run(exercise())


def test_project_catalog_reconciles_a_recreated_view_after_queued_deletion(
    notebook_path: Path,
) -> None:
    configured(notebook_path)
    prepare_view(notebook_path, "qa-view")
    studio = load_studio(notebook_path)

    async def exercise() -> None:
        coordinator = DevelopmentCoordinator()
        try:
            initial = await coordinator.project_catalog(studio, "qa-view")
            await asyncio.to_thread(shutil.rmtree, initial.project.root)
            await coordinator.refresh("qa-view")
            await asyncio.to_thread(prepare_view, notebook_path, "qa-view")

            current = await asyncio.to_thread(load_studio, notebook_path)
            reconciled = await coordinator.project_catalog(current, "qa-view")

            assert reconciled.project.name == "qa-view"
            assert reconciled.inspection.editor_documents
        finally:
            await coordinator.close()

    asyncio.run(exercise())


def test_inactive_presentation_warmup_is_bounded_across_clients(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    active = 0
    peak = 0
    calls: list[str] = []
    prepared: list[str] = []
    lock = threading.Lock()
    started = threading.Event()
    release = threading.Event()

    def publish(view_name: str) -> tuple[dict[str, object], None, None]:
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
            calls.append(view_name)
            if active == 2:
                started.set()
        try:
            assert release.wait(timeout=5)
            return {}, None, None
        finally:
            with lock:
                active -= 1

    async def prepare(
        _studio: object,
        view_name: str,
        _generation: object,
        development: DevelopmentCoordinator,
        *,
        warmup: bool = False,
    ) -> tuple[dict[str, object], None, None]:
        assert warmup
        prepared.append(view_name)
        return await development.publish(
            view_name,
            1,
            lambda: publish(view_name),
            warmup=True,
        )

    async def exercise() -> None:
        studio: Any = SimpleNamespace(
            views={
                "overview": object(),
                "gallery": object(),
                "story": object(),
                "table": object(),
            }
        )
        development = DevelopmentCoordinator()
        monkeypatch.setattr(dev_module, "_prepare_presentation", prepare)
        first = asyncio.create_task(
            dev_module._prepare_inactive_presentations(studio, "overview", development)
        )
        second = asyncio.create_task(
            dev_module._prepare_inactive_presentations(studio, "gallery", development)
        )
        try:
            assert await asyncio.to_thread(started.wait, 1)
            assert peak == 2
            release.set()
            await asyncio.gather(first, second)
        finally:
            release.set()
            await asyncio.gather(first, second, return_exceptions=True)
            await development.close()

    asyncio.run(exercise())

    assert Counter(prepared) == Counter(
        {"gallery": 1, "overview": 1, "story": 2, "table": 2}
    )
    assert Counter(calls) == Counter(
        {"gallery": 1, "overview": 1, "story": 1, "table": 1}
    )


def test_foreground_publication_promotes_a_queued_warmup() -> None:
    held_started = threading.Event()
    release_held = threading.Event()
    target_started = threading.Event()
    warmups_cancelled = threading.Event()
    active = 0
    cancellations = 0
    lock = threading.Lock()
    target_calls = 0

    def held() -> str:
        nonlocal active, cancellations
        control = current_provider_cancellation()
        assert control is not None

        def cancelled() -> None:
            nonlocal cancellations
            with lock:
                cancellations += 1
                if cancellations == 2:
                    warmups_cancelled.set()

        unregister = control.register(cancelled)
        with lock:
            active += 1
            if active == 2:
                held_started.set()
        try:
            assert release_held.wait(timeout=5)
            return "held"
        finally:
            unregister()
            with lock:
                active -= 1

    def target() -> str:
        nonlocal target_calls
        target_calls += 1
        target_started.set()
        return "target"

    async def exercise() -> tuple[str, str]:
        coordinator = DevelopmentCoordinator()
        first = asyncio.create_task(coordinator.publish("first", 1, held, warmup=True))
        second = asyncio.create_task(
            coordinator.publish("second", 1, held, warmup=True)
        )
        try:
            assert await asyncio.to_thread(held_started.wait, 1)
            queued = asyncio.create_task(
                coordinator.publish("target", 1, target, warmup=True)
            )
            await asyncio.sleep(0)
            assert not target_started.is_set()
            foreground = asyncio.create_task(
                coordinator.publish(
                    "target",
                    1,
                    lambda: pytest.fail(
                        "foreground request must join the queued publication"
                    ),
                )
            )
            assert await asyncio.to_thread(target_started.wait, 1)
            assert await asyncio.to_thread(warmups_cancelled.wait, 1)
            assert not release_held.is_set()
            result = await asyncio.gather(queued, foreground)
            return result[0], result[1]
        finally:
            release_held.set()
            await asyncio.gather(first, second, return_exceptions=True)
            await coordinator.close()

    assert asyncio.run(exercise()) == ("target", "target")
    assert target_calls == 1


def test_foreground_waits_for_a_preempted_same_generation_owner() -> None:
    warmup_started = threading.Event()
    warmup_cancelled = threading.Event()
    release_warmup = threading.Event()
    replacement_started = threading.Event()
    replacement_calls = 0

    def warmup() -> str:
        control = current_provider_cancellation()
        assert control is not None
        unregister = control.register(warmup_cancelled.set)
        warmup_started.set()
        try:
            assert release_warmup.wait(timeout=5)
            return "warmup"
        finally:
            unregister()

    def replacement() -> str:
        nonlocal replacement_calls
        replacement_calls += 1
        replacement_started.set()
        return "replacement"

    async def exercise() -> tuple[str, str]:
        coordinator = DevelopmentCoordinator()
        original = asyncio.create_task(
            coordinator.publish("target", 1, warmup, warmup=True)
        )
        try:
            assert await asyncio.to_thread(warmup_started.wait, 1)
            assert (
                await coordinator.publish("selected", 1, lambda: "selected")
                == "selected"
            )
            assert await asyncio.to_thread(warmup_cancelled.wait, 1)
            first = asyncio.create_task(coordinator.publish("target", 1, replacement))
            second = asyncio.create_task(
                coordinator.publish(
                    "target",
                    1,
                    lambda: pytest.fail(
                        "foreground requests must join one replacement publication"
                    ),
                )
            )
            await asyncio.sleep(0)
            assert not replacement_started.is_set()
            release_warmup.set()
            assert await asyncio.to_thread(replacement_started.wait, 1)
            result = await asyncio.gather(first, second)
            return result[0], result[1]
        finally:
            release_warmup.set()
            await asyncio.gather(original, return_exceptions=True)
            await coordinator.close()

    assert asyncio.run(exercise()) == ("replacement", "replacement")
    assert replacement_calls == 1


def test_inactive_presentation_warmup_drains_siblings_after_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sibling_started = asyncio.Event()
    sibling_cancelled = asyncio.Event()

    async def prepare(
        _studio: object,
        view_name: str,
        _generation: object,
        _development: DevelopmentCoordinator,
        *,
        warmup: bool = False,
    ) -> tuple[dict[str, object], None, None]:
        assert warmup
        if view_name == "gallery":
            sibling_started.set()
            try:
                await asyncio.Event().wait()
            finally:
                sibling_cancelled.set()
        await asyncio.wait_for(sibling_started.wait(), timeout=1)
        raise RuntimeError("warmup failed")

    async def exercise() -> None:
        studio: Any = SimpleNamespace(
            views={"overview": object(), "gallery": object(), "story": object()}
        )
        development = DevelopmentCoordinator()
        monkeypatch.setattr(dev_module, "_prepare_presentation", prepare)
        try:
            with pytest.raises(RuntimeError, match="warmup failed"):
                await dev_module._prepare_inactive_presentations(
                    studio,
                    "overview",
                    development,
                )
            assert sibling_cancelled.is_set()
        finally:
            await development.close()

    asyncio.run(exercise())


def test_inactive_warmup_cleanup_failure_survives_primary_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sibling_started = asyncio.Event()

    async def prepare(
        _studio: object,
        view_name: str,
        _generation: object,
        _development: DevelopmentCoordinator,
        *,
        warmup: bool = False,
    ) -> tuple[dict[str, object], None, None]:
        assert warmup
        if view_name == "gallery":
            sibling_started.set()
            try:
                await asyncio.Future()
            except asyncio.CancelledError as cancellation:
                raise ProcessCleanupError(
                    "warmup provider process survived"
                ) from cancellation
        await asyncio.wait_for(sibling_started.wait(), timeout=1)
        raise RuntimeError("warmup failed")

    async def exercise() -> None:
        studio: Any = SimpleNamespace(
            views={"overview": object(), "gallery": object(), "story": object()}
        )
        development = DevelopmentCoordinator()
        monkeypatch.setattr(dev_module, "_prepare_presentation", prepare)
        try:
            with pytest.raises(
                ProcessCleanupError,
                match="warmup provider process survived",
            ) as captured:
                await dev_module._prepare_inactive_presentations(
                    studio,
                    "overview",
                    development,
                )
            assert isinstance(captured.value.__cause__, RuntimeError)
        finally:
            await development.close()

    asyncio.run(exercise())
