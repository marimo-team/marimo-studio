"""Search a notebook's tool directories before PATH for provider commands."""

from __future__ import annotations

import os
import shutil
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass


@dataclass(frozen=True)
class ProviderTools:
    """The executable directories provider calls search before PATH.

    ``identity`` names the environment revision that supplied the directories,
    so availability checked for one revision is never reused for another.
    ``problem`` explains why a declared environment supplied no directories.
    """

    directories: tuple[str, ...] = ()
    identity: str = ""
    problem: str | None = None


NO_TOOLS = ProviderTools()
_TOOLS: ContextVar[ProviderTools] = ContextVar(
    "marimo_studio_provider_tools",
    default=NO_TOOLS,
)


@contextmanager
def provider_tools(tools: ProviderTools) -> Iterator[None]:
    """Use ``tools`` for the provider calls made in this context."""
    token = _TOOLS.set(tools)
    try:
        yield
    finally:
        _TOOLS.reset(token)


def current_tools() -> ProviderTools:
    """Return the tools provider calls use in this context."""
    return _TOOLS.get()


def tool_environment(environment: Mapping[str, str] | None = None) -> dict[str, str]:
    """Return ``environment``, or this process's, with the tool directories on PATH."""
    selected = dict(os.environ if environment is None else environment)
    directories = _TOOLS.get().directories
    if directories:
        inherited = selected.get("PATH")
        selected["PATH"] = os.pathsep.join(
            (*directories, inherited) if inherited else directories
        )
    return selected


def find_tool(command: str) -> str | None:
    """Return the executable a provider command named ``command`` runs."""
    return shutil.which(command, path=tool_environment().get("PATH"))
