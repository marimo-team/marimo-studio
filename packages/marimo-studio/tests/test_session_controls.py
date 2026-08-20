from __future__ import annotations

import asyncio
from collections.abc import Mapping
from pathlib import Path
from types import SimpleNamespace

import marimo_export.sessions as marimo_export_sessions
import pytest
from marimo_export.index import ControlBinding, ControlIndexStep

from marimo_studio._capabilities import ServerContext, ServerHandle
from marimo_studio._server.session_controls import SessionControlBindingReader
from marimo_studio.errors import RuntimeSyncError


def _context() -> ServerContext:
    return ServerContext(
        notebook=Path("/workspace/notebook.py"),
        file_key="notebook.py",
        base_url="/proxy/app",
        internal_url="http://127.0.0.1:4312/proxy/app/",
        mode="edit",
        dev=True,
        routing_query=(),
        user_config={},
        config_overrides={},
        server_token="server-token",
        handle=ServerHandle(object()),
    )


def test_session_controls_use_lightweight_observation_and_reuse_across_views(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str, str]] = []
    ordinary_global = list(range(100_001))
    control_bindings = {
        "editor-root": ControlBinding("filters", ()),
        "editor-child": ControlBinding("filters", (ControlIndexStep(0),)),
    }

    class Client:
        def __init__(self, server: str, *, server_token: str) -> None:
            self.server = server
            self.server_token = server_token

        def __enter__(self) -> Client:
            return self

        def __exit__(self, *_error: object) -> None:
            return None

        def session(self, session_id: str) -> SimpleNamespace:
            calls.append((self.server, self.server_token, session_id))
            return SimpleNamespace(
                ordinary_global=ordinary_global,
                inspect=lambda: (_ for _ in ()).throw(
                    AssertionError("control polling used full session inspection")
                ),
                observe_inputs=lambda: SimpleNamespace(
                    control_bindings=control_bindings,
                ),
            )

    monkeypatch.setattr(marimo_export_sessions, "Client", Client)

    async def inspect_twice() -> tuple[object, object]:
        reader = SessionControlBindingReader()
        first = await reader.bindings(
            _context(),
            "s_123456",
            "notebook-revision-1",
            0,
        )
        second = await reader.bindings(
            _context(),
            "s_123456",
            "notebook-revision-1",
            0,
        )
        return first, second

    bindings, repeated = asyncio.run(inspect_twice())

    assert bindings == {
        "editor-root": {"input": "filters", "path": ()},
        "editor-child": {
            "input": "filters",
            "path": ({"kind": "index", "value": 0},),
        },
    }
    assert repeated is bindings
    assert calls == [("http://127.0.0.1:4312/proxy/app/", "server-token", "s_123456")]


@pytest.mark.parametrize(
    ("next_session", "next_revision", "next_control_revision"),
    (
        ("s_123456", "notebook-revision-2", 0),
        ("s_654321", "notebook-revision-1", 0),
        ("s_123456", "notebook-revision-1", 1),
    ),
    ids=("notebook-source", "session", "ordinary-run"),
)
def test_session_control_cache_invalidates_runtime_identity(
    monkeypatch: pytest.MonkeyPatch,
    next_session: str,
    next_revision: str,
    next_control_revision: int,
) -> None:
    calls: list[str] = []

    class Client:
        def __init__(self, _server: str, *, server_token: str) -> None:
            assert server_token == "server-token"

        def __enter__(self) -> Client:
            return self

        def __exit__(self, *_error: object) -> None:
            return None

        def session(self, session_id: str) -> SimpleNamespace:
            calls.append(session_id)
            return SimpleNamespace(
                observe_inputs=lambda: SimpleNamespace(
                    control_bindings={},
                )
            )

    monkeypatch.setattr(marimo_export_sessions, "Client", Client)

    async def inspect_replacement() -> None:
        reader = SessionControlBindingReader()
        await reader.bindings(
            _context(),
            "s_123456",
            "notebook-revision-1",
            0,
        )
        await reader.bindings(
            _context(),
            next_session,
            next_revision,
            next_control_revision,
        )

    asyncio.run(inspect_replacement())

    assert calls == ["s_123456", next_session]


def test_completed_run_refreshes_conditionally_constructed_control_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inspections = 0

    class Client:
        def __init__(self, _server: str, *, server_token: str) -> None:
            assert server_token == "server-token"

        def __enter__(self) -> Client:
            return self

        def __exit__(self, *_error: object) -> None:
            return None

        def session(self, _session_id: str) -> SimpleNamespace:
            def observe_inputs() -> SimpleNamespace:
                nonlocal inspections
                inspections += 1
                return SimpleNamespace(
                    control_bindings={
                        f"control-{inspections}": ControlBinding(
                            "conditional",
                            (),
                        )
                    }
                )

            return SimpleNamespace(observe_inputs=observe_inputs)

    monkeypatch.setattr(marimo_export_sessions, "Client", Client)

    async def inspect_runs() -> tuple[Mapping[str, object], Mapping[str, object]]:
        reader = SessionControlBindingReader()
        first = await reader.bindings(
            _context(),
            "s_123456",
            "notebook-revision-1",
            0,
        )
        second = await reader.bindings(
            _context(),
            "s_123456",
            "notebook-revision-1",
            1,
        )
        return first, second

    first, second = asyncio.run(inspect_runs())

    assert set(first) == {"control-1"}
    assert set(second) == {"control-2"}


def test_session_controls_require_trusted_internal_endpoint() -> None:
    context = _context()
    unavailable = ServerContext(
        notebook=context.notebook,
        file_key=context.file_key,
        base_url=context.base_url,
        internal_url=None,
        mode=context.mode,
        dev=context.dev,
        routing_query=context.routing_query,
        user_config=context.user_config,
        config_overrides=context.config_overrides,
        server_token=context.server_token,
        handle=context.handle,
    )

    with pytest.raises(RuntimeSyncError, match="local server endpoint"):
        asyncio.run(
            SessionControlBindingReader().bindings(
                unavailable,
                "s_123456",
                "notebook-revision-1",
                0,
            )
        )


def test_session_control_inspection_failure_is_transient(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Client:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            raise OSError("connection closed")

    monkeypatch.setattr(marimo_export_sessions, "Client", Client)

    with pytest.raises(RuntimeSyncError, match="live control metadata"):
        asyncio.run(
            SessionControlBindingReader().bindings(
                _context(),
                "s_123456",
                "notebook-revision-1",
                0,
            )
        )
