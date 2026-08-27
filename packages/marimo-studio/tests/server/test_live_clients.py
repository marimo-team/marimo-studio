"""Protect connected Studio client identity and ownership."""

from __future__ import annotations

import asyncio

import pytest

from marimo_studio._server.agent.clients import (
    ClientBinding,
    PeerStatus,
    StudioClientRegistry,
    WorkspaceStreamLease,
)
from marimo_studio.errors import AgentRequestError

from ..client_test_support import bind_native_session


class GraceControl:
    def __init__(self) -> None:
        self.releases: list[asyncio.Event] = []
        self.tasks: list[asyncio.Task[None]] = []
        self.started: asyncio.Queue[int] = asyncio.Queue()
        self._now = 0.0

    def now(self) -> float:
        self._now += 1
        return self._now

    async def wait(self, _delay: float) -> None:
        release = asyncio.Event()
        task = asyncio.current_task()
        assert task is not None
        self.releases.append(release)
        self.tasks.append(task)
        self.started.put_nowait(len(self.releases) - 1)
        await release.wait()

    async def release(self, index: int) -> None:
        assert await self.started.get() == index
        self.releases[index].set()
        await self.tasks[index]


async def _connect(
    clients: StudioClientRegistry,
    client_id: str,
    generation: int = 1,
    active_view: str | None = None,
) -> WorkspaceStreamLease:
    lease = await clients.connect_stream(client_id, generation, active_view)
    assert lease is not None
    return lease


def test_browser_selection_uses_the_calling_session_and_rejects_ambiguity() -> None:
    async def exercise() -> None:
        clients = StudioClientRegistry()
        first = await _connect(clients, "browser-client-a")
        await _connect(clients, "browser-client-b")
        await bind_native_session(clients, "s_123456", "browser-client-b")

        selected = await clients.select_target(session_id="s_123456")
        assert selected.client_id == "browser-client-b"
        selected = await clients.select_target(client_id="browser-client-a")
        assert selected.client_id == "browser-client-a"
        with pytest.raises(AgentRequestError) as raised:
            await clients.select_target()
        assert raised.value.code == "browser-client-ambiguous"
        with pytest.raises(AgentRequestError) as raised:
            await clients.select_target(session_id="s_654321")
        assert raised.value.code == "browser-client-unavailable"

        await clients.release_stream(first)
        selected = await clients.select_target()
        assert selected.client_id == "browser-client-b"

    asyncio.run(exercise())


def test_named_browser_selection_requires_the_calling_session_to_match() -> None:
    async def exercise() -> None:
        clients = StudioClientRegistry()
        await _connect(clients, "browser-client-1234")
        await bind_native_session(clients, "s_123456", "browser-client-1234")

        with pytest.raises(AgentRequestError) as raised:
            await clients.select_target(
                session_id="s_654321",
                client_id="browser-client-1234",
            )

        assert raised.value.code == "browser-client-unavailable"

    asyncio.run(exercise())


def test_newer_workspace_stream_owns_presence_and_active_view() -> None:
    async def exercise() -> None:
        clients = StudioClientRegistry()
        client_id = "browser-client-1234"
        first = await _connect(clients, client_id, 1, "dashboard")

        target = await clients.target_for_client(client_id)
        assert target is not None
        assert (target.active_view, target.active_view_generation) == ("dashboard", 1)

        replacement = await _connect(clients, client_id, 2, "report")
        target = await clients.target_for_client(client_id)
        assert target is not None
        assert (target.active_view, target.active_view_generation) == ("report", 2)

        assert await clients.reserve_stream(client_id, 1, "dashboard") is None
        await clients.release_stream(first)
        target = await clients.target_for_client(client_id)
        assert target is not None and target.active_view == "report"
        await clients.release_stream(replacement)
        assert await clients.target_for_client(client_id) is None

    asyncio.run(exercise())


def test_candidate_stream_does_not_change_the_agent_target_until_promotion() -> None:
    async def exercise() -> None:
        clients = StudioClientRegistry()
        client_id = "browser-client-1234"
        current = await _connect(clients, client_id, 1, "dashboard")
        initial = await clients.select_target(client_id=client_id)
        assert (initial.active_view, initial.active_view_generation) == (
            "dashboard",
            1,
        )

        candidate = await clients.reserve_stream(client_id, 2, "report")
        assert candidate is not None
        while_preparing = await clients.select_target(client_id=client_id)
        assert while_preparing == initial

        await clients.release_stream(candidate)
        after_failure = await clients.select_target(client_id=client_id)
        assert after_failure == initial

        committed = await clients.reserve_stream(client_id, 3, "report")
        assert committed is not None
        before_commit = await clients.select_target(client_id=client_id)
        assert before_commit == initial
        assert await clients.promote_stream(committed)

        after_commit = await clients.select_target(client_id=client_id)
        assert (after_commit.active_view, after_commit.active_view_generation) == (
            "report",
            2,
        )
        await clients.release_stream(current)
        await clients.release_stream(committed)
        await clients.close()

    asyncio.run(exercise())


