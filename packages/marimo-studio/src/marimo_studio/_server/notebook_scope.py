"""Compose notebook-scoped presentation, client, and agent services."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from marimo_studio._server.agent_coordinator import AgentCoordinator
from marimo_studio._server.live_clients import StudioClientRegistry
from marimo_studio._server.presentation import NotebookPresentation


@dataclass(frozen=True)
class NotebookScope:
    notebook: Path
    presentation: NotebookPresentation
    clients: StudioClientRegistry
    agents: AgentCoordinator

    @classmethod
    def create(cls, notebook: Path) -> NotebookScope:
        clients = StudioClientRegistry()
        return cls(
            notebook=notebook,
            presentation=NotebookPresentation(notebook),
            clients=clients,
            agents=AgentCoordinator(clients),
        )

    async def close(self) -> None:
        failure: BaseException | None = None
        for resource in (self.agents, self.clients):
            try:
                await resource.close()
            except BaseException as error:
                if failure is None:
                    failure = error
        if failure is not None:
            raise failure


class NotebookScopeRegistry:
    """Return one service composition for each canonical notebook path."""

    def __init__(self) -> None:
        self._scopes: dict[Path, NotebookScope] = {}

    def get(self, notebook: Path) -> NotebookScope:
        canonical = notebook.resolve()
        notebook_scope = self._scopes.get(canonical)
        if notebook_scope is None:
            notebook_scope = NotebookScope.create(canonical)
            self._scopes[canonical] = notebook_scope
        return notebook_scope

    def contains(self, notebook: Path) -> bool:
        return notebook.resolve() in self._scopes

    async def close(self) -> None:
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
        if failure is not None:
            raise failure


__all__ = ["NotebookScope", "NotebookScopeRegistry"]
