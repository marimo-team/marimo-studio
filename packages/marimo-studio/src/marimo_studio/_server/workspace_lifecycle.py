"""Resolve one notebook into an explicit Studio workspace lifecycle state."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import TypeAlias

from marimo_studio._processes.ownership import (
    propagate_cancellation,
    settle_ownership,
)
from marimo_studio._server.presentation.service import NotebookPresentation
from marimo_studio._workspace.models import StudioDefinition, StudioWorkspace
from marimo_studio.errors import MarimoStudioError
from marimo_studio.errors._internal import WorkspaceInitializationError


@dataclass(frozen=True)
class Unconfigured:
    notebook: Path


@dataclass(frozen=True)
class NeedsView:
    definition: StudioDefinition
    error: WorkspaceInitializationError


@dataclass(frozen=True)
class Ready:
    definition: StudioDefinition
    workspace: StudioWorkspace


@dataclass(frozen=True)
class Invalid:
    notebook: Path
    error: MarimoStudioError
    definition: StudioDefinition | None = None


WorkspaceLifecycle: TypeAlias = Unconfigured | NeedsView | Ready | Invalid
ConfiguredWorkspace: TypeAlias = NeedsView | Ready


def resolve_workspace_lifecycle(
    presentation: NotebookPresentation,
) -> WorkspaceLifecycle:
    try:
        definition = presentation.discover_definition()
    except MarimoStudioError as error:
        return Invalid(presentation.notebook, error)
    if definition is None:
        return Unconfigured(presentation.notebook)
    try:
        return Ready(definition, presentation.materialize(definition))
    except WorkspaceInitializationError as error:
        return NeedsView(definition, error)
    except MarimoStudioError as error:
        return Invalid(presentation.notebook, error, definition)


class WorkspaceLifecycleResolver:
    """Coalesce filesystem lifecycle resolution outside the event loop."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._close_lock = asyncio.Lock()
        self._task: asyncio.Task[WorkspaceLifecycle] | None = None
        self._closed = False

    async def resolve(
        self,
        presentation: NotebookPresentation,
    ) -> WorkspaceLifecycle:
        async with self._lock:
            if self._closed:
                raise RuntimeError("Workspace lifecycle resolver is closed")
            task = self._task
            if task is None:
                task = asyncio.create_task(self._resolve_owned(presentation))
                self._task = task
        try:
            return await asyncio.shield(task)
        finally:
            async with self._lock:
                if self._task is task and task.done():
                    self._task = None

    async def close(self) -> None:
        _result, cancellation = await settle_ownership(self._close_owned())
        propagate_cancellation(cancellation)

    async def _resolve_owned(
        self,
        presentation: NotebookPresentation,
    ) -> WorkspaceLifecycle:
        worker = asyncio.create_task(
            asyncio.to_thread(resolve_workspace_lifecycle, presentation)
        )
        try:
            return await asyncio.shield(worker)
        except asyncio.CancelledError as cancellation:
            await settle_ownership(asyncio.gather(worker, return_exceptions=True))
            raise cancellation

    async def _close_owned(self) -> None:
        async with self._close_lock:
            async with self._lock:
                self._closed = True
                task = self._task
            if task is None:
                return
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            async with self._lock:
                if self._task is task and task.done():
                    self._task = None
