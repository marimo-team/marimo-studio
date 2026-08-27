from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from marimo_studio._server.agent.activation import ActivationAckOutcome
from marimo_studio._server.agent.clients import StudioClientRegistry
from marimo_studio._server.agent.coordinator import AgentCoordinator
from marimo_studio._server.development import routes as dev
from marimo_studio.errors import AgentRequestError, ConfigurationError

from ..app_helpers import configured
from ..client_test_support import bind_native_session


def test_control_events_preempt_a_blocked_presentation_build(
    notebook_path: Path,
) -> None:
    studio = configured(notebook_path)
    clients = StudioClientRegistry()
    agents = AgentCoordinator(clients)

    class Subscription:
        generation = 1

        async def poll(self) -> None:
            await asyncio.Future()

        async def close(self) -> None:
            return

    class Development:
        def __init__(self) -> None:
            self.build_started = asyncio.Event()
            self.release_build = asyncio.Event()
            self.build_finished = asyncio.Event()

        async def subscribe(
            self,
            _studio: object,
            view_name: str,
        ) -> Subscription:
            assert view_name == "dashboard"
            return Subscription()

        async def baseline(
            self,
            view_name: str,
            generation: int,
            _operation: object,
        ) -> dict[str, object]:
            assert (view_name, generation) == ("dashboard", 1)
            return {"revision": "published-before-build"}

        async def project_catalog(
            self,
            _studio: object,
            view_name: str,
        ) -> SimpleNamespace:
            assert view_name == "dashboard"
            return SimpleNamespace(
                inspection=object(),
                input_id="input-dashboard",
                generation=1,
            )

        async def publish(
            self,
            view_name: str,
            generation: int,
            _operation: object,
            *,
            warmup: bool = False,
        ) -> tuple[dict[str, object], str, str]:
            assert (view_name, generation, warmup) == ("dashboard", 1, False)
            self.build_started.set()
            await self.release_build.wait()
            self.build_finished.set()
            return (
                {"schema": 1, "profile": "development", "phase": "ready"},
                "presentation-after-build",
                "artifact-after-build",
            )

    async def exercise() -> tuple[
        bytes,
        bool,
        bool,
        ActivationAckOutcome | None,
    ]:
        development = Development()
        client_id = "browser-client-1234"
        stream = dev.change_events(
            studio,
            clients=clients,
            agents=agents,
            client_id=client_id,
            stream_generation=1,
            active_view="dashboard",
            development=cast(Any, development),
        )
        next_event: asyncio.Task[bytes] | None = None
        acknowledged: ActivationAckOutcome | None = None
        try:
            await anext(stream)
            building = await anext(stream)
            assert json.loads(building.split(b"data: ", 1)[1])["phase"] == "building"

            async def receive() -> bytes:
                return await anext(stream)

            next_event = asyncio.create_task(receive())
            await asyncio.wait_for(development.build_started.wait(), timeout=1)

            await bind_native_session(clients, "s_123456", client_id)
            target = await clients.select_target(client_id=client_id)
            activation = await agents.activate(target, "executive")
            done, _pending = await asyncio.wait((next_event,), timeout=0.5)
            delivered_before_build = bool(done)
            if delivered_before_build:
                event = await next_event
                payload = json.loads(event.split(b"data: ", 1)[1])
                if event.startswith(b"event: activate"):
                    acknowledged = await agents.acknowledge_activation(
                        client_id,
                        cast(int, payload["generation"]),
                        cast(str, payload["view"]),
                    )
                    await agents.wait_for_activation(activation, timeout=0.5)
            else:
                event = b""
            return (
                event,
                delivered_before_build,
                development.build_finished.is_set(),
                acknowledged,
            )
        finally:
            development.release_build.set()
            if next_event is not None:
                await asyncio.gather(next_event, return_exceptions=True)
            await stream.aclose()
            await agents.close()

    event, delivered_before_build, build_finished, acknowledged = asyncio.run(
        exercise()
    )

    assert delivered_before_build
    assert event.startswith(b"event: activate")
    assert not build_finished
    assert acknowledged is ActivationAckOutcome.APPLIED


