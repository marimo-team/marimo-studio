"""Describe a notebook's pixi script environment through Marimo's pixi backend."""

from __future__ import annotations

from pathlib import Path

from marimo_studio._notebook.ports import ScriptEnvironmentInstall
from marimo_studio.errors import DependencyError


class PixiScriptEnvironments:
    """Marimo's `pixi install --script` command and its report."""

    def selected(self) -> bool:
        from marimo._environments.backends import current_backend

        return current_backend() == "pixi"

    def install(self, notebook: Path) -> ScriptEnvironmentInstall:
        """Return the command `marimo edit --sandbox=pixi` runs before a kernel starts.

        The command creates or reuses the notebook's cached environment and
        reports its location on standard error.
        """
        from marimo._environments import pixi
        from marimo._environments.errors import EnvironmentManagerError

        try:
            command = tuple(pixi._sync_command(str(notebook)))
        except EnvironmentManagerError as error:
            raise DependencyError(str(error)) from error

        def executable_directories(report: str) -> tuple[str, ...]:
            try:
                environment = pixi._parse_sync_report(report)
            except EnvironmentManagerError as error:
                raise DependencyError(str(error)) from error
            return pixi._activation_path_entries(environment.root)

        return ScriptEnvironmentInstall(
            command, pixi.command_env(), executable_directories
        )
