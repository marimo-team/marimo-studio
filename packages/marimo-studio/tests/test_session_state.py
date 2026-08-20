from __future__ import annotations

from typing import Any, cast

import pytest
from marimo._messaging.notification import CompletedRunNotification
from marimo._messaging.serde import serialize_kernel_message

import marimo_studio._compat.server.session_state as session_state_module
from marimo_studio._capabilities import ServerContext
from marimo_studio._compat.server.session_state import PrivateSessionState
from marimo_studio._server.control_config_api import _control_etag


def test_scratchpad_inspection_keeps_control_etag_stable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class EventBus:
        def __init__(self) -> None:
            self.listeners: list[object] = []

        def subscribe(self, listener: object) -> None:
            self.listeners.append(listener)

    class Session:
        def __init__(self) -> None:
            self._event_bus = EventBus()

    current = {"session": Session()}
    monkeypatch.setattr(
        session_state_module,
        "current_session",
        lambda _context, _session_id: current["session"],
    )
    sessions = PrivateSessionState()
    context = cast(ServerContext, object())

    revision = sessions.control_revision(context, "s_123456")
    etag = _control_etag(
        "shell-revision",
        "notebook-revision",
        "s_123456",
        "server",
        revision,
    )
    listener = cast(Any, current["session"]._event_bus.listeners[0])
    listener.on_notification_sent(current["session"], b"{}")
    assert sessions.control_revision(context, "s_123456") == 0
    listener.on_notification_sent(
        current["session"],
        serialize_kernel_message(CompletedRunNotification(run_id="inspect-1")),
    )
    assert sessions.control_revision(context, "s_123456") == 0
    assert (
        _control_etag(
            "shell-revision",
            "notebook-revision",
            "s_123456",
            "server",
            sessions.control_revision(context, "s_123456"),
        )
        == etag
    )
    listener.on_notification_sent(
        current["session"],
        serialize_kernel_message(CompletedRunNotification()),
    )
    assert sessions.control_revision(context, "s_123456") == 1
    assert (
        _control_etag(
            "shell-revision",
            "notebook-revision",
            "s_123456",
            "server",
            sessions.control_revision(context, "s_123456"),
        )
        != etag
    )

    current["session"] = Session()
    assert sessions.control_revision(context, "s_123456") == 0
