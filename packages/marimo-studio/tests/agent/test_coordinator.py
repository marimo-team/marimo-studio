"""Protect agent request coordination and cancellation."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from typing import Any

import pytest

from marimo_studio._server.agent.activation import ActivationAckOutcome
from marimo_studio._server.agent.clients import (
    PeerTarget,
    StudioClientRegistry,
    WorkspaceStreamLease,
)
from marimo_studio._server.agent.coordinator import AgentCoordinator
from marimo_studio._validation.evidence import (
    BrowserObservation,
    ObservedProjectionInstance,
)
from marimo_studio.errors import AgentRequestError

from ..async_test_support import wait_for_event
from ..client_test_support import bind_native_session


async def connected_target(
    clients: StudioClientRegistry,
    client_id: str = "browser-client-1234",
    *,
    session_id: str | None = "s_123456",
    active_view: str | None = None,
) -> tuple[PeerTarget, WorkspaceStreamLease]:
    lease = await clients.connect_stream(client_id, 1, active_view)
    assert lease is not None
    if session_id is not None:
        await bind_native_session(clients, session_id, client_id)
    return await clients.select_target(client_id=client_id), lease


def wait_admission(
    monkeypatch: pytest.MonkeyPatch,
    owner: Any,
) -> asyncio.Event:
    admitted = asyncio.Event()
    is_finished = owner._finished

    def observed(operation: Any) -> bool:
        result = is_finished(operation)
        if not result:
            admitted.set()
        return result

    monkeypatch.setattr(owner, "_finished", observed)
    return admitted


def test_activation_replays_until_the_target_browser_acknowledges_it() -> None:
    async def exercise() -> None:
        clients = StudioClientRegistry()
        agents = AgentCoordinator(clients)
        target, _lease = await connected_target(clients)
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
        assert (
            await agents.acknowledge_activation(
                target.client_id,
                activation.generation,
                "dashboard",
            )
            is ActivationAckOutcome.REJECTED
        )

        waiting = asyncio.create_task(agents.wait_for_activation(activation, 1))
        assert (
            await agents.acknowledge_activation(
                target.client_id,
                activation.generation,
                "executive",
            )
            is ActivationAckOutcome.APPLIED
        )
        await waiting
        settled = await agents.pending_operations(target, None, None)
        assert settled.activation is None
        assert (
            await agents.acknowledge_activation(
                target.client_id,
                activation.generation,
                "executive",
            )
            is ActivationAckOutcome.APPLIED
        )
        assert (
            await agents.acknowledge_activation(
                target.client_id,
                activation.generation,
                "dashboard",
            )
            is ActivationAckOutcome.REJECTED
        )

    asyncio.run(exercise())


def test_manual_view_change_invalidates_an_older_activation() -> None:
    async def exercise() -> None:
        clients = StudioClientRegistry()
        agents = AgentCoordinator(clients)
        target, _lease = await connected_target(clients, active_view="dashboard")
        activation = await agents.activate(target, "executive")
        waiting = asyncio.create_task(agents.wait_for_activation(activation, 1))

        assert await clients.connect_stream(target.client_id, 2, "operations")

        assert (
            await agents.acknowledge_activation(
                target.client_id,
                activation.generation,
                "executive",
            )
            is ActivationAckOutcome.REJECTED
        )
        with pytest.raises(AgentRequestError) as raised:
            await waiting
        assert raised.value.code == "browser-view-changed"
        changed = await clients.target_for_client(target.client_id)
        assert changed is not None
        assert changed.active_view == "operations"

    asyncio.run(exercise())


def test_activation_commit_wins_atomically_over_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def exercise() -> None:
        clients = StudioClientRegistry()
        agents = AgentCoordinator(clients)
        target, _lease = await connected_target(clients, active_view="dashboard")
        activation = await agents.activate(target, "executive")
        committed = asyncio.Event()
        release = asyncio.Event()
        commit_active_view = clients.commit_active_view

        async def delayed_commit(selected: PeerTarget, view: str):
            result = await commit_active_view(selected, view)
            committed.set()
            await release.wait()
            return result

        monkeypatch.setattr(clients, "commit_active_view", delayed_commit)
        waiting = asyncio.create_task(agents.wait_for_activation(activation, 0.01))
        acknowledgement = asyncio.create_task(
            agents.acknowledge_activation(
                target.client_id,
                activation.generation,
                "executive",
            )
        )

        await wait_for_event(committed)
        await asyncio.sleep(0.02)
        assert not waiting.done()
        release.set()

        assert await acknowledgement is ActivationAckOutcome.APPLIED
        await waiting

    asyncio.run(exercise())


def test_activation_cancellation_clears_the_pending_transition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def exercise() -> None:
        clients = StudioClientRegistry()
        agents = AgentCoordinator(clients)
        target, _lease = await connected_target(clients)
        activation = await agents.activate(target, "executive")
        with pytest.raises(AgentRequestError) as raised:
            await agents.activate(target, "dashboard")
        assert raised.value.code == "browser-operation-in-progress"

        admitted = wait_admission(monkeypatch, agents._activations)
        waiting = asyncio.create_task(agents.wait_for_activation(activation, 10))
        await wait_for_event(admitted)
        waiting.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiting

        pending = await agents.pending_operations(target, None, None)
        assert pending.activation is None

    asyncio.run(exercise())


def test_observation_requires_the_requested_revision_instance_and_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def exercise() -> None:
        clients = StudioClientRegistry()
        agents = AgentCoordinator(clients)
        target, _lease = await connected_target(clients)
        request = await agents.request_observation(
            target,
            "dashboard",
            "server",
            "runtime-instance",
            "revision-1",
        )
        assert request.binding_session_id == "s_123456"
        assert request.runtime_session_id == "s_123456"
        admitted = wait_admission(monkeypatch, agents._observations)
        waiting = asyncio.create_task(agents.wait_for_observation(request, 1))
        await wait_for_event(admitted)
        pending_mount = ObservedProjectionInstance(
            mount_id="site:value:summary",
            instance_id="projection-summary",
            target="summary",
            runtime_cell_id=None,
            phase="loading",
        )

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
            projection_instances=(pending_mount,),
        )
        assert await agents.record(loading)
        assert not waiting.done()
        assert not await agents.record(
            replace(
                loading,
                state="ready",
                sequence=5,
            )
        )
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
        ready = replace(
            loading,
            state="ready",
            sequence=5,
            projection_instances=(
                replace(
                    pending_mount,
                    phase="ready",
                    runtime_cell_id="runtime-summary",
                ),
            ),
        )
        assert await agents.record(ready)
        assert not await agents.record(replace(loading, sequence=6))
        assert await waiting == ready
        assert not await agents.record(ready)

    asyncio.run(exercise())


def test_wasm_observation_guards_its_browser_binding_and_accepts_no_session() -> None:
    async def exercise() -> None:
        clients = StudioClientRegistry()
        agents = AgentCoordinator(clients)
        target, _lease = await connected_target(clients)
        request = await agents.request_observation(
            target,
            "dashboard",
            "wasm",
            "wasm-instance",
            "revision-1",
        )

        assert request.binding_session_id == "s_123456"
        assert request.runtime_session_id is None
        waiting = asyncio.create_task(agents.wait_for_observation(request, 1))
        ready = BrowserObservation(
            view="dashboard",
            runtime="wasm",
            runtime_instance="wasm-instance",
            revision="revision-1",
            state="ready",
            client_id=target.client_id,
            session_id=None,
            request_id=request.request_id,
            sequence=0,
            query="",
        )

        assert not await agents.record(replace(ready, session_id="s_123456"))
        assert await agents.record(ready)
        assert await waiting == ready

    asyncio.run(exercise())


def test_browser_observation_survives_an_event_stream_reconnect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def exercise() -> None:
        clients = StudioClientRegistry(disconnect_grace=0.1)
        agents = AgentCoordinator(clients)
        target, lease = await connected_target(clients, session_id=None)
        request = await agents.request_observation(
            target,
            "dashboard",
            "server",
            "runtime-instance",
            "revision-1",
        )
        admitted = wait_admission(monkeypatch, agents._observations)
        waiting = asyncio.create_task(agents.wait_for_observation(request, 1))
        await wait_for_event(admitted)
        await clients.release_stream(lease)
        assert not waiting.done()
        assert await clients.connect_stream(target.client_id, 2)
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
        target, lease = await connected_target(clients)
        request = await agents.request_observation(
            target,
            "dashboard",
            "server",
            "runtime-instance",
            "revision-1",
        )
        waiting = asyncio.create_task(agents.wait_for_observation(request, 300))

        await clients.release_stream(lease)

        result = await asyncio.wait_for(waiting, timeout=1)
        assert result.code == "browser-client-unavailable"
        pending = await agents.pending_operations(target, None, None)
        assert pending.observations == ()

    asyncio.run(exercise())


def test_view_activation_survives_an_event_stream_reconnect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def exercise() -> None:
        clients = StudioClientRegistry(disconnect_grace=0.1)
        agents = AgentCoordinator(clients)
        target, lease = await connected_target(clients)
        activation = await agents.activate(target, "executive")
        admitted = wait_admission(monkeypatch, agents._activations)
        waiting = asyncio.create_task(agents.wait_for_activation(activation, 1))
        await wait_for_event(admitted)

        await clients.release_stream(lease)
        assert not waiting.done()
        assert await clients.connect_stream(target.client_id, 2)
        replay = await agents.pending_operations(target, None, None)
        assert replay.activation == activation
        assert (
            await agents.acknowledge_activation(
                target.client_id,
                activation.generation,
                "executive",
            )
            is ActivationAckOutcome.APPLIED
        )
        await waiting

    asyncio.run(exercise())


def test_permanent_disconnect_finishes_view_activation_after_the_grace() -> None:
    async def exercise() -> None:
        clients = StudioClientRegistry(disconnect_grace=0.01)
        agents = AgentCoordinator(clients)
        target, lease = await connected_target(clients)
        activation = await agents.activate(target, "executive")
        waiting = asyncio.create_task(agents.wait_for_activation(activation, 300))

        await clients.release_stream(lease)

        with pytest.raises(AgentRequestError) as raised:
            await asyncio.wait_for(waiting, timeout=1)
        assert raised.value.code == "browser-client-unavailable"
        pending = await agents.pending_operations(target, None, None)
        assert pending.activation is None

    asyncio.run(exercise())


def test_one_browser_handles_one_agent_operation_at_a_time() -> None:
    async def exercise() -> None:
        clients = StudioClientRegistry()
        agents = AgentCoordinator(clients)
        target, _lease = await connected_target(clients, session_id=None)
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
        target, _lease = await connected_target(
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

        assert await clients.connect_stream(target.client_id, 2, "executive")

        result = await waiting
        assert result.code == "browser-view-not-active"
        pending = await agents.pending_operations(target, None, None)
        assert pending.observations == ()

    asyncio.run(exercise())


def test_close_finishes_an_active_activation_wait_with_a_terminal_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def exercise() -> None:
        clients = StudioClientRegistry()
        agents = AgentCoordinator(clients)
        target, _lease = await connected_target(
            clients,
            active_view="dashboard",
        )
        activation = await agents.activate(target, "dashboard")
        admitted = wait_admission(monkeypatch, agents._activations)
        waiting = asyncio.create_task(agents.wait_for_activation(activation, 300))
        await wait_for_event(admitted)

        await agents.close()
        with pytest.raises(AgentRequestError) as raised:
            await waiting
        assert raised.value.code == "browser-coordinator-closed"
        await clients.close()

    asyncio.run(exercise())


def test_close_finishes_an_active_observation_wait_with_a_terminal_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def exercise() -> None:
        clients = StudioClientRegistry()
        agents = AgentCoordinator(clients)
        target, _lease = await connected_target(
            clients,
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
        admitted = wait_admission(monkeypatch, agents._observations)
        waiting = asyncio.create_task(agents.wait_for_observation(request, 300))
        await wait_for_event(admitted)

        await agents.close()
        with pytest.raises(AgentRequestError) as raised:
            await waiting
        assert raised.value.code == "browser-coordinator-closed"
        await clients.close()

    asyncio.run(exercise())


@pytest.mark.parametrize(
    "operation",
    ("activate", "acknowledge", "request-observation", "record-observation"),
)
def test_close_rejects_operations_paused_before_store_admission(
    operation: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def exercise() -> None:
        clients = StudioClientRegistry()
        agents = AgentCoordinator(clients)
        target, _lease = await connected_target(
            clients,
            active_view="dashboard",
        )
        activation = None
        request = None
        observation = None
        if operation == "acknowledge":
            activation = await agents.activate(target, "executive")
            owner = agents._activations
            method = "acknowledge"
        elif operation == "record-observation":
            request = await agents.request_observation(
                target,
                "dashboard",
                "server",
                "runtime-instance",
                "revision-1",
            )
            observation = BrowserObservation(
                view="dashboard",
                runtime="server",
                runtime_instance="runtime-instance",
                revision="revision-1",
                state="loading",
                client_id=target.client_id,
                session_id=target.session_id,
                request_id=request.request_id,
                sequence=0,
                query="",
            )
            owner = agents._observations
            method = "record"
        elif operation == "request-observation":
            owner = agents._observations
            method = "request"
        else:
            owner = agents._activations
            method = "activate"

        entered = asyncio.Event()
        release = asyncio.Event()
        original = getattr(owner, method)

        async def delayed(*args: Any, **kwargs: Any) -> Any:
            entered.set()
            await release.wait()
            return await original(*args, **kwargs)

        monkeypatch.setattr(owner, method, delayed)

        async def invoke() -> object:
            if operation == "activate":
                return await agents.activate(target, "executive")
            if operation == "acknowledge":
                assert activation is not None
                return await agents.acknowledge_activation(
                    target.client_id,
                    activation.generation,
                    "executive",
                )
            if operation == "request-observation":
                return await agents.request_observation(
                    target,
                    "dashboard",
                    "server",
                    "runtime-instance",
                    "revision-1",
                )
            assert observation is not None
            return await agents.record(observation)

        admitted = asyncio.create_task(invoke())
        await wait_for_event(entered)
        await agents.close()
        release.set()
        with pytest.raises(AgentRequestError) as raised:
            await admitted
        assert raised.value.code == "browser-coordinator-closed"
        assert raised.value.status_code == 503

        assert agents._store.activations == {}
        assert agents._store.acknowledged_activations == {}
        assert agents._store.observation_requests == {}
        assert agents._store.observations == {}
        assert agents._store.observation_sequences == {}
        await clients.close()

    asyncio.run(exercise())


def test_closed_coordinator_rejects_every_request_visible_operation() -> None:
    async def exercise() -> None:
        clients = StudioClientRegistry()
        agents = AgentCoordinator(clients)
        activation_target, _activation_lease = await connected_target(
            clients,
            active_view="dashboard",
        )
        observation_target, _observation_lease = await connected_target(
            clients,
            client_id="observation-browser-1234",
            session_id="s_observation",
            active_view="dashboard",
        )
        activation = await agents.activate(activation_target, "executive")
        request = await agents.request_observation(
            observation_target,
            "dashboard",
            "server",
            "runtime-instance",
            "revision-1",
        )
        observation = BrowserObservation(
            view="dashboard",
            runtime="server",
            runtime_instance="runtime-instance",
            revision="revision-1",
            state="loading",
            client_id=observation_target.client_id,
            session_id=observation_target.session_id,
            request_id="request-after-close",
            sequence=0,
            query="",
        )
        await agents.close()

        async def invoke(operation: str) -> object:
            if operation == "activate":
                return await agents.activate(activation_target, "executive")
            if operation == "acknowledge":
                return await agents.acknowledge_activation(
                    activation_target.client_id,
                    activation.generation,
                    activation.view,
                )
            if operation == "wait-activation":
                return await agents.wait_for_activation(activation, 1)
            if operation == "request-observation":
                return await agents.request_observation(
                    observation_target,
                    "dashboard",
                    "server",
                    "runtime-instance",
                    "revision-1",
                )
            if operation == "record-observation":
                return await agents.record(observation)
            if operation == "wait-observation":
                return await agents.wait_for_observation(request, 1)
            return await agents.pending_operations(observation_target, None, None)

        for operation in (
            "activate",
            "acknowledge",
            "wait-activation",
            "request-observation",
            "record-observation",
            "wait-observation",
            "pending-operations",
        ):
            with pytest.raises(AgentRequestError) as raised:
                await invoke(operation)
            assert raised.value.code == "browser-coordinator-closed", operation
            assert raised.value.status_code == 503, operation
        await clients.close()

    asyncio.run(exercise())
