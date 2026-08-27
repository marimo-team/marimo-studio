from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from marimo_studio._processes.supervisor import ProcessCleanupError
from marimo_studio._server.agent.clients import (
    StudioClientRegistry,
    WorkspaceStreamLease,
)
from marimo_studio._server.agent.coordinator import AgentCoordinator
from marimo_studio._server.development import routes as dev
from marimo_studio._server.development.client_events import WorkspaceClientEventProducer
from marimo_studio.errors import AgentRequestError

from ..app_helpers import configured
from ..async_test_support import wait_for_event


def test_workspace_client_lease_drains_cancelled_reservation_and_release(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def exercise() -> None:
        grace = asyncio.Event()
        registry_changed = asyncio.Event()

        async def wait_for_grace(_delay: float) -> None:
            await grace.wait()

        clients = StudioClientRegistry(
            disconnect_grace=0,
            wait=wait_for_grace,
        )
        unsubscribe = clients.subscribe(registry_changed.set)
        agents = AgentCoordinator(clients)
        producer = WorkspaceClientEventProducer(
            clients,
            agents,
            "browser-client-1234",
            1,
            "dashboard",
        )
        reserve_stream = clients.reserve_stream
        connected = asyncio.Event()
        release_connect = asyncio.Event()

        async def delayed_reserve(
            client_id: str,
            generation: int,
            active_view: str | None = None,
        ) -> WorkspaceStreamLease | None:
            lease = await reserve_stream(client_id, generation, active_view)
            connected.set()
            await release_connect.wait()
            return lease

        monkeypatch.setattr(clients, "reserve_stream", delayed_reserve)
        acquiring = asyncio.create_task(producer.connect())
        await wait_for_event(connected)
        acquiring.cancel()
        release_connect.set()
        with pytest.raises(asyncio.CancelledError):
            await acquiring
        assert await clients.snapshot_for_client("browser-client-1234") is None
        assert "browser-client-1234" in await clients.retained_binding_generations()

        release_stream = clients.release_stream
        disconnecting = asyncio.Event()
        release_disconnect = asyncio.Event()

        async def delayed_release(lease: WorkspaceStreamLease) -> None:
            disconnecting.set()
            await release_disconnect.wait()
            await release_stream(lease)

        monkeypatch.setattr(clients, "release_stream", delayed_release)
        closing = asyncio.create_task(producer.close())
        await wait_for_event(disconnecting)
        closing.cancel()
        release_disconnect.set()
        with pytest.raises(asyncio.CancelledError):
            await closing
        registry_changed.clear()
        grace.set()
        await asyncio.wait_for(registry_changed.wait(), timeout=1)
        assert "browser-client-1234" not in await clients.retained_binding_generations()
        await producer.close()
        unsubscribe()
        await agents.close()
        await clients.close()

    asyncio.run(exercise())


def test_cancellation_before_baseline_releases_pending_stream_owners(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    studio = configured(notebook_path)

    class Browser:
        def __init__(self) -> None:
            self.reserved = False
            self.closed = False

        async def reserve(self) -> bool:
            self.reserved = True
            return True

        async def close(self) -> None:
            self.closed = True

    class Subscription:
        generation = 1

        def __init__(self) -> None:
            self.closed = False

        async def close(self) -> None:
            self.closed = True

    browser = Browser()
    subscription = Subscription()

    class Development:
        def __init__(self) -> None:
            self.baseline_started = asyncio.Event()

        async def subscribe(
            self,
            _studio: object,
            _view: str,
        ) -> Subscription:
            return subscription

        async def baseline(self, *_args: object) -> dict[str, object]:
            self.baseline_started.set()
            await asyncio.Future()
            raise AssertionError("blocked baseline resumed")

    monkeypatch.setattr(dev, "_browser_events", lambda *_args: browser)

    async def exercise() -> None:
        development = Development()
        stream = dev.change_events(
            studio,
            view_name="dashboard",
            development=cast(Any, development),
        )
        ready = asyncio.create_task(anext(stream))
        await asyncio.wait_for(development.baseline_started.wait(), timeout=1)
        ready.cancel()

        with pytest.raises(asyncio.CancelledError):
            await ready
        assert browser.reserved
        assert browser.closed
        assert subscription.closed

    asyncio.run(exercise())


def test_source_cleanup_failure_still_disconnects_browser(
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
            raise OSError("source watcher close failed")

    class Development:
        async def subscribe(self, _studio: object, _view: str) -> Subscription:
            return Subscription()

        async def baseline(self, *_args: object) -> dict[str, object]:
            return {"schema": 1, "view": "dashboard", "revision": None}

        async def project_catalog(
            self,
            _studio: object,
            _view: str,
        ) -> SimpleNamespace:
            return SimpleNamespace(
                inspection=object(),
                input_id="input-dashboard",
                generation=1,
            )

        async def publish(
            self,
            _view: str,
            _generation: int,
            _operation: object,
            **_kwargs: object,
        ) -> tuple[dict[str, object], str, str]:
            return (
                {"schema": 1, "profile": "development", "phase": "published"},
                "presentation-current",
                "artifact-current",
            )

    async def exercise() -> None:
        stream = dev.change_events(
            studio,
            clients=clients,
            agents=agents,
            client_id="browser-client-1234",
            stream_generation=1,
            active_view="dashboard",
            development=cast(Any, Development()),
        )
        assert (await anext(stream)).startswith(b"event: ready")
        assert await clients.select_target(client_id="browser-client-1234")

        with pytest.raises(Exception, match="source watcher close failed"):
            await stream.aclose()
        with pytest.raises(AgentRequestError) as raised:
            await clients.select_target(client_id="browser-client-1234")
        assert raised.value.code == "browser-client-unavailable"
        await agents.close()

    asyncio.run(exercise())


def test_cancelled_source_cleanup_still_disconnects_browser(
    notebook_path: Path,
) -> None:
    studio = configured(notebook_path)
    clients = StudioClientRegistry()
    agents = AgentCoordinator(clients)

    class Subscription:
        generation = 1

        def __init__(self) -> None:
            self.closing = asyncio.Event()
            self.release = asyncio.Event()

        async def poll(self) -> None:
            await asyncio.Future()

        async def close(self) -> None:
            self.closing.set()
            await self.release.wait()

    subscription = Subscription()

    class Development:
        async def subscribe(self, _studio: object, _view: str) -> Subscription:
            return subscription

        async def baseline(self, *_args: object) -> dict[str, object]:
            return {"schema": 1, "view": "dashboard", "revision": None}

    async def exercise() -> None:
        stream = dev.change_events(
            studio,
            clients=clients,
            agents=agents,
            client_id="browser-client-1234",
            stream_generation=1,
            active_view="dashboard",
            development=cast(Any, Development()),
        )
        assert (await anext(stream)).startswith(b"event: ready")
        assert await clients.select_target(client_id="browser-client-1234")

        closing = asyncio.create_task(stream.aclose())
        await wait_for_event(subscription.closing)
        closing.cancel()
        subscription.release.set()
        with pytest.raises(asyncio.CancelledError):
            await closing
        with pytest.raises(AgentRequestError) as raised:
            await clients.select_target(client_id="browser-client-1234")
        assert raised.value.code == "browser-client-unavailable"
        await agents.close()

    asyncio.run(exercise())


def test_stream_close_reports_cancelled_producer_cleanup_failure() -> None:
    async def exercise() -> None:
        started = asyncio.Event()

        async def producer() -> None:
            started.set()
            try:
                await asyncio.Future()
            except asyncio.CancelledError as cancellation:
                raise ProcessCleanupError(
                    "inactive presentation process survived"
                ) from cancellation

        task = asyncio.create_task(producer())
        assert await asyncio.wait_for(started.wait(), timeout=1)
        errors, cancellation = await dev._finish_stream((task,), None, None)

        with pytest.raises(
            dev.DevelopmentStreamCleanupError,
            match="inactive presentation process survived",
        ):
            dev._propagate_stream_cleanup(errors, cancellation, None)

    asyncio.run(exercise())


def test_stream_close_reports_unconsumed_producer_cleanup_failure() -> None:
    async def exercise() -> None:
        broker = dev._EventBroker()
        released = asyncio.Event()

        async def producer() -> None:
            await released.wait()
            raise ProcessCleanupError("unconsumed provider process survived")

        task = dev._start_producer(producer, broker)
        completed = asyncio.Event()
        task.add_done_callback(lambda _task: completed.set())
        released.set()
        await asyncio.wait_for(completed.wait(), timeout=1)
        errors, cancellation = await dev._finish_stream(
            (task,),
            None,
            None,
            broker,
        )

        with pytest.raises(
            dev.DevelopmentStreamCleanupError,
            match="unconsumed provider process survived",
        ):
            dev._propagate_stream_cleanup(errors, cancellation, None)

    asyncio.run(exercise())


def test_stream_close_preserves_cleanup_failure_while_broker_is_full() -> None:
    async def exercise() -> None:
        failure_started = asyncio.Event()

        class Broker(dev._EventBroker):
            async def fail(self, error: Exception) -> None:
                failure_started.set()
                await super().fail(error)

        broker = Broker(control_limit=1)
        await broker.fail(RuntimeError("queued failure"))
        failure_started.clear()

        async def producer() -> None:
            raise ProcessCleanupError("blocked broker provider process survived")

        task = dev._start_producer(producer, broker)
        await asyncio.wait_for(failure_started.wait(), timeout=1)
        assert not task.done()
        errors, cancellation = await dev._finish_stream(
            (task,),
            None,
            None,
            broker,
        )

        with pytest.raises(
            dev.DevelopmentStreamCleanupError,
            match="blocked broker provider process survived",
        ):
            dev._propagate_stream_cleanup(errors, cancellation, None)

    asyncio.run(exercise())


def test_prompt_warmup_cleanup_failure_fails_the_stream_immediately(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    studio = configured(notebook_path)

    class Subscription:
        generation = 1

        async def poll(self) -> None:
            await asyncio.Future()

        async def close(self) -> None:
            return

    class Development:
        async def subscribe(self, _studio: object, _view: str) -> Subscription:
            return Subscription()

        async def baseline(self, *_args: object) -> dict[str, object]:
            return {"schema": 1, "view": "dashboard", "revision": None}

        async def project_catalog(
            self,
            _studio: object,
            _view: str,
        ) -> SimpleNamespace:
            return SimpleNamespace(
                inspection=object(),
                input_id="input-dashboard",
                generation=1,
            )

        async def publish(
            self,
            _view: str,
            _generation: int,
            _operation: object,
            **_kwargs: object,
        ) -> tuple[dict[str, object], str, str]:
            return (
                {"schema": 1, "profile": "development", "phase": "published"},
                "presentation-current",
                "artifact-current",
            )

    async def fail_prompt(*_args: object) -> None:
        raise ProcessCleanupError("prompt warmup process survived")

    monkeypatch.setattr(
        dev,
        "_prepare_presentations_after_initial",
        fail_prompt,
    )

    async def exercise() -> None:
        stream = dev.change_events(
            studio,
            active_view="dashboard",
            development=cast(Any, Development()),
        )
        assert (await anext(stream)).startswith(b"event: ready")
        with pytest.raises(
            ProcessCleanupError,
            match="prompt warmup process survived",
        ):
            await anext(stream)

    asyncio.run(exercise())


def test_cancellation_while_a_producer_stops_still_disconnects_browser(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    studio = configured(notebook_path)
    clients = StudioClientRegistry()
    agents = AgentCoordinator(clients)

    class Subscription:
        generation = 1

        def __init__(self) -> None:
            self.polls = 0
            self.polling = asyncio.Event()
            self.producer_cancelling = asyncio.Event()
            self.release_producer = asyncio.Event()

        async def poll(self) -> object:
            self.polls += 1
            if self.polls == 1:
                return SimpleNamespace(
                    generation=1,
                    change=dev.SourceChange(kind="views", files=()),
                )
            self.polling.set()
            try:
                await asyncio.Future()
            except asyncio.CancelledError:
                self.producer_cancelling.set()
                await self.release_producer.wait()
                raise

        async def close(self) -> None:
            return

    subscription = Subscription()

    class Development:
        async def subscribe(self, _studio: object, _view: str) -> Subscription:
            return subscription

        async def baseline(self, *_args: object) -> dict[str, object]:
            return {"schema": 1, "view": "dashboard", "revision": None}

        async def project_catalog(
            self,
            _studio: object,
            _view: str,
        ) -> SimpleNamespace:
            return SimpleNamespace(
                inspection=object(),
                input_id="input-dashboard",
                generation=1,
            )

        async def publish(
            self,
            _view: str,
            _generation: int,
            _operation: object,
            *,
            warmup: bool = False,
        ) -> tuple[dict[str, object], str, str]:
            del warmup
            return (
                {"schema": 1, "profile": "development", "phase": "published"},
                "presentation-current",
                "artifact-current",
            )

    async def exercise() -> None:
        browser_released = asyncio.Event()
        release_stream = clients.release_stream

        async def tracked_release(lease: WorkspaceStreamLease) -> None:
            await release_stream(lease)
            browser_released.set()

        monkeypatch.setattr(clients, "release_stream", tracked_release)
        stream = dev.change_events(
            studio,
            clients=clients,
            agents=agents,
            client_id="browser-client-1234",
            stream_generation=1,
            active_view="dashboard",
            development=cast(Any, Development()),
        )
        assert (await anext(stream)).startswith(b"event: ready")
        assert await clients.select_target(client_id="browser-client-1234")
        assert (await anext(stream)).startswith(b"event: change")
        await asyncio.wait_for(subscription.polling.wait(), timeout=1)

        closing = asyncio.create_task(stream.aclose())
        await asyncio.wait_for(subscription.producer_cancelling.wait(), timeout=1)
        closing.cancel()
        await asyncio.wait_for(browser_released.wait(), timeout=1)
        with pytest.raises(AgentRequestError) as raised:
            await clients.select_target(client_id="browser-client-1234")
        assert raised.value.code == "browser-client-unavailable"
        assert not closing.done()
        subscription.release_producer.set()
        with pytest.raises(asyncio.CancelledError):
            await closing
        with pytest.raises(AgentRequestError) as raised:
            await clients.select_target(client_id="browser-client-1234")
        assert raised.value.code == "browser-client-unavailable"
        await agents.close()

    asyncio.run(exercise())