def test_active_view_handoff_blocks_the_old_agent_target_until_settled() -> None:
    async def exercise() -> None:
        clients = StudioClientRegistry()
        client_id = "browser-client-1234"
        await _connect(clients, client_id, 1, "dashboard")
        await bind_native_session(clients, "s_123456", client_id)
        initial = await clients.select_target(client_id=client_id)

        assert await clients.begin_active_view_handoff(
            client_id,
            "handoff-operation-1",
            "dashboard",
            "report",
        )
        assert await clients.begin_active_view_handoff(
            client_id,
            "handoff-operation-1",
            "dashboard",
            "report",
        )
        assert not await clients.begin_active_view_handoff(
            client_id,
            "handoff-operation-stale",
            "dashboard",
            "report",
        )
        assert await clients.target_for_client(client_id) is None
        assert clients.status(initial) is PeerStatus.UNAVAILABLE
        assert not clients.matches(initial, require_connected=True)
        assert not await clients.rollback_active_view_handoff(
            client_id,
            "handoff-operation-stale",
        )
        with pytest.raises(AgentRequestError) as raised:
            await clients.select_target(client_id=client_id)
        assert raised.value.code == "browser-client-unavailable"

        assert await clients.rollback_active_view_handoff(
            client_id,
            "handoff-operation-1",
        )
        restored = await clients.select_target(client_id=client_id)
        assert restored == initial

        assert await clients.begin_active_view_handoff(
            client_id,
            "handoff-operation-2",
            "dashboard",
            "report",
        )
        replacement = await clients.reserve_stream(client_id, 2, "report")
        assert replacement is not None
        assert await clients.target_for_client(client_id) is None
        assert await clients.promote_stream(replacement)

        committed = await clients.select_target(client_id=client_id)
        assert (committed.active_view, committed.active_view_generation) == (
            "report",
            2,
        )
        await clients.close()

    asyncio.run(exercise())


def test_last_stream_release_clears_handoff_for_same_client_remount() -> None:
    async def exercise() -> None:
        clients = StudioClientRegistry()
        client_id = "browser-client-1234"
        current = await _connect(clients, client_id, 1, "dashboard")
        assert await clients.begin_active_view_handoff(
            client_id,
            "handoff-operation-1",
            "dashboard",
            "report",
        )

        await clients.release_stream(current)
        remounted = await _connect(clients, client_id, 2, "dashboard")

        target = await clients.select_target(client_id=client_id)
        assert (target.active_view, target.active_view_generation) == (
            "dashboard",
            1,
        )
        await clients.release_stream(remounted)
        await clients.close()

    asyncio.run(exercise())


def test_partial_stream_release_retains_the_active_handoff() -> None:
    async def exercise() -> None:
        clients = StudioClientRegistry()
        client_id = "browser-client-1234"
        current = await _connect(clients, client_id, 1, "dashboard")
        candidate = await clients.reserve_stream(client_id, 2, "report")
        assert candidate is not None
        assert await clients.begin_active_view_handoff(
            client_id,
            "handoff-operation-1",
            "dashboard",
            "report",
        )

        await clients.release_stream(candidate)

        assert await clients.target_for_client(client_id) is None
        assert await clients.rollback_active_view_handoff(
            client_id,
            "handoff-operation-1",
        )
        assert (
            await clients.select_target(client_id=client_id)
        ).active_view == "dashboard"
        await clients.release_stream(current)
        await clients.close()

    asyncio.run(exercise())


def test_higher_generation_from_view_stream_recovers_abandoned_handoff() -> None:
    async def exercise() -> None:
        clients = StudioClientRegistry()
        client_id = "browser-client-1234"
        await _connect(clients, client_id, 1, "dashboard")
        assert await clients.begin_active_view_handoff(
            client_id,
            "handoff-operation-1",
            "dashboard",
            "report",
        )

        same_generation = await clients.reserve_stream(client_id, 1, "dashboard")
        assert same_generation is not None
        assert not await clients.promote_stream(same_generation)
        await clients.release_stream(same_generation)
        wrong_view = await clients.reserve_stream(client_id, 2, "analysis")
        assert wrong_view is not None
        assert not await clients.promote_stream(wrong_view)
        await clients.release_stream(wrong_view)
        assert await clients.target_for_client(client_id) is None

        recovered = await clients.reserve_stream(client_id, 3, "dashboard")
        assert recovered is not None
        assert await clients.promote_stream(recovered)

        target = await clients.select_target(client_id=client_id)
        assert (target.active_view, target.active_view_generation) == (
            "dashboard",
            1,
        )
        await clients.close()

    asyncio.run(exercise())


