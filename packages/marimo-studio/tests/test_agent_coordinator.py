from __future__ import annotations

import asyncio
from dataclasses import replace

import pytest

from marimo_studio._server.agent_coordinator import AgentCoordinator
from marimo_studio._server.live_clients import PeerTarget, StudioClientRegistry
from marimo_studio.agent_models import BrowserObservation
from marimo_studio.errors import AgentRequestError


async def connected_target(
    clients: StudioClientRegistry,
    client_id: str = "browser-client-1234",
    *,
    session_id: str | None = "s_123456",
    active_view: str | None = None,
) -> PeerTarget:
    await clients.connect(client_id, active_view)
    if session_id is not None:
        await clients.bind_session(session_id, client_id)
    return await clients.select_target(client_id=client_id)


def test_activation_replays_until_the_target_browser_acknowledges_it() -> None:
    async def exercise() -> None:
        clients = StudioClientRegistry()
        agents = AgentCoordinator(clients)
        target = await connected_target(clients)
        activation = await agents.activate(target, "executive")

        first = await agents.pending_operations(target, None, None)
        same_stream = await agents.pending_operations(
            target,
            activation.generation,
            None,
        )
        reconnect = await agents.pending_operations(target, None, None)
        assert first.activation == activation
        assert same_stream.activation is None
        assert reconnect.activation == activation
        assert not await agents.acknowledge_activation(
            target.client_id,
            activation.generation,
            "dashboard",
        )

        waiting = asyncio.create_task(agents.wait_for_activation(activation, 1))
        await asyncio.sleep(0)
        assert await agents.acknowledge_activation(
            target.client_id,
            activation.generation,
            "executive",
        )
        await waiting
        settled = await agents.pending_operations(target, None, None)
        assert settled.activation is None

    asyncio.run(exercise())


def test_manual_view_change_invalidates_an_older_activation() -> None:
    async def exercise() -> None:
        clients = StudioClientRegistry()
        agents = AgentCoordinator(clients)
        target = await connected_target(clients, active_view="dashboard")
        activation = await agents.activate(target, "executive")
        waiting = asyncio.create_task(agents.wait_for_activation(activation, 1))

        await clients.connect(target.client_id, "operations")

        assert not await agents.acknowledge_activation(
            target.client_id,
            activation.generation,
            "executive",
        )
        with pytest.raises(AgentRequestError) as raised:
            await waiting
        assert raised.value.code == "browser-view-changed"
        changed = await clients.target_for_client(target.client_id)
        assert changed is not None
        assert changed.active_view == "operations"

    asyncio.run(exercise())


def test_activation_cancellation_clears_the_pending_transition() -> None:
    async def exercise() -> None:
        clients = StudioClientRegistry()
        agents = AgentCoordinator(clients)
        target = await connected_target(clients)
        activation = await agents.activate(target, "executive")
        with pytest.raises(AgentRequestError) as raised:
            await agents.activate(target, "dashboard")
        assert raised.value.code == "browser-operation-in-progress"

        waiting = asyncio.create_task(agents.wait_for_activation(activation, 10))
        await asyncio.sleep(0)
        waiting.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiting

        pending = await agents.pending_operations(target, None, None)
        assert pending.activation is None

    asyncio.run(exercise())


def test_observation_requires_the_requested_revision_instance_and_order() -> None:
    async def exercise() -> None:
        clients = StudioClientRegistry()
        agents = AgentCoordinator(clients)
        target = await connected_target(clients)
        request = await agents.request_observation(
            target,
            "dashboard",
            "server",
            "runtime-instance",
            "revision-1",
        )
        waiting = asyncio.create_task(agents.wait_for_observation(request, 1))

        loading = BrowserObservation(
            view="dashboard",
            runtime="server",
            runtime_instance="runtime-instance",
            revision="revision-1",
            state="loading",
            client_id=target.client_id,
            session_id="s_123456",
            request_id=request.request_id,
            sequence=4,
            query="",
        )
        assert await agents.record(loading)
        await asyncio.sleep(0)
        assert not waiting.done()
        assert not await agents.record(replace(loading, state="ready", sequence=3))
        assert not await agents.record(
            replace(
                loading,
                state="ready",
                runtime_instance="other-instance",
                sequence=5,
            )
        )
        assert not await agents.record(
            replace(loading, state="ready", session_id="s_654321", sequence=5)
        )
        ready = replace(loading, state="ready", sequence=5)
        assert await agents.record(ready)
        assert not await agents.record(replace(loading, sequence=6))
        assert await waiting == ready
        assert not await agents.record(ready)

    asyncio.run(exercise())


def test_browser_observation_survives_an_event_stream_reconnect() -> None:
    async def exercise() -> None:
        clients = StudioClientRegistry(disconnect_grace=0.1)
        agents = AgentCoordinator(clients)
        target = await connected_target(clients, session_id=None)
        request = await agents.request_observation(
            target,
            "dashboard",
            "server",
            "runtime-instance",
            "revision-1",
        )
        waiting = asyncio.create_task(agents.wait_for_observation(request, 1))
        await asyncio.sleep(0)
        await clients.disconnect(target.client_id)
        await asyncio.sleep(0)
        assert not waiting.done()
        await clients.connect(target.client_id)
        replay = await agents.pending_operations(target, None, None)
        assert replay.observations == (request,)
        ready = BrowserObservation(
            view="dashboard",
            runtime="server",
            runtime_instance="runtime-instance",
            revision="revision-1",
            state="ready",
            client_id=target.client_id,
            request_id=request.request_id,
            sequence=0,
            query="",
        )
        assert await agents.record(ready)
        assert await waiting == ready

    asyncio.run(exercise())


