"""Protect Studio query operation ordering and binding ownership."""

from __future__ import annotations

import asyncio

from marimo_studio._server.agent.clients import (
    QueryOperationStatus,
    StudioClientRegistry,
    WorkspaceStreamLease,
)

from ..client_test_support import bind_native_session


async def _connect(
    clients: StudioClientRegistry,
    client_id: str,
    generation: int = 1,
) -> WorkspaceStreamLease:
    lease = await clients.connect_stream(client_id, generation)
    assert lease is not None
    return lease


def test_query_claim_rejects_a_rejected_session_binding() -> None:
    async def exercise() -> None:
        clients = StudioClientRegistry()
        client_id = "browser-client-1234"
        await _connect(clients, client_id)
        binding = await bind_native_session(clients, "s_123456", client_id)
        resolved = await clients.session_for_client(client_id)
        assert resolved == "s_123456"

        assert clients.reject_session_binding(binding)

        stale_claim = await clients.claim_query_operation(
            client_id,
            "query-1",
            resolved,
            "fingerprint-1",
            0,
        )
        assert stale_claim is None

        await clients.close()

    asyncio.run(exercise())


def test_query_operation_commits_only_for_the_current_binding() -> None:
    async def exercise() -> None:
        clients = StudioClientRegistry()
        client_id = "browser-client-1234"
        lease = await _connect(clients, client_id)
        await bind_native_session(clients, "s_123456", client_id)
        claim = await clients.claim_query_operation(
            client_id,
            "query-1",
            "s_123456",
            "fingerprint-1",
            0,
        )
        assert claim is not None
        pending = await clients.claim_query_operation(
            client_id,
            "query-1",
            "s_123456",
            "fingerprint-1",
            0,
        )
        assert pending is not None
        assert pending.status is QueryOperationStatus.PENDING

        await clients.release_stream(lease)
        assert not await clients.commit_query_operation(claim)
        await _connect(clients, client_id, 2)
        retry = await clients.claim_query_operation(
            client_id,
            "query-1",
            "s_123456",
            "fingerprint-1",
            0,
        )
        assert retry is not None
        assert retry.status is QueryOperationStatus.NEW
        assert retry.query_generation == claim.query_generation

        assert await clients.commit_query_operation(retry)
        committed = await clients.claim_query_operation(
            client_id,
            "query-1",
            "s_123456",
            "fingerprint-1",
            0,
        )
        assert committed is not None
        assert committed.status is QueryOperationStatus.COMMITTED
        await clients.close()

    asyncio.run(exercise())


def test_concurrent_query_claims_reserve_distinct_generations() -> None:
    async def exercise() -> None:
        clients = StudioClientRegistry()
        client_id = "browser-client-1234"
        session_id = "s_123456"
        await _connect(clients, client_id)
        await bind_native_session(clients, session_id, client_id)

        first, second = await asyncio.gather(
            clients.claim_query_operation(
                client_id,
                "query-1",
                session_id,
                "fingerprint-1",
                0,
            ),
            clients.claim_query_operation(
                client_id,
                "query-2",
                session_id,
                "fingerprint-2",
                1,
            ),
        )

        assert first is not None
        assert second is not None
        assert first.binding_generation == second.binding_generation
        assert {first.query_generation, second.query_generation} == {0, 1}
        for _ in range(2):
            collision = await clients.claim_query_operation(
                client_id,
                "query-collision",
                session_id,
                "fingerprint-collision",
                1,
            )
            assert collision is not None
            assert collision.status is QueryOperationStatus.CONFLICT
        await clients.release_query_operation(first)
        await clients.release_query_operation(second)
        await clients.close()

    asyncio.run(exercise())


def test_client_session_binding_is_idempotent_and_fixed() -> None:
    async def exercise() -> None:
        clients = StudioClientRegistry()
        client_id = "browser-client-1234"
        await _connect(clients, client_id)
        first = await clients.bind_session("s_123456", client_id)
        repeated = await clients.bind_session("s_123456", client_id)
        conflicting = await clients.bind_session("s_654321", client_id)

        assert first is not None
        assert repeated is first
        assert conflicting is None
        await clients.close()

    asyncio.run(exercise())


