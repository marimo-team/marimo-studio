"""Protect notebook-scoped service ownership."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from starlette.types import Message, Receive, Scope, Send

from marimo_studio._server.middleware import PresentationMiddleware
from marimo_studio._server.notebook_scope import NotebookScope, NotebookScopeRegistry
from marimo_studio._server.ports import ServerAdapters
from marimo_studio._server.presentation.session_ids import SessionIdAllocator


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


class _PresentationCloser:
    def __init__(self, calls: list[str]) -> None:
        self.calls = calls

    def close(self) -> None:
        self.calls.append("presentation")


def test_registry_reuses_a_scope_without_constructing_another(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = NotebookScopeRegistry()
    notebook = tmp_path / "analysis.py"
    created: list[Path] = []
    notebook_scope = cast(NotebookScope, object())

    def create(
        path: Path,
        _project_watcher: object,
        _session_ids: object,
    ) -> NotebookScope:
        created.append(path)
        return notebook_scope

    monkeypatch.setattr(NotebookScope, "create", staticmethod(create))

    assert registry.get(notebook) is notebook_scope
    assert registry.get(notebook) is notebook_scope
    assert created == [notebook.resolve()]


def test_registry_lookup_does_not_resolve_an_already_canonical_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = NotebookScopeRegistry()
    notebook = tmp_path / "analysis.py"
    notebook_scope = cast(NotebookScope, object())
    monkeypatch.setattr(
        NotebookScope,
        "create",
        staticmethod(lambda *_args: notebook_scope),
    )

    def reject_resolve(_path: Path) -> Path:
        raise AssertionError("request routing must not resolve notebook paths")

    monkeypatch.setattr(
        Path,
        "resolve",
        reject_resolve,
    )

    assert registry.get(notebook) is notebook_scope
    assert registry.contains(notebook)


def test_registry_shares_session_identity_across_notebooks(tmp_path: Path) -> None:
    registry = NotebookScopeRegistry(
        session_ids=SessionIdAllocator(key=b"test-key", start=0)
    )
    first = registry.get(tmp_path / "first.py")
    second = registry.get(tmp_path / "second.py")
    sessions = cast(
        Any,
        SimpleNamespace(ownership=lambda _context, _session_id: "unclaimed"),
    )
    context = cast(Any, SimpleNamespace())
    expected = SessionIdAllocator(key=b"test-key", start=0)

    first_pair = first.session_ids.allocate_pair(context, sessions)
    second_pair = second.session_ids.allocate_pair(context, sessions)

    assert first.session_ids is second.session_ids
    assert first_pair == expected.allocate_pair(context, sessions)
    assert second_pair == expected.allocate_pair(context, sessions)


def test_scope_closes_every_later_owner_after_shutdown_fails(tmp_path: Path) -> None:
    for owner in ("development", "agents"):
        calls: list[str] = []
        failure = RuntimeError(f"{owner} shutdown failed")
        notebook_scope = NotebookScope(
            notebook=tmp_path / "analysis.py",
            presentation=cast(Any, _PresentationCloser(calls)),
            clients=cast(Any, _AsyncCloser("clients", calls)),
            agents=cast(
                Any,
                _AsyncCloser("agents", calls, failure if owner == "agents" else None),
            ),
            development=cast(
                Any,
                _AsyncCloser(
                    "development",
                    calls,
                    failure if owner == "development" else None,
                ),
            ),
        )

        with pytest.raises(RuntimeError, match=f"{owner} shutdown failed"):
            asyncio.run(notebook_scope.close())

        assert calls == ["development", "presentation", "agents", "clients"], owner


@pytest.mark.parametrize(
    "blocked_owner",
    ("lifecycle", "development", "agents", "clients"),
)
def test_scope_close_drains_each_async_owner_before_advancing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    blocked_owner: str,
) -> None:
    async def exercise() -> None:
        notebook = tmp_path / "analysis.py"
        notebook.write_text("", encoding="utf-8")
        notebook_scope = NotebookScope.create(notebook)
        calls: list[str] = []
        close_entered = asyncio.Event()
        release_close = asyncio.Event()
        owner_order = (
            ("lifecycle", notebook_scope.lifecycle),
            ("development", notebook_scope.development),
            ("agents", notebook_scope.agents),
            ("clients", notebook_scope.clients),
        )

        for name, owner in owner_order:
            close_owner = owner.close

            async def close_async_owner(
                *,
                selected: str = name,
                close: Any = close_owner,
            ) -> None:
                calls.append(f"{selected}:enter")
                if selected == blocked_owner:
                    close_entered.set()
                    await release_close.wait()
                await close()
                calls.append(f"{selected}:done")

            monkeypatch.setattr(owner, "close", close_async_owner)

        close_presentation = notebook_scope.presentation.close

        def close_sync_owner() -> None:
            calls.append("presentation:enter")
            close_presentation()
            calls.append("presentation:done")

        monkeypatch.setattr(notebook_scope.presentation, "close", close_sync_owner)
        sequence = [
            "lifecycle:enter",
            "lifecycle:done",
            "development:enter",
            "development:done",
            "presentation:enter",
            "presentation:done",
            "agents:enter",
            "agents:done",
            "clients:enter",
            "clients:done",
        ]
        blocked_index = sequence.index(f"{blocked_owner}:enter")
        closing = asyncio.create_task(notebook_scope.close())
        try:
            await close_entered.wait()
            closing.cancel()
            await asyncio.sleep(0)
            closing.cancel()
            await asyncio.sleep(0)
            assert not closing.done()
            assert calls == sequence[: blocked_index + 1]

            release_close.set()
            with pytest.raises(asyncio.CancelledError):
                await closing
            assert calls == sequence

            await notebook_scope.close()
            assert calls == [*sequence, *sequence]
        finally:
            release_close.set()
            await asyncio.gather(closing, return_exceptions=True)

    asyncio.run(exercise())


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
    assert registry.contains(tmp_path / "first.py")
    assert not registry.contains(tmp_path / "second.py")

    first.failure = None
    asyncio.run(registry.close())

    assert calls == ["first", "second", "first"]
    assert not registry.contains(tmp_path / "first.py")
    with pytest.raises(RuntimeError, match="registry is closed"):
        registry.get(tmp_path / "late.py")


def test_middleware_restores_adapters_after_scope_shutdown_fails() -> None:
    calls: list[str] = []

    class AdapterHandle:
        closed = False

        def close(self) -> None:
            if self.closed:
                return
            self.closed = True
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
                server=SimpleNamespace(),
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

    assert calls == ["open", "scopes", "adapters", "scopes"]
