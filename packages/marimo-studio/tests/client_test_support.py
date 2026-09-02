"""Shared accepted native-session setup for Studio client tests."""

from __future__ import annotations

from marimo_studio._server.agent.clients import (
    SessionBindingLease,
    StudioClientRegistry,
)


async def bind_native_session(
    clients: StudioClientRegistry,
    session_id: str,
    client_id: str,
    *,
    new_incarnation: bool = False,
    native_claim: object | None = None,
) -> SessionBindingLease:
    lease = await clients.bind_session(
        session_id,
        client_id,
        new_incarnation=new_incarnation,
    )
    assert lease is not None
    accepted = clients.accept_session_binding(
        lease,
        native_claim if native_claim is not None else object(),
    )
    assert accepted is not None
    return accepted