def test_rejected_connector_cannot_release_an_active_query_binding() -> None:
    async def exercise() -> None:
        clients = StudioClientRegistry()
        client_id = "browser-client-1234"
        session_id = "s_123456"
        await _connect(clients, client_id)
        binding = await clients.bind_session(session_id, client_id)
        assert binding is not None
        assert clients.accept_session_binding(binding, object()) is binding
        claim = await clients.claim_query_operation(
            client_id,
            "query-1",
            session_id,
            "fingerprint-1",
            0,
        )
        assert claim is not None
        assert await clients.acquire_query_mutation(claim)

        removed = asyncio.Event()
        unsubscribe = clients.subscribe(removed.set)
        assert clients.reject_session_binding(binding)
        assert await clients.session_for_client(client_id) == session_id

        await clients.release_query_operation(claim)
        await clients.finish_query_mutation(claim)
        await asyncio.wait_for(removed.wait(), timeout=1)
        unsubscribe()
        assert await clients.binding_for_client(client_id) is None
        await clients.close()

    asyncio.run(exercise())


def test_native_session_close_releases_its_deferred_query_owner() -> None:
    async def exercise() -> None:
        clients = StudioClientRegistry()
        client_id = "browser-client-1234"
        session_id = "s_123456"
        await _connect(clients, client_id)
        binding = await clients.bind_session(session_id, client_id)
        assert binding is not None
        native_claim = object()
        assert clients.accept_session_binding(binding, native_claim) is binding
        claim = await clients.claim_query_operation(
            client_id,
            "query-1",
            session_id,
            "fingerprint-1",
            0,
        )
        assert claim is not None
        assert await clients.acquire_query_mutation(claim)
        terminal = asyncio.get_running_loop().create_future()
        clients.defer_query_mutation(claim, terminal)

        closed = clients.native_session_closed(binding)
        assert closed is not None
        await closed

        assert terminal.cancelled()
        assert binding.phase == "retired"
        assert await clients.binding_for_client(client_id) is None
        await clients.close()

    asyncio.run(exercise())


def test_stale_native_close_releases_only_its_binding_incarnation() -> None:
    async def exercise() -> None:
        clients = StudioClientRegistry()
        client_id = "browser-client-1234"
        session_id = "s_123456"
        await _connect(clients, client_id)
        first = await clients.bind_session(session_id, client_id)
        assert first is not None
        assert clients.accept_session_binding(first, object()) is first
        first_claim = await clients.claim_query_operation(
            client_id,
            "query-1",
            session_id,
            "fingerprint-1",
            0,
        )
        assert first_claim is not None
        assert await clients.acquire_query_mutation(first_claim)
        first_terminal = asyncio.get_running_loop().create_future()
        first_deferred = clients.defer_query_mutation(first_claim, first_terminal)
        assert first_deferred is not None

        second = await clients.bind_session(
            session_id,
            client_id,
            new_incarnation=True,
        )
        assert second is not None and second is not first
        assert clients.accept_session_binding(second, object()) is second
        second_claim = await clients.claim_query_operation(
            client_id,
            "query-2",
            session_id,
            "fingerprint-2",
            1,
        )
        assert second_claim is not None
        assert await clients.acquire_query_mutation(second_claim)
        second_terminal = asyncio.get_running_loop().create_future()
        second_deferred = clients.defer_query_mutation(second_claim, second_terminal)
        assert second_deferred is not None

        first_closed = clients.native_session_closed(first)
        assert first_closed is not None
        await first_closed

        assert first_terminal.cancelled()
        assert first_deferred.done()
        assert not second_terminal.done()
        assert not second_deferred.done()
        assert second.phase == "active"
        assert await clients.session_for_client(client_id) == session_id

        second_closed = clients.native_session_closed(second)
        assert second_closed is not None
        await second_closed
        assert second_terminal.cancelled()
        assert await clients.binding_for_client(client_id) is None
        await clients.close()

    asyncio.run(exercise())


def test_disconnected_binding_keeps_its_assigned_session() -> None:
    async def exercise() -> None:
        clients = StudioClientRegistry(disconnect_grace=60)
        client_id = "browser-client-1234"
        lease = await _connect(clients, client_id)
        await bind_native_session(clients, "s_123456", client_id)
        await clients.release_stream(lease)

        conflicting = await clients.bind_session("s_654321", client_id)

        assert conflicting is None
        assert await clients.binding_for_client(client_id) is not None
        await clients.close()

    asyncio.run(exercise())


