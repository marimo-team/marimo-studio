"""Resolve one notebook into an explicit Studio workspace lifecycle state."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TypeAlias

from marimo_studio._server.presentation import NotebookPresentation
from marimo_studio._workspace.models import StudioDefinition, StudioWorkspace
from marimo_studio.errors import MarimoStudioError, WorkspaceInitializationError


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


__all__ = [
    "ConfiguredWorkspace",
    "Invalid",
    "NeedsView",
    "Ready",
    "Unconfigured",
    "WorkspaceLifecycle",
    "resolve_workspace_lifecycle",
]