def test_unknown_rollback_tombstone_rejects_a_late_acquisition() -> None:
    async def exercise() -> None:
        clients = StudioClientRegistry()
        client_id = "browser-client-1234"
        await _connect(clients, client_id, 1, "dashboard")

        assert await clients.rollback_active_view_handoff(
            client_id,
            "handoff-operation-late",
        )
        recovered = await clients.connect_stream(client_id, 2, "dashboard")
        assert recovered is not None
        assert not await clients.begin_active_view_handoff(
            client_id,
            "handoff-operation-late",
            "dashboard",
            "report",
        )

        target = await clients.select_target(client_id=client_id)
        assert (target.active_view, target.active_view_generation) == (
            "dashboard",
            1,
        )
        assert await clients.rollback_active_view_handoff(
            client_id,
            "handoff-operation-late",
        )
        await clients.close()

    asyncio.run(exercise())


def test_handoff_terminal_ids_preserve_ordering_and_idempotency() -> None:
    async def exercise() -> None:
        clients = StudioClientRegistry()
        client_id = "browser-client-1234"
        await _connect(clients, client_id, 1, "dashboard")
        assert await clients.begin_active_view_handoff(
            client_id,
            "handoff-operation-current",
            "dashboard",
            "report",
        )
        assert await clients.begin_active_view_handoff(
            client_id,
            "handoff-operation-current",
            "dashboard",
            "report",
        )

        assert not await clients.rollback_active_view_handoff(
            client_id,
            "handoff-operation-late",
        )
        assert not await clients.begin_active_view_handoff(
            client_id,
            "handoff-operation-late",
            "dashboard",
            "report",
        )
        assert await clients.rollback_active_view_handoff(
            client_id,
            "handoff-operation-late",
        )
        assert await clients.rollback_active_view_handoff(
            client_id,
            "handoff-operation-current",
        )
        assert await clients.rollback_active_view_handoff(
            client_id,
            "handoff-operation-current",
        )
        assert not await clients.begin_active_view_handoff(
            client_id,
            "handoff-operation-current",
            "dashboard",
            "report",
        )
        assert (
            await clients.select_target(client_id=client_id)
        ).active_view == "dashboard"
        await clients.close()

    asyncio.run(exercise())


def test_handoff_terminal_ids_are_bounded_under_a_fixed_session() -> None:
    async def exercise() -> None:
        clients = StudioClientRegistry(terminal_handoff_limit=2)
        client_id = "browser-client-1234"
        await _connect(clients, client_id, 1, "dashboard")
        await bind_native_session(clients, "s_123456", client_id)
        for operation_id in (
            "handoff-operation-1",
            "handoff-operation-2",
            "handoff-operation-3",
        ):
            assert await clients.rollback_active_view_handoff(client_id, operation_id)

        assert not await clients.begin_active_view_handoff(
            client_id,
            "handoff-operation-3",
            "dashboard",
            "report",
        )
        assert await clients.begin_active_view_handoff(
            client_id,
            "handoff-operation-1",
            "dashboard",
            "report",
        )
        assert await clients.rollback_active_view_handoff(
            client_id,
            "handoff-operation-1",
        )

        assert await clients.bind_session("s_654321", client_id) is None
        assert not await clients.begin_active_view_handoff(
            client_id,
            "handoff-operation-3",
            "dashboard",
            "report",
        )
        target = await clients.select_target(client_id=client_id)
        assert target.session_id == "s_123456"
        assert target.active_view == "dashboard"
        await clients.close()

    asyncio.run(exercise())


def test_client_discard_releases_handoff_terminal_ids() -> None:
    async def exercise() -> None:
        grace = GraceControl()
        clients = StudioClientRegistry(disconnect_grace=0, wait=grace.wait)
        client_id = "browser-client-1234"
        current = await _connect(clients, client_id, 1, "dashboard")
        assert await clients.rollback_active_view_handoff(
            client_id,
            "handoff-operation-old",
        )
        await clients.release_stream(current)
        discarded = asyncio.Event()
        unsubscribe = clients.subscribe(discarded.set)
        await grace.release(0)
        await asyncio.wait_for(discarded.wait(), timeout=1)
        unsubscribe()

        await _connect(clients, client_id, 2, "dashboard")
        assert await clients.begin_active_view_handoff(
            client_id,
            "handoff-operation-old",
            "dashboard",
            "report",
        )
        await clients.close()

    asyncio.run(exercise())


