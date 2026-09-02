"""Compose notebook-scoped presentation, client, and agent services."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from marimo_studio._processes.ownership import (
    propagate_cancellation,
    settle_ownership,
)
from marimo_studio._server.agent.clients import StudioClientRegistry
from marimo_studio._server.agent.coordinator import AgentCoordinator
from marimo_studio._server.development.coordinator import DevelopmentCoordinator
from marimo_studio._server.presentation.service import NotebookPresentation
from marimo_studio._server.presentation.session_ids import SessionIdAllocator
from marimo_studio._server.workspace_lifecycle import WorkspaceLifecycleResolver

if TYPE_CHECKING:
    from marimo_studio._server.development.ports import ProjectWatcherFactory


@dataclass(frozen=True)
class NotebookScope:
    notebook: Path
    presentation: NotebookPresentation
    clients: StudioClientRegistry
    agents: AgentCoordinator
    development: DevelopmentCoordinator = field(default_factory=DevelopmentCoordinator)
    session_ids: SessionIdAllocator = field(
        default_factory=SessionIdAllocator,
        compare=False,
        repr=False,
    )
    lifecycle: WorkspaceLifecycleResolver = field(
        default_factory=WorkspaceLifecycleResolver,
        compare=False,
        repr=False,
    )

    @classmethod
    def create(
        cls,
        notebook: Path,
        project_watcher: ProjectWatcherFactory | None = None,
        session_ids: SessionIdAllocator | None = None,
    ) -> NotebookScope:
        clients = StudioClientRegistry()
        development = DevelopmentCoordinator(project_watcher=project_watcher)
        return cls(
            notebook=notebook,
            presentation=NotebookPresentation(notebook, development=development),
            clients=clients,
            agents=AgentCoordinator(clients),
            development=development,
            session_ids=session_ids or SessionIdAllocator(),
        )

    async def close(self) -> None:
        _result, cancellation = await settle_ownership(self._close_owned())
        propagate_cancellation(cancellation)

    async def _close_owned(self) -> None:
        failure: BaseException | None = None
        cancellation: asyncio.CancelledError | None = None

        async def close_async(close: Callable[[], Awaitable[None]]) -> None:
            nonlocal cancellation, failure
            try:
                _result, owner_cancellation = await settle_ownership(close())
            except asyncio.CancelledError as error:
                if cancellation is None:
                    cancellation = error
            except BaseException as error:
                if failure is None:
                    failure = error
            else:
                if cancellation is None:
                    cancellation = owner_cancellation

        await close_async(self.lifecycle.close)
        await close_async(self.development.close)
        try:
            self.presentation.close()
        except asyncio.CancelledError as error:
            if cancellation is None:
                cancellation = error
        except BaseException as error:
            if failure is None:
                failure = error
        for resource in (self.agents, self.clients):
            await close_async(resource.close)
        if failure is not None:
            raise failure
        propagate_cancellation(cancellation)


class NotebookScopeRegistry:
    """Return one service composition for each canonical notebook path."""

    def __init__(
        self,
        project_watcher: ProjectWatcherFactory | None = None,
        *,
        session_ids: SessionIdAllocator | None = None,
    ) -> None:
        self._scopes: dict[Path, NotebookScope] = {}
        self._project_watcher = project_watcher
        self._session_ids = session_ids or SessionIdAllocator()
        self._closed = False

    def get(self, notebook: Path) -> NotebookScope:
        if self._closed:
            raise RuntimeError("Notebook scope registry is closed")
        canonical = Path(os.path.abspath(notebook))
        notebook_scope = self._scopes.get(canonical)
        if notebook_scope is None:
            notebook_scope = NotebookScope.create(
                canonical,
                self._project_watcher,
                self._session_ids,
            )
            self._scopes[canonical] = notebook_scope
        return notebook_scope

    def contains(self, notebook: Path) -> bool:
        return Path(os.path.abspath(notebook)) in self._scopes

    async def close(self) -> None:
        self._closed = True
        scopes = tuple(self._scopes.items())
        failure: BaseException | None = None
        for notebook, notebook_scope in scopes:
            try:
                await notebook_scope.close()
            except BaseException as error:
                if failure is None:
                    failure = error
            else:
                if self._scopes.get(notebook) is notebook_scope:
                    self._scopes.pop(notebook)
        self._session_ids.close()
        if failure is not None:
            raise failure
