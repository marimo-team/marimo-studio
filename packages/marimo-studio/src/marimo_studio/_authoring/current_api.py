"""Authoring interface bound to the current code-mode Studio tab."""

from __future__ import annotations

from marimo_studio._authoring.validation import validate as validate_workspace
from marimo_studio._authoring.view import show_view
from marimo_studio._authoring.view_api import View as SavedView
from marimo_studio._authoring.workspace import create_view as create_view_operation
from marimo_studio._authoring.workspace_api import Workspace as SavedWorkspace
from marimo_studio._browser_client.records import ShowResult
from marimo_studio._processes.limits import DEFAULT_RUNTIME_TIMEOUT
from marimo_studio._validation.limits import DEFAULT_BROWSER_TIMEOUT
from marimo_studio._validation.records import ValidationLevel, ValidationReport
from marimo_studio._views.records import Starter
from marimo_studio.errors import ConfigurationError


class View(SavedView):
    """One named view attached to the current Studio tab."""

    async def show(self) -> ShowResult:
        """Show this view in the attached Studio tab."""
        return await show_view(
            self.workspace.notebook,
            self.name,
            self.workspace._connection(),
        )

    async def validate(
        self,
        *,
        level: ValidationLevel = "static",
        browser_timeout: float = DEFAULT_BROWSER_TIMEOUT,
        runtime_timeout: float = DEFAULT_RUNTIME_TIMEOUT,
    ) -> ValidationReport:
        """Validate this view at the selected evidence level."""
        return await validate_workspace(
            self.workspace.notebook,
            level=level,
            view=self.name,
            connection=self.workspace._connection() if level == "browser" else None,
            browser_timeout=browser_timeout,
            runtime_timeout=runtime_timeout,
        )


class Workspace(SavedWorkspace):
    """Authoring workspace attached to the current Studio tab."""

    async def create_view(
        self,
        name: str,
        *,
        starter: str | Starter | None = None,
    ) -> View:
        """Create one named view and return its live handle."""
        result = await create_view_operation(self.notebook, name, starter=starter)
        return View._create(self, result.name)

    def view(self, name: str) -> View:
        """Return a live handle for one named view."""
        if not isinstance(name, str) or not name:
            raise ValueError("view name must be a non-empty string")
        return View._create(self, name)


def current_workspace() -> Workspace:
    """Bind authoring to the current code-mode notebook and Studio tab."""
    from marimo_studio._composition import create_code_mode_bridge

    bridge = create_code_mode_bridge()
    path = bridge.active_notebook()
    if not path.is_file():
        raise ConfigurationError(f"Notebook does not exist: {path}")
    return Workspace._create(path, bridge.connection)