def test_released_query_is_terminal_after_a_newer_generation_is_reserved() -> None:
    async def exercise() -> None:
        clients = StudioClientRegistry()
        client_id = "browser-client-1234"
        session_id = "s_123456"
        await _connect(clients, client_id)
        await bind_native_session(clients, session_id, client_id)
        previous = await clients.claim_query_operation(
            client_id,
            "query-1",
            session_id,
            "fingerprint-1",
            0,
        )
        assert previous is not None
        await clients.release_query_operation(previous)
        current = await clients.claim_query_operation(
            client_id,
            "query-2",
            session_id,
            "fingerprint-2",
            1,
        )
        assert current is not None

        superseded = await clients.claim_query_operation(
            client_id,
            "query-1",
            session_id,
            "fingerprint-1",
            0,
        )

        assert superseded is not None
        assert superseded.query_generation == previous.query_generation
        assert superseded.status is QueryOperationStatus.SUPERSEDED
        await clients.release_query_operation(current)
        await clients.close()

    asyncio.run(exercise())


def test_malformed_deferred_terminal_releases_claim_and_fence() -> None:
    async def exercise() -> None:
        clients = StudioClientRegistry()
        client_id = "browser-client-1234"
        session_id = "s_123456"
        await _connect(clients, client_id)
        await bind_native_session(clients, session_id, client_id)
        claim = await clients.claim_query_operation(
            client_id,
            "query-1",
            session_id,
            "fingerprint-1",
            0,
        )
        assert claim is not None
        assert await clients.acquire_query_mutation(claim)
        terminal = asyncio.get_running_loop().create_future()
        deferred = clients.defer_query_mutation(claim, terminal)
        assert deferred is not None

        terminal.set_result(None)
        await deferred
        retry = await clients.claim_query_operation(
            client_id,
            "query-1",
            session_id,
            "fingerprint-1",
            0,
        )

        assert retry is not None
        assert retry.status is QueryOperationStatus.NEW
        await clients.release_query_operation(retry)
        await clients.close()

    asyncio.run(exercise())


def test_query_operation_failure_releases_its_claim() -> None:
    async def exercise() -> None:
        clients = StudioClientRegistry()
        client_id = "browser-client-1234"
        session_id = "s_123456"
        await _connect(clients, client_id)
        await bind_native_session(clients, session_id, client_id)

        failed = await clients.claim_query_operation(
            client_id,
            "failed",
            session_id,
            "fingerprint-1",
            0,
        )
        assert failed is not None
        await clients.release_query_operation(failed)
        retry = await clients.claim_query_operation(
            client_id,
            "failed",
            session_id,
            "fingerprint-1",
            0,
        )
        assert retry is not None
        assert retry.status is QueryOperationStatus.NEW
        await clients.release_query_operation(retry)
        await clients.close()

    asyncio.run(exercise())


def test_committed_query_history_is_bounded() -> None:
    async def exercise() -> None:
        clients = StudioClientRegistry()
        client_id = "browser-client-1234"
        session_id = "s_123456"
        await _connect(clients, client_id)
        await bind_native_session(clients, session_id, client_id)

        for index in range(257):
            claim = await clients.claim_query_operation(
                client_id,
                f"query-{index}",
                session_id,
                f"fingerprint-{index}",
                index,
            )
            assert claim is not None
            assert await clients.commit_query_operation(claim)
        expired = await clients.claim_query_operation(
            client_id,
            "query-0",
            session_id,
            "fingerprint-0",
            0,
        )
        retained = await clients.claim_query_operation(
            client_id,
            "query-256",
            session_id,
            "fingerprint-256",
            256,
        )
        assert expired is not None
        assert expired.status is QueryOperationStatus.SUPERSEDED
        assert retained is not None
        assert retained.status is QueryOperationStatus.COMMITTED

        await clients.close()

    asyncio.run(exercise())


def test_query_operation_id_rejects_a_different_fingerprint() -> None:
    async def exercise() -> None:
        clients = StudioClientRegistry()
        client_id = "browser-client-1234"
        session_id = "s_123456"
        await _connect(clients, client_id)
        await bind_native_session(clients, session_id, client_id)

        claim = await clients.claim_query_operation(
            client_id,
            "query-1",
            session_id,
            "fingerprint-1",
            0,
        )
        assert claim is not None
        pending_conflict = await clients.claim_query_operation(
            client_id,
            "query-1",
            session_id,
            "fingerprint-2",
            0,
        )
        assert pending_conflict is not None
        assert pending_conflict.status is QueryOperationStatus.CONFLICT

        assert await clients.commit_query_operation(claim)
        committed_conflict = await clients.claim_query_operation(
            client_id,
            "query-1",
            session_id,
            "fingerprint-2",
            0,
        )
        assert committed_conflict is not None
        assert committed_conflict.status is QueryOperationStatus.CONFLICT

        await clients.close()

    asyncio.run(exercise())
