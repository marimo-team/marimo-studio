from __future__ import annotations

import asyncio

import pytest

from marimo_studio._server.live_clients import ClientBinding, StudioClientRegistry
from marimo_studio.errors import AgentRequestError


def test_browser_selection_uses_the_calling_session_and_rejects_ambiguity() -> None:
    async def exercise() -> None:
        clients = StudioClientRegistry()
        await clients.connect("browser-client-a")
        await clients.connect("browser-client-b")
        await clients.bind_session("s_123456", "browser-client-b")

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

        await clients.disconnect("browser-client-a")
        selected = await clients.select_target()
        assert selected.client_id == "browser-client-b"

    asyncio.run(exercise())


def test_named_browser_selection_requires_the_calling_session_to_match() -> None:
    async def exercise() -> None:
        clients = StudioClientRegistry()
        await clients.connect("browser-client-1234")
        await clients.bind_session("s_123456", "browser-client-1234")

        with pytest.raises(AgentRequestError) as raised:
            await clients.select_target(
                session_id="s_654321",
                client_id="browser-client-1234",
            )

        assert raised.value.code == "browser-client-unavailable"

    asyncio.run(exercise())


def test_workspace_connection_records_its_active_view() -> None:
    async def exercise() -> None:
        clients = StudioClientRegistry()
        client_id = "browser-client-1234"
        await clients.connect(client_id, "dashboard")

        target = await clients.target_for_client(client_id)
        assert target is not None
        assert (target.active_view, target.active_view_generation) == ("dashboard", 1)

        await clients.connect(client_id, "dashboard")
        target = await clients.target_for_client(client_id)
        assert target is not None
        assert (target.active_view, target.active_view_generation) == ("dashboard", 1)

        await clients.disconnect(client_id)
        await clients.disconnect(client_id)
        assert await clients.target_for_client(client_id) is None

    asyncio.run(exercise())


def test_session_target_waits_for_the_workspace_event_stream() -> None:
    async def exercise() -> None:
        clients = StudioClientRegistry()
        waiting = asyncio.create_task(clients.wait_for_session_target("s_123456", 1))
        await asyncio.sleep(0)
        await clients.bind_session("s_123456", "browser-client-1234")
        await clients.connect("browser-client-1234")

        target = await waiting
        assert target is not None
        assert target.client_id == "browser-client-1234"

    asyncio.run(exercise())


def test_session_target_survives_an_event_stream_reconnect() -> None:
    async def exercise() -> None:
        clients = StudioClientRegistry()
        client_id = "browser-client-1234"
        await clients.bind_session("s_123456", client_id)
        await clients.connect(client_id)
        await clients.disconnect(client_id)

        assert await clients.binding_for_session("s_123456") == ClientBinding(
            client_id=client_id,
            session_id="s_123456",
            connected=False,
        )

        await clients.connect(client_id)
        assert await clients.session_for_client(client_id) == "s_123456"

    asyncio.run(exercise())


def test_disconnected_idle_client_is_pruned_after_the_reconnect_grace() -> None:
    async def exercise() -> None:
        clients = StudioClientRegistry(disconnect_grace=0)
        client_id = "browser-client-1234"
        await clients.connect(client_id)
        await clients.bind_session("s_123456", client_id)
        await clients.disconnect(client_id)
        await asyncio.sleep(0)
        await asyncio.sleep(0)

        await clients.connect(client_id)
        assert await clients.session_for_client(client_id) is None

    asyncio.run(exercise())


def test_binding_generation_increases_after_client_reclamation() -> None:
    async def exercise() -> None:
        clients = StudioClientRegistry(disconnect_grace=0)
        client_id = "browser-client-1234"
        await clients.connect(client_id)
        await clients.bind_session("s_123456", client_id)
        first = await clients.snapshot_for_client(client_id)
        assert first is not None
        await clients.disconnect(client_id)
        await asyncio.sleep(0)
        await asyncio.sleep(0)

        await clients.connect(client_id)
        await clients.bind_session("s_654321", client_id)
        second = await clients.snapshot_for_client(client_id)
        assert second is not None

        assert first.target.binding_generation < second.target.binding_generation
        assert second.target.session_id == "s_654321"

    asyncio.run(exercise())


def test_session_binding_without_an_event_stream_expires_after_the_grace() -> None:
    async def exercise() -> None:
        clients = StudioClientRegistry(disconnect_grace=0)
        client_id = "browser-client-1234"
        await clients.bind_session("s_123456", client_id)
        await asyncio.sleep(0)
        await asyncio.sleep(0)

        await clients.connect(client_id)
        assert await clients.session_for_client(client_id) is None

    asyncio.run(exercise())


def test_event_stream_claims_a_session_binding_before_its_grace_expires() -> None:
    async def exercise() -> None:
        clients = StudioClientRegistry(disconnect_grace=0.01)
        client_id = "browser-client-1234"
        await clients.bind_session("s_123456", client_id)
        await clients.connect(client_id)
        await asyncio.sleep(0.02)

        assert await clients.session_for_client(client_id) == "s_123456"

    asyncio.run(exercise())


def test_rebinding_refreshes_the_pre_connection_grace() -> None:
    async def exercise() -> None:
        clients = StudioClientRegistry(disconnect_grace=0.08)
        client_id = "browser-client-1234"
        await clients.bind_session("s_123456", client_id)
        await asyncio.sleep(0.05)
        await clients.bind_session("s_654321", client_id)
        await asyncio.sleep(0.04)
        await clients.connect(client_id)

        assert await clients.session_for_client(client_id) == "s_654321"

    asyncio.run(exercise())


def test_query_claim_rejects_a_session_that_changed_after_resolution() -> None:
    async def exercise() -> None:
        clients = StudioClientRegistry()
        client_id = "browser-client-1234"
        await clients.connect(client_id)
        await clients.bind_session("s_123456", client_id)
        resolved = await clients.session_for_client(client_id)
        assert resolved == "s_123456"

        await clients.bind_session("s_654321", client_id)

        stale_claim = await clients.claim_query_operation(
            client_id,
            "query-1",
            resolved,
        )
        assert stale_claim is None
        assert (
            await clients.claim_query_operation(client_id, "query-1", "s_654321")
            is True
        )
        assert (
            await clients.claim_query_operation(client_id, "query-1", "s_654321")
            is False
        )

    asyncio.run(exercise())
