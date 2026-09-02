from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from marimo_studio._server.agent.clients import StudioClientRegistry
from marimo_studio._server.agent.coordinator import AgentCoordinator
from marimo_studio._server.development import routes as dev
from marimo_studio._workspace.ownership import AbsentViewOwner
from marimo_studio.errors import AgentRequestError

from ..app_helpers import configured
from ..client_test_support import bind_native_session


def test_change_stream_delivers_agent_view_activation(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    studio = configured(notebook_path)
    clients = StudioClientRegistry()
    agents = AgentCoordinator(clients)
    native_sleep = asyncio.sleep

    async def poll_immediately(_delay: float) -> None:
        await native_sleep(0)

    monkeypatch.setattr(dev.asyncio, "sleep", poll_immediately)
    stopping = False

    async def collect() -> tuple[bytes, bytes, bytes]:
        nonlocal stopping
        client_id = "browser-client-1234"
        stream = dev.change_events(
            studio,
            stop_requested=lambda: stopping,
            clients=clients,
            agents=agents,
            client_id=client_id,
            stream_generation=1,
        )
        ready = await anext(stream)
        await bind_native_session(clients, "s_123456", client_id)
        target = await clients.select_target(client_id=client_id)
        activation = await agents.activate(
            target,
            "executive",
            owner=AbsentViewOwner("a" * 64),
        )
        activated = await asyncio.wait_for(anext(stream), timeout=1)
        session = await asyncio.wait_for(anext(stream), timeout=1)
        stopping = True
        with pytest.raises(StopAsyncIteration):
            await asyncio.wait_for(anext(stream), timeout=1)
        assert activation.generation == 1
        return ready, activated, session

    ready, activated, session = asyncio.run(collect())

    assert ready == b"event: ready\ndata: {}\n\n"
    assert activated.startswith(b"event: activate\n")
    assert json.loads(activated.split(b"data: ", 1)[1]) == {
        "schema": 1,
        "generation": 1,
        "view": "executive",
        "catalogGeneration": "a" * 64,
        "viewGeneration": None,
    }
    assert json.loads(session.split(b"data: ", 1)[1]) == {
        "schema": 1,
        "generation": 1,
        "sessionId": "s_123456",
        "replaced": False,
    }
    with pytest.raises(AgentRequestError, match="not connected"):
        asyncio.run(clients.select_target(client_id="browser-client-1234"))


def test_workspace_stream_prepares_inactive_views_after_active_readiness(
    notebook_path: Path,
) -> None:
    studio = configured(notebook_path)
    events: list[str] = []

    async def exercise() -> tuple[bytes, list[dict[str, object]]]:
        stopping = False
        inactive_started = asyncio.Event()
        inactive_cancelled = asyncio.Event()

        class Subscription:
            generation = 3

            async def poll(self) -> None:
                return None

            async def close(self) -> None:
                events.append("subscription-closed")

        class Development:
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
                assert (view_name, generation) == ("dashboard", 3)
                events.append("active-baseline")
                return {"revision": "dashboard-baseline"}

            async def project_catalog(
                self,
                _studio: object,
                view_name: str,
            ) -> SimpleNamespace:
                events.append(f"catalog:{view_name}")
                return SimpleNamespace(
                    inspection=object(),
                    input_id=f"input-{view_name}",
                    generation=7,
                )

            async def publish(
                self,
                view_name: str,
                generation: int,
                _operation: object,
                *,
                warmup: bool = False,
            ) -> tuple[dict[str, object], str, str]:
                events.append(f"publish:{view_name}")
                assert generation in {3, 7}
                assert warmup is (view_name != "dashboard")
                if view_name == "executive":
                    inactive_started.set()
                    try:
                        await asyncio.Future()
                    except asyncio.CancelledError:
                        events.append("cancel:executive")
                        inactive_cancelled.set()
                        raise
                return (
                    {"phase": "ready"},
                    f"{view_name}-revision",
                    f"{view_name}-artifact",
                )

        stream = dev.change_events(
            studio,
            stop_requested=lambda: stopping,
            active_view="dashboard",
            development=cast(Any, Development()),
        )
        ready = await anext(stream)
        assert events == ["active-baseline"]
        active_events: list[dict[str, object]] = []
        while not (
            any("build" in event for event in active_events)
            and any(event.get("kind") == "presentation" for event in active_events)
        ):
            event = await asyncio.wait_for(anext(stream), timeout=1)
            active_events.append(json.loads(event.split(b"data: ", 1)[1]))

        async def next_event() -> bytes:
            return await anext(stream)

        pending = asyncio.create_task(next_event())
        await asyncio.wait_for(inactive_started.wait(), timeout=1)
        pending.cancel()
        await asyncio.gather(pending, return_exceptions=True)
        await stream.aclose()
        await asyncio.wait_for(inactive_cancelled.wait(), timeout=1)
        return ready, active_events

    ready, active_events = asyncio.run(exercise())

    assert json.loads(ready.split(b"data: ", 1)[1]) == {
        "revision": "dashboard-baseline"
    }
    assert next(event for event in active_events if "build" in event) == {
        "schema": 1,
        "kind": "build",
        "view": "dashboard",
        "build": {"phase": "ready"},
        "revision": "dashboard-revision",
        "files": [],
    }
    assert next(
        event for event in active_events if event.get("kind") == "presentation"
    ) == {
        "schema": 1,
        "kind": "presentation",
        "view": "dashboard",
        "revision": "dashboard-revision",
        "artifact_revision": "dashboard-artifact",
        "files": [],
    }
    assert events == [
        "active-baseline",
        "catalog:dashboard",
        "publish:dashboard",
        "catalog:executive",
        "publish:executive",
        "cancel:executive",
        "subscription-closed",
    ]


def test_change_stream_registers_a_browser_before_the_first_view() -> None:
    clients = StudioClientRegistry()
    agents = AgentCoordinator(clients)
    client_id = "browser-client-1234"
    stopping = False

    async def exercise() -> None:
        nonlocal stopping
        stream = dev.change_events(
            None,
            stop_requested=lambda: stopping,
            clients=clients,
            agents=agents,
            client_id=client_id,
            stream_generation=1,
        )
        assert await anext(stream) == b"event: ready\ndata: {}\n\n"
        target = await clients.select_target(client_id=client_id)
        assert target.active_view is None
        stopping = True
        with pytest.raises(StopAsyncIteration):
            await anext(stream)

    asyncio.run(exercise())
