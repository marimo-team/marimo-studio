from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from starlette.requests import Request

from marimo_studio._server.agent import api as agent_api
from marimo_studio._server.agent.activation import ActivationAckOutcome
from marimo_studio._server.agent.clients import StudioClientRegistry
from marimo_studio._server.agent.coordinator import AgentCoordinator
from marimo_studio._server.development import routes as dev
from marimo_studio._server.development.client_events import (
    WorkspaceClientEventProducer,
)
from marimo_studio._server.development.source_changes import SourceChange
from marimo_studio.errors import AgentRequestError, ConfigurationError

from ..app_helpers import configured
from ..client_test_support import bind_native_session

_FIXTURE = (
    Path(__file__).resolve().parents[4]
    / "packages"
    / "protocol"
    / "fixtures"
    / "development-events.json"
)


def _event_payload(event: bytes) -> dict[str, object]:
    return cast(dict[str, object], json.loads(event.split(b"data: ", 1)[1]))


async def _source_event(change: SourceChange) -> dict[str, object]:
    class Source:
        def poll(self) -> SourceChange:
            return change

    class Broker:
        event: bytes | None = None

        async def emit_source(
            self,
            _view: str,
            _kind: str,
            _generation: int,
            event: bytes,
            _resync: bytes,
        ) -> None:
            self.event = event

    broker = Broker()
    await dev._produce_source_events(
        None,
        cast(Any, Source()),
        None,
        None,
        cast(Any, asyncio.Queue()),
        lambda: broker.event is not None,
        cast(Any, broker),
    )
    assert broker.event is not None
    return _event_payload(broker.event)


async def _activation_acknowledgement(
    outcome: ActivationAckOutcome,
) -> dict[str, object]:
    body = json.dumps(
        {
            "schema": 1,
            "clientId": "browser-client-1234",
            "view": "executive",
        }
    ).encode()

    async def receive() -> dict[str, object]:
        return {"type": "http.request", "body": body, "more_body": False}

    class Agents:
        async def acknowledge_activation(
            self,
            _client_id: str,
            _generation: int,
            _view: str,
            **_kwargs: object,
        ) -> ActivationAckOutcome:
            return outcome

    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/_marimo-studio/activations/1/ack",
            "query_string": b"",
            "headers": [
                (b"content-length", str(len(body)).encode()),
                (b"content-type", b"application/json"),
                (b"marimo-server-token", b"test-token"),
            ],
            "auth": SimpleNamespace(scopes=("edit",)),
        },
        receive,
    )
    response = await agent_api.activation_ack_response(
        request,
        cast(Any, SimpleNamespace(server_token="test-token")),
        cast(Any, SimpleNamespace()),
        cast(Any, SimpleNamespace(agents=Agents())),
        1,
    )
    return cast(dict[str, object], json.loads(bytes(response.body)))


async def _browser_event_payloads(
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, list[dict[str, object]]]:
    request_ids = iter(("request-dashboard", "request-dashboard-with-generation"))
    monkeypatch.setattr(
        "marimo_studio._server.agent.observation.secrets.token_urlsafe",
        lambda _length: next(request_ids),
    )
    clients = StudioClientRegistry()
    agents = AgentCoordinator(clients)
    producer = WorkspaceClientEventProducer(
        clients,
        agents,
        "browser-client-1234",
        1,
        "dashboard",
    )

    def payload(kind: str, events: tuple[Any, ...]) -> dict[str, object]:
        return next(event.payload for event in events if event.kind == kind)

    try:
        assert await producer.connect()
        await bind_native_session(clients, "s_123456", "browser-client-1234")
        initial_binding = payload("session", await producer.poll())

        target = await clients.select_target(client_id="browser-client-1234")
        activation = await agents.activate(target, "executive")
        active_view = payload("activate", await producer.poll())
        assert (
            await agents.acknowledge_activation(
                target.client_id,
                activation.generation,
                activation.view,
            )
            is ActivationAckOutcome.APPLIED
        )
        await agents.wait_for_activation(activation, timeout=1)

        target = await clients.select_target(client_id="browser-client-1234")
        observation = await agents.request_observation(
            target,
            "executive",
            "server",
            "server-instance",
            "presentation-revision",
        )
        without_generation = payload("observe", await producer.poll())
        await agents.wait_for_observation(observation, timeout=0)

        observation = await agents.request_observation(
            target,
            "executive",
            "server",
            "server-instance",
            "presentation-revision",
            active_view_generation=target.active_view_generation,
        )
        with_generation = payload("observe", await producer.poll())
        await agents.wait_for_observation(observation, timeout=0)

        await bind_native_session(
            clients,
            "s_123456",
            "browser-client-1234",
            new_incarnation=True,
        )
        replacement_binding = payload("session", await producer.poll())
        return {
            "activeViewRequests": [active_view],
            "editorSessionBindings": [initial_binding, replacement_binding],
            "observationRequests": [without_generation, with_generation],
        }
    finally:
        await producer.close()
        await agents.close()
        await clients.close()


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


def test_python_development_events_match_the_browser_protocol_fixture(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    studio = configured(notebook_path)

    class PublishedPresentations:
        def __enter__(self) -> PublishedPresentations:
            return self

        def __exit__(self, *_args: object) -> None:
            return

        def revision(self, view_name: str) -> str:
            assert view_name == "dashboard"
            return "presentation-revision"

    monkeypatch.setattr(
        dev,
        "capture_published_presentations",
        lambda *_args: PublishedPresentations(),
    )
    published_baseline = dev._presentation_baseline(studio, "dashboard")
    monkeypatch.setattr(
        dev,
        "capture_published_presentations",
        lambda *_args: None,
    )
    unpublished_baseline = dev._presentation_baseline(studio, "dashboard")

    async def prepare(
        _studio: object,
        view_name: str,
        generation: int,
        _development: object,
    ) -> tuple[dict[str, object], str | None, str | None]:
        assert view_name == "dashboard"
        if generation == 4:
            return (
                {"schema": 1, "profile": "development", "phase": "ready"},
                "presentation-revision",
                "artifact-revision",
            )
        assert generation == 5
        return (
            {"schema": 1, "profile": "development", "phase": "failed"},
            None,
            None,
        )

    monkeypatch.setattr(dev, "_prepare_presentation", prepare)
    monkeypatch.setattr(dev, "_EVENT_POLL_INTERVAL", 0)

    async def presentation_events(generation: int) -> list[dict[str, object]]:
        return [
            _event_payload(event)
            async for _kind, event in dev._presentation_events(
                studio, "dashboard", generation, None
            )
        ]

    async def collect() -> dict[str, object]:
        source_changes = [
            await _source_event(
                SourceChange(
                    "project",
                    (
                        {"path": "index.html", "revision": "html-r2"},
                        {"path": "app.css", "revision": None},
                        {"path": "src/App.tsx", "revision": "tsx-r2"},
                    ),
                )
            ),
            await _source_event(SourceChange("views", ())),
        ]
        ready = await presentation_events(4)
        failed = await presentation_events(5)
        browser = await _browser_event_payloads(monkeypatch)
        acknowledgements = [
            await _activation_acknowledgement(outcome)
            for outcome in ActivationAckOutcome
        ]
        return {
            "sourceChanges": source_changes,
            "presentationBaselines": [
                published_baseline,
                unpublished_baseline,
            ],
            "presentationBuilds": [ready[0], ready[1], failed[1]],
            "presentationChanges": [ready[2]],
            "activationAcknowledgements": acknowledgements,
            **browser,
        }

    expected = json.loads(_FIXTURE.read_text(encoding="utf-8"))

    assert asyncio.run(collect()) == expected


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