def test_native_close_then_stream_disconnect_reclaims_the_client() -> None:
    async def exercise() -> None:
        grace = GraceControl()
        clients = StudioClientRegistry(disconnect_grace=0, wait=grace.wait)
        client_id = "browser-client-1234"
        current = await _connect(clients, client_id, 1, "dashboard")
        binding = await bind_native_session(clients, "s_123456", client_id)
        operation_id = "handoff-operation-old"
        assert await clients.rollback_active_view_handoff(client_id, operation_id)

        closed = clients.native_session_closed(binding)
        assert closed is not None
        await closed
        await clients.release_stream(current)
        discarded = asyncio.Event()
        unsubscribe = clients.subscribe(discarded.set)
        await grace.release(0)
        await asyncio.wait_for(discarded.wait(), timeout=1)
        unsubscribe()

        await _connect(clients, client_id, 2, "dashboard")
        assert await clients.begin_active_view_handoff(
            client_id,
            operation_id,
            "dashboard",
            "report",
        )
        await clients.close()

    asyncio.run(exercise())


def test_session_target_waits_for_the_workspace_event_stream() -> None:
    async def exercise() -> None:
        clients = StudioClientRegistry()
        started = asyncio.Event()

        async def wait_for_target():
            started.set()
            return await clients.wait_for_session_target("s_123456", 1)

        waiting = asyncio.create_task(wait_for_target())
        await started.wait()
        await bind_native_session(clients, "s_123456", "browser-client-1234")
        assert not waiting.done()
        await _connect(clients, "browser-client-1234")

        target = await waiting
        assert target is not None
        assert target.client_id == "browser-client-1234"

    asyncio.run(exercise())


def test_native_accept_replaces_the_provisional_target_identity() -> None:
    async def exercise() -> None:
        clients = StudioClientRegistry()
        client_id = "browser-client-1234"
        await _connect(clients, client_id, 1, "dashboard")
        binding = await clients.bind_session(
            "s_123456",
            client_id,
        )
        assert binding is not None
        provisional = await clients.select_target(client_id=client_id)

        assert provisional.session_id is None
        assert clients.status(provisional) is PeerStatus.CURRENT
        with pytest.raises(AgentRequestError):
            await clients.select_target(session_id="s_123456")
        started = asyncio.Event()

        async def wait_for_session():
            started.set()
            return await clients.wait_for_session_target("s_123456", 1)

        waiting = asyncio.create_task(wait_for_session())
        await started.wait()
        assert not waiting.done()
        assert clients.accept_session_binding(binding, object()) is binding
        accepted_by_session = await waiting
        assert accepted_by_session is not None
        assert accepted_by_session.session_id == "s_123456"
        assert clients.status(provisional) is PeerStatus.REBOUND
        accepted = await clients.select_target(client_id=client_id)
        assert accepted.session_id == "s_123456"
        assert clients.status(accepted) is PeerStatus.CURRENT
        await clients.close()

    asyncio.run(exercise())


def test_session_target_survives_an_event_stream_reconnect() -> None:
    async def exercise() -> None:
        clients = StudioClientRegistry()
        client_id = "browser-client-1234"
        await bind_native_session(clients, "s_123456", client_id)
        first = await _connect(clients, client_id)
        await clients.release_stream(first)

        assert await clients.binding_for_session("s_123456") == ClientBinding(
            client_id=client_id,
            session_id="s_123456",
            connected=False,
        )

        await _connect(clients, client_id, 2)
        assert await clients.session_for_client(client_id) == "s_123456"

    asyncio.run(exercise())


def test_accepted_session_survives_the_event_stream_reconnect_grace() -> None:
    async def exercise() -> None:
        grace = GraceControl()
        clients = StudioClientRegistry(disconnect_grace=0, wait=grace.wait)
        client_id = "browser-client-1234"
        first = await _connect(clients, client_id)
        await bind_native_session(clients, "s_123456", client_id)
        await clients.release_stream(first)
        expired = asyncio.Event()
        unsubscribe = clients.subscribe(expired.set)
        await grace.release(0)
        await asyncio.wait_for(expired.wait(), timeout=1)
        unsubscribe()

        await _connect(clients, client_id, 2)
        assert await clients.session_for_client(client_id) == "s_123456"

    asyncio.run(exercise())


