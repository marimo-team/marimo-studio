"""Author and verify the current Marimo Studio workspace."""

from __future__ import annotations

import sys
from textwrap import indent
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


def agent_plugin() -> agent_plugins.Plugin:
    """Return the Agent Plugin installed with this Studio version."""
    return agent_plugins.locate(_DISTRIBUTION_NAME)


def agent_skill() -> agent_plugins.Skill:
    """Return Studio's packaged Agent Skill."""
    return agent_plugin().skill(_SKILL_NAME)


def _module_help(summary: str) -> str:
    plugin = agent_plugin()
    skill = plugin.skill(_SKILL_NAME)
    tree = indent(plugin.tree(max_depth=3, max_files=50), "    ")
    return f"""{summary}

The installed Agent Plugin carries the complete Studio workflow and the
resources that match this package version:

{tree}

Read the Studio skill instructions before authoring a view:

    {skill / "SKILL.md"}

Traverse the same resources programmatically:

    import marimo_studio.agent as studio_agent

    resources = studio_agent.agent_plugin()
    skill = studio_agent.agent_skill()
    print(resources)
    print(skill.body)

Then bind authoring to the current code-mode notebook and Studio tab:

    workspace = studio_agent.current_workspace()
"""


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
    "agent_plugin",
    "agent_skill",
    "current_workspace",
]


class _AgentModule(ModuleType):
    @property
    def __doc__(  # pyrefly: ignore [bad-override]  # pyright: ignore[reportIncompatibleVariableOverride]
        self,
    ) -> str | None:
        summary = self.__dict__.get("__doc__")
        return _module_help(summary) if isinstance(summary, str) else None

    @__doc__.setter
    def __doc__(  # pyright: ignore[reportIncompatibleVariableOverride]
        self,
        value: str | None,
    ) -> None:
        self.__dict__["__doc__"] = value


sys.modules[__name__].__class__ = _AgentModule
