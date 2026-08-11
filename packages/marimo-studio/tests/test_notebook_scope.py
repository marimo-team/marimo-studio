from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from starlette.types import Message, Receive, Scope, Send

from marimo_studio._capabilities import ServerAdapters
from marimo_studio._server.middleware import PresentationMiddleware
from marimo_studio._server.notebook_scope import NotebookScope, NotebookScopeRegistry


class _AsyncCloser:
    def __init__(
        self,
        name: str,
        calls: list[str],
        failure: BaseException | None = None,
    ) -> None:
        self.name = name
        self.calls = calls
        self.failure = failure

    async def close(self) -> None:
        self.calls.append(self.name)
        if self.failure is not None:
            raise self.failure


def test_registry_reuses_a_scope_without_constructing_another(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = NotebookScopeRegistry()
    notebook = tmp_path / "analysis.py"
    created: list[Path] = []
    notebook_scope = cast(NotebookScope, object())

    def create(path: Path) -> NotebookScope:
        created.append(path)
        return notebook_scope

    monkeypatch.setattr(NotebookScope, "create", staticmethod(create))

    assert registry.get(notebook) is notebook_scope
    assert registry.get(notebook) is notebook_scope
    assert created == [notebook.resolve()]


def test_scope_closes_clients_after_agent_shutdown_fails(tmp_path: Path) -> None:
    calls: list[str] = []
    notebook_scope = NotebookScope(
        notebook=tmp_path / "analysis.py",
        presentation=cast(Any, object()),
        clients=cast(Any, _AsyncCloser("clients", calls)),
        agents=cast(
            Any,
            _AsyncCloser("agents", calls, RuntimeError("agent shutdown failed")),
        ),
    )

    with pytest.raises(RuntimeError, match="agent shutdown failed"):
        asyncio.run(notebook_scope.close())

    assert calls == ["agents", "clients"]


def test_registry_closes_every_scope_after_one_fails(tmp_path: Path) -> None:
    calls: list[str] = []
    registry = NotebookScopeRegistry()
    first = _AsyncCloser("first", calls, RuntimeError("scope shutdown failed"))
    second = _AsyncCloser("second", calls)
    registry._scopes = {
        (tmp_path / "first.py").resolve(): cast(Any, first),
        (tmp_path / "second.py").resolve(): cast(Any, second),
    }

    with pytest.raises(RuntimeError, match="scope shutdown failed"):
        asyncio.run(registry.close())

    assert calls == ["first", "second"]
    assert not registry.contains(tmp_path / "first.py")
    assert not registry.contains(tmp_path / "second.py")


def test_middleware_restores_adapters_after_scope_shutdown_fails() -> None:
    calls: list[str] = []

    class AdapterHandle:
        def close(self) -> None:
            calls.append("adapters")

    class AdapterLifecycle:
        def open(self) -> AdapterHandle:
            calls.append("open")
            return AdapterHandle()

    async def downstream(
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        del scope, receive
        await send({"type": "lifespan.shutdown.complete"})

    middleware = PresentationMiddleware(
        downstream,
        lambda: cast(
            ServerAdapters,
            SimpleNamespace(
                session_state=SimpleNamespace(),
                browser=SimpleNamespace(),
                lifecycle=AdapterLifecycle(),
            ),
        ),
    )
    middleware._notebooks = cast(
        Any,
        _AsyncCloser("scopes", calls, RuntimeError("scope shutdown failed")),
    )
    scope: Scope = {
        "type": "lifespan",
        "asgi": {"version": "3.0", "spec_version": "2.0"},
    }

    async def receive() -> Message:
        return {"type": "lifespan.shutdown"}

    async def send(_message: Message) -> None:
        return None

    with pytest.raises(RuntimeError, match="scope shutdown failed"):
        asyncio.run(middleware(scope, receive, send))

    assert calls == ["open", "scopes", "adapters"]
