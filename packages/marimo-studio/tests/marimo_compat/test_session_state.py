"""Protect synchronous Marimo session ownership classification."""

from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from marimo._messaging.notification import (
    QueryParamsSetNotification,
    ReloadNotification,
)

import marimo_studio._compat.server.session_state as session_state_module
from marimo_studio._compat.server.session_state import (
    PrivateSessionState,
    session_creation_query_matches,
    session_matches_notebook,
)


def test_session_owner_uses_the_initialization_identity() -> None:
    class UnreadablePath:
        def __fspath__(self) -> str:
            raise AssertionError("established sessions must not resolve their path")

    session = SimpleNamespace(
        initialization_id="notebook.py",
        app_file_manager=SimpleNamespace(path=UnreadablePath()),
    )

    assert session_matches_notebook(
        cast(Any, session),
        file_key="notebook.py",
        notebook=Path("/workspace/notebook.py"),
    )


def test_session_owner_accepts_the_current_notebook_path(tmp_path: Path) -> None:
    notebook = tmp_path / "notebook.py"
    session = SimpleNamespace(
        initialization_id=str(tmp_path / "nested" / "notebook.py"),
        app_file_manager=SimpleNamespace(path=str(notebook)),
    )

    assert session_matches_notebook(
        cast(Any, session),
        file_key="notebook.py",
        notebook=notebook,
    )


def test_session_owner_rejects_another_notebook_path(tmp_path: Path) -> None:
    notebook = tmp_path / "notebook.py"
    session = SimpleNamespace(
        initialization_id="other.py",
        app_file_manager=SimpleNamespace(path=str(tmp_path / "other.py")),
    )

    assert not session_matches_notebook(
        cast(Any, session),
        file_key="notebook.py",
        notebook=notebook,
    )


def test_app_host_session_exposes_its_creation_query() -> None:
    session = SimpleNamespace(
        _kernel_manager=SimpleNamespace(
            _app_metadata=SimpleNamespace(
                query_params={"region": "emea", "session_id": "s_private"}
            )
        )
    )

    assert session_creation_query_matches(
        session,
        [("session_id", "s_other1"), ("region", "emea")],
    )
    assert not session_creation_query_matches(session, [("region", "apac")])


def test_first_save_requests_session_resume_before_reload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    notifications: list[object] = []

    def notify(operation: object, from_consumer_id: object) -> None:
        assert from_consumer_id is None
        notifications.append(operation)

    session = SimpleNamespace(
        initialization_id="__new__s_123456",
        notify=notify,
    )
    monkeypatch.setattr(
        session_state_module,
        "current_session",
        lambda _context, _session_id: session,
    )
    assert PrivateSessionState().request_studio_reload(
        cast(Any, object()),
        "s_123456",
    )

    first, second, third = notifications
    assert isinstance(first, QueryParamsSetNotification)
    assert (first.key, first.value) == ("session_id", "s_123456")
    assert isinstance(second, QueryParamsSetNotification)
    assert (second.key, second.value) == ("marimo_studio_resume", "1")
    assert isinstance(third, ReloadNotification)