def test_completed_build_event_carries_the_presentation_revision(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    studio = configured(notebook_path)

    async def prepare(
        _studio: object,
        view_name: str,
        generation: int,
        _development: object,
    ) -> tuple[dict[str, object], str, str]:
        assert (view_name, generation) == ("dashboard", 4)
        return (
            {"schema": 1, "profile": "development", "phase": "ready"},
            "presentation-revision",
            "artifact-revision",
        )

    monkeypatch.setattr(dev, "_prepare_presentation", prepare)

    async def collect() -> list[bytes]:
        return [
            event
            async for _kind, event in dev._presentation_events(
                studio,
                "dashboard",
                4,
                None,
            )
        ]

    events = asyncio.run(collect())
    completed = json.loads(events[1].split(b"data: ", 1)[1])
    assert completed["kind"] == "build"
    assert completed["revision"] == "presentation-revision"


def test_catalog_failure_keeps_the_presentation_stream_repairable(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    studio = configured(notebook_path)
    owners: list[tuple[str, int]] = []

    class Development:
        async def project_catalog(self, _studio: object, _view: str) -> None:
            raise ConfigurationError("view.toml is temporarily invalid")

        async def publish(
            self,
            view_name: str,
            generation: int,
            operation: Callable[[], Any],
            **_kwargs: object,
        ) -> Any:
            owners.append((view_name, generation))
            return operation()

    fallback: tuple[dict[str, object], None, None] = (
        {"schema": 1, "profile": "development", "phase": "ready"},
        None,
        None,
    )

    def publish(
        current: object,
        view_name: str,
        prepared: object | None = None,
    ) -> tuple[dict[str, object], None, None]:
        assert (current, view_name, prepared) == (studio, "dashboard", None)
        return fallback

    monkeypatch.setattr(dev, "_publish_presentation", publish)

    result = asyncio.run(
        dev._prepare_presentation(
            studio,
            "dashboard",
            1,
            cast(Any, Development()),
        )
    )

    assert result == fallback
    assert owners == [("dashboard", 1)]


def test_blocked_baseline_keeps_browser_unavailable_to_activation(
    notebook_path: Path,
) -> None:
    studio = configured(notebook_path)
    clients = StudioClientRegistry()
    agents = AgentCoordinator(clients)

    class Subscription:
        generation = 1

        def __init__(self) -> None:
            self.closed = False

        async def poll(self) -> None:
            await asyncio.Future()

        async def close(self) -> None:
            self.closed = True

    subscription = Subscription()

    class Development:
        baseline_started = asyncio.Event()
        release_baseline = asyncio.Event()

        async def subscribe(self, _studio: object, _view: str) -> Subscription:
            return subscription

        async def baseline(self, *_args: object) -> dict[str, object]:
            self.baseline_started.set()
            await self.release_baseline.wait()
            return {"schema": 1, "view": "dashboard", "revision": None}

    async def exercise() -> None:
        development = Development()
        stream = dev.change_events(
            studio,
            clients=clients,
            agents=agents,
            client_id="browser-client-1234",
            stream_generation=1,
            active_view="dashboard",
            development=cast(Any, development),
        )
        ready = asyncio.create_task(anext(stream))
        await asyncio.wait_for(development.baseline_started.wait(), timeout=1)
        with pytest.raises(AgentRequestError) as raised:
            await clients.select_target(client_id="browser-client-1234")
        assert raised.value.code == "browser-client-unavailable"

        development.release_baseline.set()
        assert (await ready).startswith(b"event: ready")
        assert (
            await clients.select_target(client_id="browser-client-1234")
        ).active_view == "dashboard"
        await stream.aclose()
        assert subscription.closed
        with pytest.raises(AgentRequestError) as raised:
            await clients.select_target(client_id="browser-client-1234")
        assert raised.value.code == "browser-client-unavailable"
        await agents.close()

    asyncio.run(exercise())
