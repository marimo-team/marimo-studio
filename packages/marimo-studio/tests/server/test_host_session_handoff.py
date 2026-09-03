from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

from marimo_studio._server.records import ServerContext
from marimo_studio._server.studio.session_handoff import (
    HostSessionHandoffRegistry,
    HostSessionTicket,
    host_session_handoff_capability_matches,
)


def _context() -> ServerContext:
    return cast(
        Any,
        SimpleNamespace(
            base_url="/notebook",
            file_key="analysis.py",
            mode="edit",
            notebook=Path("/srv/analysis.py"),
            server_token="server-token",
        ),
    )


def test_handoff_capability_binds_session_and_public_query() -> None:
    context = _context()
    query = [("file", "analysis.py"), ("region", "emea")]
    capability = HostSessionTicket.issue(
        context,
        "s_123456",
        query,
    ).capability

    assert host_session_handoff_capability_matches(
        capability,
        context,
        "s_123456",
        list(reversed(query)),
    )
    assert not host_session_handoff_capability_matches(
        capability,
        context,
        "s_654321",
        query,
    )
    assert not host_session_handoff_capability_matches(
        capability,
        context,
        "s_123456",
        [("region", "apac")],
    )

    other_notebook = cast(
        Any,
        SimpleNamespace(
            **{
                **context.__dict__,
                "file_key": "other.py",
                "notebook": Path("/srv/other.py"),
            }
        ),
    )
    assert not host_session_handoff_capability_matches(
        capability,
        other_notebook,
        "s_123456",
        query,
    )


def test_handoff_authorization_is_exact_and_single_use() -> None:
    context = _context()
    registry = HostSessionHandoffRegistry()
    claim = object()
    registry.authorize(context, "s_123456", claim)

    assert registry.contains(context, "s_123456", claim)
    assert not registry.consume(context, "s_123456", object())
    assert registry.contains(context, "s_123456", claim)
    assert registry.consume(context, "s_123456", claim)
    assert not registry.contains(context, "s_123456", claim)
    assert registry.active(context, "s_123456")
    assert not registry.consume(context, "s_123456", claim)
    registry.settle(context, "s_123456", object())
    assert registry.active(context, "s_123456")
    registry.settle(context, "s_123456", claim)
    assert not registry.active(context, "s_123456")

    registry.close()
