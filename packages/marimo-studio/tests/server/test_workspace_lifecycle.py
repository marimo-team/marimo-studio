"""Protect workspace middleware startup and shutdown."""

from __future__ import annotations

import asyncio
from pathlib import Path
from threading import Event, get_ident
from types import SimpleNamespace
from typing import Any, cast

import pytest

from marimo_studio._server.notebook_scope import NotebookScope
from marimo_studio._server.workspace_lifecycle import (
    Invalid,
    NeedsView,
    Ready,
    Unconfigured,
    WorkspaceLifecycleResolver,
    resolve_workspace_lifecycle,
)
from marimo_studio.errors import ConfigurationError
from marimo_studio.errors._internal import WorkspaceInitializationError

from ..async_test_support import wait_for_event


def presentation(
    notebook: Path,
    *,
    definition: object | None = None,
    workspace: object | None = None,
    discover_error: Exception | None = None,
    materialize_error: Exception | None = None,
) -> Any:
    def discover_definition() -> object | None:
        if discover_error is not None:
            raise discover_error
        return definition

    def materialize(_definition: object) -> object:
        if materialize_error is not None:
            raise materialize_error
        return workspace

    return SimpleNamespace(
        notebook=notebook,
        discover_definition=discover_definition,
        materialize=materialize,
    )


def test_unconfigured_lifecycle_carries_the_notebook_identity(tmp_path: Path) -> None:
    notebook = tmp_path / "analysis.py"

    lifecycle = resolve_workspace_lifecycle(presentation(notebook))

    assert lifecycle == Unconfigured(notebook)


def test_needs_view_lifecycle_preserves_definition_and_error(tmp_path: Path) -> None:
    notebook = tmp_path / "analysis.py"
    definition = object()
    error = WorkspaceInitializationError("dashboard")

    lifecycle = resolve_workspace_lifecycle(
        presentation(
            notebook,
            definition=definition,
            materialize_error=error,
        )
    )

    assert isinstance(lifecycle, NeedsView)
    assert lifecycle.definition is definition
    assert lifecycle.error is error


def test_ready_lifecycle_carries_one_materialized_workspace(tmp_path: Path) -> None:
    notebook = tmp_path / "analysis.py"
    definition = object()
    workspace = object()

    lifecycle = resolve_workspace_lifecycle(
        presentation(notebook, definition=definition, workspace=workspace)
    )

    assert isinstance(lifecycle, Ready)
    assert lifecycle.definition is definition
    assert lifecycle.workspace is workspace


@pytest.mark.parametrize("phase", ["discovery", "materialization"])
def test_invalid_lifecycle_preserves_expected_failure(
    tmp_path: Path,
    phase: str,
) -> None:
    notebook = tmp_path / "analysis.py"
    definition = object()
    error = ConfigurationError("invalid configuration")
    lifecycle = resolve_workspace_lifecycle(
        presentation(
            notebook,
            definition=definition,
            discover_error=error if phase == "discovery" else None,
            materialize_error=error if phase == "materialization" else None,
        )
    )

    assert isinstance(lifecycle, Invalid)
    assert lifecycle.error is error
    assert lifecycle.definition is (definition if phase == "materialization" else None)


def test_workspace_lifecycle_propagates_unexpected_failures(tmp_path: Path) -> None:
    error = RuntimeError("programming defect")

    with pytest.raises(RuntimeError) as raised:
        resolve_workspace_lifecycle(
            presentation(tmp_path / "analysis.py", discover_error=error)
        )

    assert raised.value is error


def test_workspace_lifecycle_resolution_is_coalesced_off_the_event_loop(
    tmp_path: Path,
) -> None:
    async def exercise() -> None:
        resolver = WorkspaceLifecycleResolver()
        started = Event()
        release = Event()
        caller = get_ident()
        threads: list[int] = []

        def discover_definition() -> None:
            threads.append(get_ident())
            started.set()
            assert release.wait(timeout=2)
            return None

        selected: Any = SimpleNamespace(
            notebook=tmp_path / "analysis.py",
            discover_definition=discover_definition,
        )
        first = asyncio.create_task(resolver.resolve(selected))
        second = asyncio.create_task(resolver.resolve(selected))
        assert await asyncio.to_thread(started.wait, 1)
        await asyncio.sleep(0)
        assert not first.done()
        assert not second.done()

        release.set()
        assert await asyncio.gather(first, second) == [
            Unconfigured(selected.notebook),
            Unconfigured(selected.notebook),
        ]
        assert len(threads) == 1
        assert threads[0] != caller
        await resolver.close()
        with pytest.raises(RuntimeError, match="resolver is closed"):
            await resolver.resolve(selected)

    asyncio.run(exercise())


def test_scope_close_drains_workspace_discovery_before_later_owners(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def exercise() -> None:
        notebook = tmp_path / "analysis.py"
        discovery_started = Event()
        release_discovery = Event()
        discovery_finished = Event()
        lifecycle_close_entered = asyncio.Event()
        downstream_started = asyncio.Event()
        markers: list[str] = []

        def discover_definition() -> None:
            discovery_started.set()
            try:
                assert release_discovery.wait(timeout=2)
                return None
            finally:
                markers.append("discovery")
                discovery_finished.set()

        class AsyncOwner:
            def __init__(self, name: str) -> None:
                self._name = name

            async def close(self) -> None:
                markers.append(self._name)
                downstream_started.set()

        selected: Any = SimpleNamespace(
            notebook=notebook,
            discover_definition=discover_definition,
            close=lambda: markers.append("presentation"),
        )
        resolver = WorkspaceLifecycleResolver()
        resolver_close = resolver.close

        async def close_lifecycle() -> None:
            lifecycle_close_entered.set()
            await resolver_close()

        monkeypatch.setattr(resolver, "close", close_lifecycle)
        scope = NotebookScope(
            notebook=notebook,
            presentation=selected,
            clients=cast(Any, AsyncOwner("clients")),
            agents=cast(Any, AsyncOwner("agents")),
            development=cast(Any, AsyncOwner("development")),
            lifecycle=resolver,
        )
        resolution = asyncio.create_task(resolver.resolve(selected))
        assert await asyncio.to_thread(discovery_started.wait, 1)
        closing = asyncio.create_task(scope.close())
        try:
            await wait_for_event(lifecycle_close_entered)
            closing.cancel()
            closing.cancel()
            assert closing.cancelling() == 2  # pyright: ignore[reportAttributeAccessIssue]
            assert not downstream_started.is_set()
            assert not closing.done()

            release_discovery.set()
            with pytest.raises(asyncio.CancelledError):
                await closing
            assert discovery_finished.is_set()
            assert markers == [
                "discovery",
                "development",
                "presentation",
                "agents",
                "clients",
            ]
            assert resolver._task is None
            await resolver.close()
        finally:
            release_discovery.set()
            await asyncio.gather(resolution, closing, return_exceptions=True)

    asyncio.run(exercise())
