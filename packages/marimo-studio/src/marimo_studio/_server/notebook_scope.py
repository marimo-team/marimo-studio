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
        await self.agents.close()
        await self.clients.close()


class NotebookScopeRegistry:
    """Return one service composition for each canonical notebook path."""

    def __init__(self) -> None:
        self._scopes: dict[Path, NotebookScope] = {}

    def get(self, notebook: Path) -> NotebookScope:
        canonical = notebook.resolve()
        return self._scopes.setdefault(canonical, NotebookScope.create(canonical))

    def contains(self, notebook: Path) -> bool:
        return notebook.resolve() in self._scopes

    async def close(self) -> None:
        scopes = tuple(self._scopes.values())
        self._scopes.clear()
        for notebook_scope in scopes:
            await notebook_scope.close()


__all__ = ["NotebookScope", "NotebookScopeRegistry"]
