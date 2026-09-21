"""Protect agent request coordination and cancellation."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from typing import Any

import pytest

from marimo_studio._browser_client.records import PreviewAutomationTarget
from marimo_studio._server.agent.activation import ActivationAckOutcome
from marimo_studio._server.agent.clients import (
    PeerTarget,
    StudioClientRegistry,
    WorkspaceStreamLease,
)
from marimo_studio._server.agent.coordinator import AgentCoordinator
from marimo_studio._workspace.ownership import PresentViewOwner
from marimo_studio.errors import AgentRequestError

from ..async_test_support import wait_for_event
from ..client_test_support import bind_native_session

PREVIEW_TARGET = PreviewAutomationTarget(
    "http://localhost/preview/", "iframe[data-test-preview]"
)


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

        first = await agents.pending_operations(target, None)
        same_stream = await agents.pending_operations(
            target,
            activation.generation,
        )
        reconnect = await agents.pending_operations(target, None)
        assert first.activation == activation
        assert same_stream.activation is None
        assert reconnect.activation == activation
        assert (
            await agents.acknowledge_activation(
                target.client_id,
                activation.generation,
                "dashboard",
                preview=PREVIEW_TARGET,
            )
            is ActivationAckOutcome.REJECTED
        )
        waiting = asyncio.create_task(agents.wait_for_activation(activation, 1))
        assert (
            await agents.acknowledge_activation(
                target.client_id,
                activation.generation,
                "executive",
                preview=PREVIEW_TARGET,
            )
            is ActivationAckOutcome.APPLIED
        )
        with pytest.raises(AgentRequestError) as occupied:
            await agents.activate(target, "report")
        assert occupied.value.code == "browser-operation-in-progress"
        await waiting
        settled = await agents.pending_operations(target, None)
        assert settled.activation is None
        assert (
            await agents.acknowledge_activation(
                target.client_id,
                activation.generation,
                "executive",
                preview=PREVIEW_TARGET,
            )
            is ActivationAckOutcome.APPLIED
        )
        assert (
            await agents.acknowledge_activation(
                target.client_id,
                activation.generation,
                "dashboard",
                preview=PREVIEW_TARGET,
            )
            is ActivationAckOutcome.REJECTED
        )
        target = await clients.select_target(client_id=target.client_id)
        replacement = await agents.activate(target, "report")
        assert replacement.view == "report"
        await agents.close()
        await clients.close()

    asyncio.run(exercise())


@pytest.mark.parametrize("retained", [False, True])
def test_activation_replay_rejects_changed_preview_identity(retained: bool) -> None:
    async def exercise() -> None:
        clients = StudioClientRegistry()
        agents = AgentCoordinator(clients)
        target, _lease = await connected_target(clients)
        activation = await agents.activate(target, "executive")
        assert (
            await agents.acknowledge_activation(
                target.client_id,
                activation.generation,
                activation.view,
                preview=PREVIEW_TARGET,
            )
            is ActivationAckOutcome.APPLIED
        )
        if retained:
            assert await agents.wait_for_activation(activation, 1) == PREVIEW_TARGET
        for changed in (
            replace(PREVIEW_TARGET, preview_url="http://localhost/replacement/"),
            replace(PREVIEW_TARGET, frame_selector="iframe[data-replacement]"),
        ):
            assert (
                await agents.acknowledge_activation(
                    target.client_id,
                    activation.generation,
                    activation.view,
                    preview=changed,
                )
                is ActivationAckOutcome.REJECTED
            )
        if not retained:
            assert await agents.wait_for_activation(activation, 1) == PREVIEW_TARGET
        await agents.close()
        await clients.close()

    asyncio.run(exercise())


def test_activation_replay_requires_the_acknowledged_workspace_owner() -> None:
    async def exercise() -> None:
        clients = StudioClientRegistry()
        agents = AgentCoordinator(clients)
        target, _lease = await connected_target(clients)
        owner = PresentViewOwner("a" * 64, "b" * 64)
        activation = await agents.activate(target, "executive", owner=owner)
        waiting = asyncio.create_task(agents.wait_for_activation(activation, 1))

        assert (
            await agents.acknowledge_activation(
                target.client_id,
                activation.generation,
                activation.view,
                owner=activation.owner,
                preview=PREVIEW_TARGET,
            )
            is ActivationAckOutcome.APPLIED
        )
        await waiting

        assert (
            await agents.acknowledge_activation(
                target.client_id,
                activation.generation,
                activation.view,
                owner=PresentViewOwner("c" * 64, "b" * 64),
                preview=PREVIEW_TARGET,
            )
            is ActivationAckOutcome.REJECTED
        )

    asyncio.run(exercise())


def test_activation_rejection_requires_the_pending_workspace_owner() -> None:
    async def exercise() -> None:
        clients = StudioClientRegistry()
        agents = AgentCoordinator(clients)
        target, _lease = await connected_target(clients)
        owner = PresentViewOwner("a" * 64, "b" * 64)
        activation = await agents.activate(target, "executive", owner=owner)
        waiting = asyncio.create_task(agents.wait_for_activation(activation, 1))

        assert (
            await agents.reject_activation(
                target.client_id,
                activation.generation,
                activation.view,
                AgentRequestError("forged-owner", "Forged owner", status_code=409),
                owner=PresentViewOwner("c" * 64, "b" * 64),
            )
            is ActivationAckOutcome.REJECTED
        )
        pending = await agents.pending_operations(target, None)
        assert pending.activation == activation
        assert not waiting.done()

        assert (
            await agents.acknowledge_activation(
                target.client_id,
                activation.generation,
                activation.view,
                owner=activation.owner,
                preview=PREVIEW_TARGET,
            )
            is ActivationAckOutcome.APPLIED
        )
        await waiting

    asyncio.run(exercise())


def test_activation_rejection_retains_its_slot_until_waiting_observes_it() -> None:
    async def exercise() -> None:
        clients = StudioClientRegistry()
        agents = AgentCoordinator(clients)
        target, _lease = await connected_target(clients)
        activation = await agents.activate(target, "executive")
        failure = AgentRequestError(
            "view-generation-conflict",
            "The selected view changed.",
            status_code=409,
        )

        assert (
            await agents.reject_activation(
                target.client_id,
                activation.generation,
                activation.view,
                failure,
            )
            is ActivationAckOutcome.REJECTED
        )
        with pytest.raises(AgentRequestError) as occupied:
            await agents.activate(target, "report")
        assert occupied.value.code == "browser-operation-in-progress"

        with pytest.raises(AgentRequestError) as rejected:
            await agents.wait_for_activation(activation, 1)
        assert rejected.value is failure
        replacement = await agents.activate(target, "report")
        assert replacement.view == "report"
        await agents.close()
        await clients.close()

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
                preview=PREVIEW_TARGET,
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
        deadline_scheduled = asyncio.Event()
        release = asyncio.Event()
        deadline: list[tuple[Any, tuple[object, ...]]] = []
        commit_active_view = clients.commit_active_view
        loop = asyncio.get_running_loop()
        call_at = loop.call_at
        activation_timeout = 123.456

        def observe_deadline(
            when: float,
            callback: Any,
            *args: object,
            context: Any = None,
        ):
            if when - loop.time() > 100:
                deadline.append((callback, args))
                deadline_scheduled.set()
                return call_at(loop.time() + 3_600, callback, *args, context=context)
            return call_at(when, callback, *args, context=context)

        async def delayed_commit(selected: PeerTarget, view: str):
            result = await commit_active_view(selected, view)
            committed.set()
            await release.wait()
            return result

        monkeypatch.setattr(clients, "commit_active_view", delayed_commit)
        monkeypatch.setattr(loop, "call_at", observe_deadline)
        waiting = asyncio.create_task(
            agents.wait_for_activation(activation, activation_timeout)
        )
        await wait_for_event(deadline_scheduled)
        acknowledgement = asyncio.create_task(
            agents.acknowledge_activation(
                target.client_id,
                activation.generation,
                "executive",
                preview=PREVIEW_TARGET,
            )
        )

        await wait_for_event(committed)
        callback, args = deadline.pop()
        callback(*args)
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

        pending = await agents.pending_operations(target, None)
        assert pending.activation is None

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
        replay = await agents.pending_operations(target, None)
        assert replay.activation == activation
        assert (
            await agents.acknowledge_activation(
                target.client_id,
                activation.generation,
                "executive",
                preview=PREVIEW_TARGET,
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
        pending = await agents.pending_operations(target, None)
        assert pending.activation is None

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


@pytest.mark.parametrize(
    "operation",
    ("activate", "acknowledge"),
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
        if operation == "acknowledge":
            activation = await agents.activate(target, "executive")
            owner = agents._activations
            method = "acknowledge"
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
                    preview=PREVIEW_TARGET,
                )
            raise AssertionError(operation)

        admitted = asyncio.create_task(invoke())
        await wait_for_event(entered)
        await agents.close()
        release.set()
        with pytest.raises(AgentRequestError) as raised:
            await admitted
        assert raised.value.code == "browser-coordinator-closed"
        assert raised.value.status_code == 503

        assert agents._store.activation_operations == {}
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
        activation = await agents.activate(activation_target, "executive")
        await agents.close()

        async def invoke(operation: str) -> object:
            if operation == "activate":
                return await agents.activate(activation_target, "executive")
            if operation == "acknowledge":
                return await agents.acknowledge_activation(
                    activation_target.client_id,
                    activation.generation,
                    activation.view,
                    preview=PREVIEW_TARGET,
                )
            if operation == "wait-activation":
                return await agents.wait_for_activation(activation, 1)
            return await agents.pending_operations(activation_target, None)

        for operation in (
            "activate",
            "acknowledge",
            "wait-activation",
            "pending-operations",
        ):
            with pytest.raises(AgentRequestError) as raised:
                await invoke(operation)
            assert raised.value.code == "browser-coordinator-closed", operation
            assert raised.value.status_code == 503, operation
        await clients.close()

    asyncio.run(exercise())