def test_binding_generation_increases_after_client_reclamation() -> None:
    async def exercise() -> None:
        grace = GraceControl()
        clients = StudioClientRegistry(
            disconnect_grace=0,
            clock=grace.now,
            wait=grace.wait,
        )
        client_id = "browser-client-1234"
        first_lease = await _connect(clients, client_id)
        first_binding = await clients.bind_session("s_123456", client_id)
        assert first_binding is not None
        first = await clients.snapshot_for_client(client_id)
        assert first is not None
        await clients.release_stream(first_lease)
        discarded = asyncio.Event()
        unsubscribe = clients.subscribe(discarded.set)
        await grace.release(0)
        await asyncio.wait_for(discarded.wait(), timeout=1)
        unsubscribe()

        await _connect(clients, client_id, 2)
        await bind_native_session(clients, "s_654321", client_id)
        second = await clients.snapshot_for_client(client_id)
        assert second is not None

        assert first.target.binding_generation < second.target.binding_generation
        assert second.target.session_id == "s_654321"

    asyncio.run(exercise())


def test_session_binding_without_an_event_stream_expires_after_the_grace() -> None:
    async def exercise() -> None:
        grace = GraceControl()
        clients = StudioClientRegistry(
            disconnect_grace=0,
            clock=grace.now,
            wait=grace.wait,
        )
        client_id = "browser-client-1234"
        await clients.bind_session("s_123456", client_id)
        discarded = asyncio.Event()
        unsubscribe = clients.subscribe(discarded.set)
        await grace.release(0)
        await asyncio.wait_for(discarded.wait(), timeout=1)
        unsubscribe()

        await _connect(clients, client_id)
        assert await clients.session_for_client(client_id) is None

    asyncio.run(exercise())


def test_reserved_stream_retains_a_binding_until_promotion() -> None:
    async def exercise() -> None:
        grace = GraceControl()
        clients = StudioClientRegistry(
            disconnect_grace=10,
            clock=grace.now,
            wait=grace.wait,
        )
        client_id = "browser-client-1234"
        binding = await clients.bind_session("s_123456", client_id)
        assert binding is not None
        lease = await clients.reserve_stream(client_id, 1, "dashboard")
        assert lease is not None
        await grace.release(0)

        assert await clients.binding_for_client(client_id) == ClientBinding(
            client_id=client_id,
            session_id="s_123456",
            connected=False,
        )
        with pytest.raises(AgentRequestError):
            await clients.select_target(client_id=client_id)
        assert await clients.promote_stream(lease)
        assert await clients.session_for_client(client_id) is None
        assert clients.accept_session_binding(binding, object()) is binding
        assert await clients.session_for_client(client_id) == "s_123456"
        await clients.close()

    asyncio.run(exercise())


def test_candidate_stream_restores_presence_only_after_promotion() -> None:
    async def exercise() -> None:
        grace = GraceControl()
        clients = StudioClientRegistry(
            disconnect_grace=10,
            clock=grace.now,
            wait=grace.wait,
        )
        client_id = "browser-client-1234"
        current = await _connect(clients, client_id, 1, "dashboard")
        await bind_native_session(clients, "s_123456", client_id)
        target = await clients.select_target(client_id=client_id)

        await clients.release_stream(current)
        expired = asyncio.Event()
        unsubscribe = clients.subscribe(expired.set)
        await grace.release(0)
        await asyncio.wait_for(expired.wait(), timeout=1)
        unsubscribe()
        assert clients.status(target) is PeerStatus.UNAVAILABLE

        candidate = await clients.reserve_stream(client_id, 2, "dashboard")
        assert candidate is not None
        assert clients.status(target) is PeerStatus.UNAVAILABLE
        assert await clients.target_for_client(client_id) is None

        assert await clients.promote_stream(candidate)
        restored = await clients.select_target(client_id=client_id)
        assert clients.status(restored) is PeerStatus.CURRENT
        await clients.close()

    asyncio.run(exercise())


def test_registry_close_is_terminal_for_new_owners() -> None:
    async def exercise() -> None:
        clients = StudioClientRegistry()
        lease = await clients.reserve_stream("browser-client-1234", 1, "dashboard")
        assert lease is not None

        await clients.close()

        assert not await clients.promote_stream(lease)
        await clients.release_stream(lease)
        assert await clients.wait_for_session_target("s_123456", 1) is None
        with pytest.raises(RuntimeError, match="registry is closed"):
            await clients.reserve_stream("browser-client-1234", 2, "report")
        with pytest.raises(RuntimeError, match="registry is closed"):
            await clients.bind_session("s_123456", "browser-client-1234")
        with pytest.raises(RuntimeError, match="registry is closed"):
            clients.subscribe(lambda: None)

    asyncio.run(exercise())
