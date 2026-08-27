"""Protect synchronous Marimo session ownership classification."""

from types import SimpleNamespace
from typing import Any, cast

from marimo_studio._compat.server.session_state import (
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
