"""Notebook-bound interface over workspace authoring operations."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from marimo_studio._authoring.validation import validate as validate_workspace
from marimo_studio._authoring.view_api import View
from marimo_studio._authoring.workspace import (
    ProviderReport,
    bind_cell,
    diagnose_providers,
)
from marimo_studio._authoring.workspace import create_view as create_view_operation
from marimo_studio._authoring.workspace import inspect_notebook as inspect_operation
from marimo_studio._authoring.workspace import starters as list_starters
from marimo_studio._authoring.workspace import status as workspace_status
from marimo_studio._browser_client.transport import StudioServerConnection
from marimo_studio._notebook.records import CellSelector, InspectionResult
from marimo_studio._processes.limits import DEFAULT_RUNTIME_TIMEOUT
from marimo_studio._validation.limits import DEFAULT_BROWSER_TIMEOUT
from marimo_studio._validation.records import ValidationLevel, ValidationReport
from marimo_studio._views.records import Starter, StudioOverview
from marimo_studio._workspace.models import BindingResult
from marimo_studio.errors import ConfigurationError


@dataclass(frozen=True, init=False)
class Workspace:
    """Notebook-bound Studio authoring workspace."""

    notebook: Path
    _connection_factory: Callable[[], StudioServerConnection] | None

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        raise TypeError("Use marimo_studio.agent.open() to create a workspace")

    @classmethod
    def _create(
        cls,
        notebook: Path,
        connection_factory: Callable[[], StudioServerConnection] | None,
    ) -> Workspace:
        workspace = object.__new__(cls)
        object.__setattr__(workspace, "notebook", notebook)
        object.__setattr__(workspace, "_connection_factory", connection_factory)
        return workspace

    def _connection(self) -> StudioServerConnection | None:
        if self._connection_factory is None:
            return None
        return self._connection_factory()

    async def status(self) -> StudioOverview:
        """Return configuration and view state for this notebook."""
        return await workspace_status(self.notebook)

    async def inspect_notebook(
        self,
        *,
        runtime: bool = False,
        include_code: bool = False,
        selectors: tuple[CellSelector, ...] = (),
        output_expressions: bool = False,
        limit: int | None = None,
        runtime_timeout: float = DEFAULT_RUNTIME_TIMEOUT,
    ) -> InspectionResult:
        """Return selected cells with optional isolated runtime evidence."""
        return await inspect_operation(
            self.notebook,
            runtime=runtime,
            include_code=include_code,
            selectors=selectors,
            output_expressions=output_expressions,
            limit=limit,
            runtime_timeout=runtime_timeout,
        )

    async def starters(self) -> tuple[Starter, ...]:
        """Return installed view starters and their availability."""
        return await list_starters()

    async def create_view(
        self,
        name: str,
        *,
        starter: str | Starter | None = None,
    ) -> View:
        """Create one named view and return its handle."""
        result = await create_view_operation(self.notebook, name, starter=starter)
        return View._create(self, result.name)

    def view(self, name: str) -> View:
        """Return a handle for one named view."""
        if not isinstance(name, str) or not name:
            raise ValueError("view name must be a non-empty string")
        return View._create(self, name)

    async def bind(
        self,
        alias: str,
        cell: CellSelector,
        *,
        overwrite: bool = False,
    ) -> BindingResult:
        """Give one notebook cell a stable symbolic target."""
        return await bind_cell(
            self.notebook,
            alias,
            cell,
            overwrite=overwrite,
        )

    async def validate(
        self,
        *,
        level: ValidationLevel = "static",
        view: str | None = None,
        browser_timeout: float = DEFAULT_BROWSER_TIMEOUT,
        runtime_timeout: float = DEFAULT_RUNTIME_TIMEOUT,
    ) -> ValidationReport:
        """Validate saved source, runtime execution, or browser evidence."""
        return await validate_workspace(
            self.notebook,
            level=level,
            view=view,
            connection=self._connection() if level == "browser" else None,
            browser_timeout=browser_timeout,
            runtime_timeout=runtime_timeout,
        )


def open_workspace(notebook: str | Path | None = None) -> Workspace:
    """Open a saved notebook or bind to the active code-mode notebook."""
    connection_factory: Callable[[], StudioServerConnection] | None = None
    if notebook is None:
        from marimo_studio._composition import create_code_mode_bridge

        bridge = create_code_mode_bridge()
        path = bridge.active_notebook()
        connection_factory = bridge.connection
    else:
        path = Path(notebook).expanduser().resolve()
    if not path.is_file():
        raise ConfigurationError(f"Notebook does not exist: {path}")
    return Workspace._create(path, connection_factory)


async def doctor(provider: str | None = None) -> ProviderReport:
    """Return installed provider diagnostics."""
    return await diagnose_providers(provider)
