"""Author and verify the current Marimo Studio workspace."""

from __future__ import annotations

import sys
from types import ModuleType

import agent_plugins

from marimo_studio._authoring.current_api import View as View
from marimo_studio._authoring.current_api import Workspace as Workspace
from marimo_studio._authoring.current_api import (
    current_workspace as current_workspace,
)
from marimo_studio._browser_client.records import ShowResult as ShowResult
from marimo_studio._validation.evidence import ValidationIssue as ValidationIssue
from marimo_studio._validation.records import ValidationReport as ValidationReport
from marimo_studio._views.publication_hold import PublicationHold as PublicationHold
from marimo_studio._views.records import ViewInspection as ViewInspection
from marimo_studio._views.records import ViewSourceChanges as ViewSourceChanges
from marimo_studio._views.records import ViewSourceFile as ViewSourceFile

_DISTRIBUTION_NAME = "marimo-studio"
_SKILL_NAME = "marimo-studio"


def plugin() -> agent_plugins.Plugin:
    """Return the Agent Plugin installed with this Studio version."""
    return agent_plugins.locate(_DISTRIBUTION_NAME)


def skill() -> agent_plugins.Skill:
    """Return Studio's packaged Agent Skill."""
    return plugin().skill(_SKILL_NAME)


__all__ = [
    "PublicationHold",
    "ShowResult",
    "ValidationIssue",
    "ValidationReport",
    "View",
    "ViewInspection",
    "ViewSourceChanges",
    "ViewSourceFile",
    "Workspace",
    "current_workspace",
    "plugin",
    "skill",
]


class _AgentModule(ModuleType):
    @property
    def __doc__(  # pyrefly: ignore [bad-override]  # pyright: ignore[reportIncompatibleVariableOverride]
        self,
    ) -> str | None:
        return agent_plugins.read(_DISTRIBUTION_NAME)

    @__doc__.setter
    def __doc__(  # pyright: ignore[reportIncompatibleVariableOverride]
        self,
        value: str | None,
    ) -> None:
        self.__dict__["__doc__"] = value


sys.modules[__name__].__class__ = _AgentModule
