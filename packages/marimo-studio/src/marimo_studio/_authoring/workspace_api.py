"""Notebook-bound interface over workspace authoring operations."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, TypeVar

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
from marimo_studio._notebook.records import (
    CellSelector,
    InspectionContext,
    InspectionResult,
)
from marimo_studio._processes.limits import DEFAULT_RUNTIME_TIMEOUT
from marimo_studio._validation.records import ValidationReport
from marimo_studio._views.records import Starter, StudioOverview
from marimo_studio._workspace import load_studio
from marimo_studio._workspace.config import discover_studio_definition
from marimo_studio._workspace.generation import (
    provider_free_catalog_generation,
    view_name_generation,
)
from marimo_studio._workspace.models import (
    BindingResult,
    StudioDefinition,
    StudioWorkspace,
)
from marimo_studio.errors import ConfigurationError, WorkspaceGenerationConflictError
from marimo_studio.errors._internal import WorkspaceInitializationError

_Workspace = TypeVar("_Workspace", bound="Workspace")


def _definition_catalog_generation(definition: StudioDefinition) -> str:
    try:
        return provider_free_catalog_generation(definition)
    except (ConfigurationError, OSError):
        return definition.config_generation


@dataclass(frozen=True, init=False)
class Workspace:
    """Notebook-bound Studio authoring workspace."""

    notebook: Path
    _connection_factory: Callable[[], StudioServerConnection] | None
    _catalog_generation: str | None

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        raise TypeError(
            "Use marimo_studio.authoring.open_workspace() or "
            "marimo_studio.agent.current_workspace()"
        )

    @classmethod
    def _create(
        cls: type[_Workspace],
        notebook: Path,
        connection_factory: Callable[[], StudioServerConnection] | None,
    ) -> _Workspace:
        workspace = object.__new__(cls)
        object.__setattr__(workspace, "notebook", notebook)
        object.__setattr__(workspace, "_connection_factory", connection_factory)
        definition = discover_studio_definition(notebook)
        if definition is None:
            studio = None
        else:
            try:
                studio = load_studio(notebook)
            except (ConfigurationError, WorkspaceInitializationError):
                studio = None
        object.__setattr__(
            workspace,
            "_catalog_generation",
            (
                studio.catalog_generation
                if studio is not None
                else (
                    _definition_catalog_generation(definition)
                    if definition is not None
                    else None
                )
            ),
        )
        return workspace

    def _capture_workspace(self, studio: StudioWorkspace) -> None:
        self._capture_catalog_generation(studio.catalog_generation)

    def _capture_catalog_generation(self, generation: str) -> None:
        object.__setattr__(self, "_catalog_generation", generation)

    def _current_workspace(self) -> StudioWorkspace:
        studio = load_studio(self.notebook)
        if (
            self._catalog_generation is not None
            and studio.catalog_generation != self._catalog_generation
        ):
            raise WorkspaceGenerationConflictError()
        if self._catalog_generation is None:
            self._capture_workspace(studio)
        return studio

    def _connection(self) -> StudioServerConnection | None:
        if self._connection_factory is None:
            return None
        return self._connection_factory()

    def _fallback_view_generation(self, name: str) -> str | None:
        definition = discover_studio_definition(self.notebook)
        if definition is None:
            return None
        try:
            return view_name_generation(definition.view_root, name)
        except (ConfigurationError, OSError):
            return None

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
        context: InspectionContext = "selected",
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
            context=context,
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
        result = await create_view_operation(
            self.notebook,
            name,
            starter=starter,
            expected_catalog_generation=self._catalog_generation,
        )
        assert result.workspace is not None
        self._capture_workspace(result.workspace)
        return View._create(
            self,
            result.name,
            catalog_generation=result.workspace.catalog_generation,
            generation=result.workspace.view_generations[result.name],
        )

    def view(self, name: str) -> View:
        """Return a handle for one named view."""
        if not isinstance(name, str) or not name:
            raise ValueError("view name must be a non-empty string")
        if self._catalog_generation is None:
            return View._create(
                self,
                name,
                catalog_generation=None,
                generation=None,
            )
        try:
            studio = self._current_workspace()
        except ConfigurationError:
            return View._create(
                self,
                name,
                catalog_generation=self._catalog_generation,
                generation=self._fallback_view_generation(name),
            )
        return View._create(
            self,
            name,
            catalog_generation=studio.catalog_generation,
            generation=studio.view_generations.get(name),
        )

    async def bind(
        self,
        alias: str,
        cell: CellSelector,
        *,
        overwrite: bool = False,
    ) -> BindingResult:
        """Give an anonymous notebook cell a stable symbolic target.

        Native named cells are already valid ``marimo-cell`` targets and need
        no binding.
        """
        if self._catalog_generation is None:
            self._current_workspace()
        result = await bind_cell(
            self.notebook,
            alias,
            cell,
            overwrite=overwrite,
            expected_catalog_generation=self._catalog_generation,
        )
        self._capture_catalog_generation(result.catalog_generation)
        return result

    async def validate(
        self,
        *,
        level: Literal["static", "runtime"] = "static",
        view: str | None = None,
        runtime_timeout: float = DEFAULT_RUNTIME_TIMEOUT,
    ) -> ValidationReport:
        """Validate saved source or isolated notebook execution."""
        return await validate_workspace(
            self.notebook,
            level=level,
            view=view,
            runtime_timeout=runtime_timeout,
        )


def open_workspace(notebook: str | Path) -> Workspace:
    """Open one saved notebook for authoring."""
    path = Path(notebook).expanduser().resolve()
    if not path.is_file():
        raise ConfigurationError(f"Notebook does not exist: {path}")
    return Workspace._create(path, None)


async def doctor(provider: str | None = None) -> ProviderReport:
    """Return installed provider diagnostics."""
    return await diagnose_providers(provider)