def test_permanent_disconnect_finishes_browser_work_after_the_grace() -> None:
    async def exercise() -> None:
        clients = StudioClientRegistry(disconnect_grace=0.01)
        agents = AgentCoordinator(clients)
        target = await connected_target(clients)
        request = await agents.request_observation(
            target,
            "dashboard",
            "server",
            "runtime-instance",
            "revision-1",
        )
        waiting = asyncio.create_task(agents.wait_for_observation(request, 300))

        await clients.disconnect(target.client_id)

        result = await asyncio.wait_for(waiting, timeout=1)
        assert result.code == "browser-client-unavailable"
        pending = await agents.pending_operations(target, None, None)
        assert pending.observations == ()

    asyncio.run(exercise())


def test_view_activation_survives_an_event_stream_reconnect() -> None:
    async def exercise() -> None:
        clients = StudioClientRegistry(disconnect_grace=0.1)
        agents = AgentCoordinator(clients)
        target = await connected_target(clients)
        activation = await agents.activate(target, "executive")
        waiting = asyncio.create_task(agents.wait_for_activation(activation, 1))

        await clients.disconnect(target.client_id)
        await asyncio.sleep(0)
        assert not waiting.done()
        await clients.connect(target.client_id)
        replay = await agents.pending_operations(target, None, None)
        assert replay.activation == activation
        assert await agents.acknowledge_activation(
            target.client_id,
            activation.generation,
            "executive",
        )
        await waiting

    asyncio.run(exercise())


def test_permanent_disconnect_finishes_view_activation_after_the_grace() -> None:
    async def exercise() -> None:
        clients = StudioClientRegistry(disconnect_grace=0.01)
        agents = AgentCoordinator(clients)
        target = await connected_target(clients)
        activation = await agents.activate(target, "executive")
        waiting = asyncio.create_task(agents.wait_for_activation(activation, 300))

        await clients.disconnect(target.client_id)

        with pytest.raises(AgentRequestError) as raised:
            await asyncio.wait_for(waiting, timeout=1)
        assert raised.value.code == "browser-client-unavailable"
        pending = await agents.pending_operations(target, None, None)
        assert pending.activation is None

    asyncio.run(exercise())


def test_session_rebinding_invalidates_pending_browser_work() -> None:
    async def exercise() -> None:
        clients = StudioClientRegistry()
        agents = AgentCoordinator(clients)
        target = await connected_target(clients)
        activation = await agents.activate(target, "executive")
        activation_wait = asyncio.create_task(agents.wait_for_activation(activation, 1))

        await clients.bind_session("s_654321", target.client_id)

        assert await clients.binding_for_session("s_123456") is None
        rebound = await clients.select_target(session_id="s_654321")
        assert rebound.client_id == target.client_id
        assert not await agents.acknowledge_activation(
            target.client_id,
            activation.generation,
            "executive",
        )
        with pytest.raises(AgentRequestError) as raised:
            await activation_wait
        assert raised.value.code == "browser-session-changed"

        request = await agents.request_observation(
            rebound,
            "dashboard",
            "server",
            "runtime-instance",
            "revision-1",
        )
        observation_wait = asyncio.create_task(agents.wait_for_observation(request, 1))
        await clients.bind_session("s_111111", target.client_id)
        stale = BrowserObservation(
            view="dashboard",
            runtime="server",
            runtime_instance="runtime-instance",
            revision="revision-1",
            state="ready",
            client_id=target.client_id,
            session_id="s_654321",
            request_id=request.request_id,
            sequence=1,
            query="",
        )
        assert not await agents.record(stale)
        result = await observation_wait
        assert result.code == "browser-session-changed"

    asyncio.run(exercise())


def test_one_browser_handles_one_agent_operation_at_a_time() -> None:
    async def exercise() -> None:
        clients = StudioClientRegistry()
        agents = AgentCoordinator(clients)
        target = await connected_target(clients, session_id=None)
        await agents.request_observation(
            target,
            "dashboard",
            "server",
            "runtime-instance",
            "revision-1",
        )

        with pytest.raises(AgentRequestError) as raised:
            await agents.request_observation(
                target,
                "executive",
                "server",
                "runtime-instance",
                "revision-2",
            )
        assert raised.value.code == "browser-operation-in-progress"

    asyncio.run(exercise())


def test_active_view_change_invalidates_a_focused_observation() -> None:
    async def exercise() -> None:
        clients = StudioClientRegistry()
        agents = AgentCoordinator(clients)
        target = await connected_target(
            clients,
            session_id=None,
            active_view="dashboard",
        )
        request = await agents.request_observation(
            target,
            "dashboard",
            "server",
            "runtime-instance",
            "revision-1",
            active_view_generation=target.active_view_generation,
        )
        waiting = asyncio.create_task(agents.wait_for_observation(request, 1))

        await clients.connect(target.client_id, "executive")

        result = await waiting
        assert result.code == "browser-view-not-active"
        pending = await agents.pending_operations(target, None, None)
        assert pending.observations == ()

    asyncio.run(exercise())


def test_pending_operations_use_the_captured_peer_generation() -> None:
    async def exercise() -> None:
        clients = StudioClientRegistry()
        agents = AgentCoordinator(clients)
        target = await connected_target(clients)
        activation = await agents.activate(target, "executive")

        await clients.bind_session("s_654321", target.client_id)
        rebound = await clients.select_target(client_id=target.client_id)
        operations = await agents.pending_operations(rebound, None, None)

        assert rebound.binding_generation > activation.binding_generation
        assert rebound.session_id == "s_654321"
        assert operations.activation is None

    asyncio.run(exercise())
