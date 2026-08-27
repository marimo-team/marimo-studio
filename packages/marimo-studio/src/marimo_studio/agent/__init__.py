"""Author and validate Studio views from notebook-bound agent code.

This facade opens the active or explicit notebook and exposes its saved cells,
installed starters, named views, Source documents, builds, browser activation,
and validation through ``Workspace`` and ``View`` handles. Source writes carry
the revision the agent read so a late edit reports a conflict and preserves
newer work.

Open the current notebook in each code-mode execution:

    import marimo_studio.agent as studio

    workspace = studio.open()
    view = await workspace.ensure_view("dashboard")
    inspection = await view.inspect()

Static validation checks saved source. Runtime validation executes the complete
notebook in isolation. Browser validation requires a running Studio browser and
confirms the rendered page and mounted notebook results. The installed
``marimo-studio`` Agent Skill uses this API to move from notebook inspection to
a built, browser-visible, and validated view.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from functools import partial
from pathlib import Path, PurePosixPath

from marimo_studio._notebook.records import CellSelector, InspectionResult
from marimo_studio._processes.limits import DEFAULT_RUNTIME_TIMEOUT
from marimo_studio._processes.provider_operation import run_provider_operation
from marimo_studio._validation.evidence import AnalysisAction
from marimo_studio._validation.limits import DEFAULT_BROWSER_TIMEOUT
from marimo_studio._validation.records import ValidationLevel, ValidationReport
from marimo_studio._views.records import (
    Publication,
    Starter,
    StudioDiagnostic,
    StudioOverview,
    ViewDocument,
    ViewFreshness,
    ViewInspection,
    ViewOverview,
)
from marimo_studio._workspace.models import BindingResult
from marimo_studio.agent._records import ViewActivationResult
from marimo_studio.errors import ConfigurationError
from marimo_studio.view_providers import (
    BuildProfile,
)


@dataclass(frozen=True, init=False)
class Workspace:
    """Notebook-bound Studio authoring workspace."""

    notebook: Path

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        raise TypeError("Use marimo_studio.agent.open() to create a workspace")

    @classmethod
    def _create(cls, notebook: Path) -> Workspace:
        workspace = object.__new__(cls)
        object.__setattr__(workspace, "notebook", notebook)
        return workspace

    async def inspect(
        self,
        *,
        include_code: bool = False,
        selectors: tuple[CellSelector, ...] = (),
        output_expressions: bool = False,
        limit: int | None = None,
    ) -> InspectionResult:
        """Read saved notebook cells and their static relationships."""
        from marimo_studio._notebook.inspection import inspect_notebook_result

        return await asyncio.to_thread(
            inspect_notebook_result,
            self.notebook,
            include_code=include_code,
            selectors=selectors,
            output_expressions=output_expressions,
            limit=limit,
        )

    async def overview(self) -> StudioOverview:
        """Describe configured views for this notebook."""
        from marimo_studio._views.overview import overview

        return await run_provider_operation(partial(overview, self.notebook))

    async def starters(self) -> tuple[Starter, ...]:
        """Return installed view starters and their availability."""
        from marimo_studio._views.catalog import starters

        return await run_provider_operation(starters)

    async def starter(self, identity: str) -> Starter:
        """Return one installed view starter."""
        from marimo_studio._views.catalog import get_starter

        return await run_provider_operation(partial(get_starter, identity))

    async def ensure_view(
        self,
        name: str | None = None,
        *,
        starter: str | Starter | None = None,
    ) -> View:
        """Create a named view when needed and return its handle."""
        from marimo_studio._views.api import ensure_view

        result = await run_provider_operation(
            partial(
                ensure_view,
                self.notebook,
                name,
                starter=starter,
            )
        )
        return View._create(self, result.name)

    def view(self, name: str) -> View:
        """Return a handle for one named view."""
        if not isinstance(name, str) or not name:
            raise ValueError("view name must be a non-empty string")
        return View._create(self, name)

    async def bind(
        self,
        alias: str,
        cell_index: int,
        *,
        overwrite: bool = False,
    ) -> BindingResult:
        """Give one notebook cell a stable symbolic target."""
        from marimo_studio._views.api import bind_cell
        from marimo_studio._workspace import load_studio

        def operation() -> BindingResult:
            return bind_cell(
                load_studio(self.notebook),
                alias,
                cell_index,
                overwrite=overwrite,
            )

        return await run_provider_operation(operation)

    async def validate(
        self,
        *,
        level: ValidationLevel = "static",
        view: str | None = None,
        browser_timeout: float = DEFAULT_BROWSER_TIMEOUT,
        runtime_timeout: float = DEFAULT_RUNTIME_TIMEOUT,
    ) -> ValidationReport:
        """Validate saved source, runtime execution, or browser evidence."""
        if level not in {"static", "runtime", "browser"}:
            raise ValueError("level must be static, runtime, or browser")
        from marimo_studio._composition import create_code_mode_bridge
        from marimo_studio._validation.analysis import AnalysisRequest
        from marimo_studio._validation.runtime_process import (
            check_runtime_studio_isolated,
        )
        from marimo_studio._validation.service import validate_studio
        from marimo_studio._workspace import load_studio
        from marimo_studio.agent._client import request_analysis

        selected = await asyncio.to_thread(load_studio, self.notebook)
        if level != "browser":
            return (
                await validate_studio(
                    selected,
                    level="runtime" if level == "runtime" else "static",
                    view_name=view,
                    runtime_timeout=runtime_timeout,
                    runtime_checker=check_runtime_studio_isolated,
                )
            ).report

        request = AnalysisRequest(
            view=view,
            browser_timeout=browser_timeout,
            runtime_timeout=runtime_timeout,
            require_browser=True,
        )
        request.require_focused_view()
        connection = create_code_mode_bridge().connection()
        return ValidationReport.from_analysis(
            await request_analysis(connection, self.notebook, request)
        )


@dataclass(frozen=True, init=False)
class View:
    """One named view in a notebook-bound workspace."""

    workspace: Workspace
    name: str

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        raise TypeError(
            "Create views through a workspace returned by marimo_studio.agent.open()"
        )

    @classmethod
    def _create(
        cls,
        workspace: Workspace,
        name: str,
    ) -> View:
        view = object.__new__(cls)
        object.__setattr__(view, "workspace", workspace)
        object.__setattr__(view, "name", name)
        return view

    async def read(self, path: str | PurePosixPath) -> ViewDocument:
        """Read one document with its current content revision."""
        from marimo_studio._views.sources import (
            read_source,
            read_view_manifest,
        )
        from marimo_studio._workspace import load_studio
        from marimo_studio._workspace.config import load_studio_definition
        from marimo_studio._workspace.project_manifest import VIEW_MANIFEST_PATH

        def operation() -> ViewDocument:
            name = str(path)
            source = (
                read_view_manifest(
                    load_studio_definition(self.workspace.notebook),
                    self.name,
                )
                if PurePosixPath(name) == VIEW_MANIFEST_PATH
                else read_source(
                    load_studio(self.workspace.notebook),
                    self.name,
                    name,
                )
            )
            return source

        return await run_provider_operation(operation)

    async def write(
        self,
        path: str | PurePosixPath,
        content: str,
        *,
        expected_revision: str,
        expected_provider: str | None = None,
    ) -> ViewDocument:
        """Conditionally replace one editable document."""
        from marimo_studio._views.sources import (
            write_source,
            write_view_manifest,
        )
        from marimo_studio._workspace import load_studio
        from marimo_studio._workspace.config import load_studio_definition
        from marimo_studio._workspace.project_manifest import VIEW_MANIFEST_PATH

        name = str(path)
        manifest = PurePosixPath(name) == VIEW_MANIFEST_PATH
        if expected_provider is not None and not manifest:
            raise ValueError("expected_provider applies only to view.toml")

        def operation() -> ViewDocument:
            source = (
                write_view_manifest(
                    load_studio_definition(self.workspace.notebook),
                    self.name,
                    content,
                    expected_revision,
                    expected_provider=expected_provider,
                )
                if manifest
                else write_source(
                    load_studio(self.workspace.notebook),
                    self.name,
                    name,
                    content,
                    expected_revision,
                )
            )
            return source

        return await run_provider_operation(operation)

    async def inspect(self) -> ViewInspection:
        """Inspect source documents, diagnostics, and publication state."""
        from marimo_studio._views.inspect import inspect_view
        from marimo_studio._workspace import load_studio

        selected = await asyncio.to_thread(load_studio, self.workspace.notebook)
        return await inspect_view(selected, self.name)

    async def build(
        self,
        *,
        profile: BuildProfile = "development",
    ) -> Publication:
        """Build and return detached publication metadata."""
        from marimo_studio._views.build import build_view_project
        from marimo_studio._workspace import load_studio

        if profile not in {"development", "production"}:
            raise ValueError("profile must be development or production")
        selected = await asyncio.to_thread(load_studio, self.workspace.notebook)
        project = selected.view(self.name)
        return await build_view_project(project, profile=profile)

    async def activate(self) -> ViewActivationResult:
        """Select this view in the attached Studio browser."""
        from marimo_studio._composition import create_code_mode_bridge
        from marimo_studio._workspace import load_studio
        from marimo_studio.agent._client import activate_view

        selected = await asyncio.to_thread(load_studio, self.workspace.notebook)
        return await activate_view(
            selected,
            create_code_mode_bridge().connection(),
            self.name,
        )

    async def validate(
        self,
        *,
        level: ValidationLevel = "static",
        browser_timeout: float = DEFAULT_BROWSER_TIMEOUT,
        runtime_timeout: float = DEFAULT_RUNTIME_TIMEOUT,
    ) -> ValidationReport:
        """Validate this view at the selected evidence level."""
        return await self.workspace.validate(
            level=level,
            view=self.name,
            browser_timeout=browser_timeout,
            runtime_timeout=runtime_timeout,
        )


def open(notebook: str | Path | None = None) -> Workspace:
    """Open a saved notebook or bind to the active code-mode notebook."""
    if notebook is None:
        from marimo_studio._composition import create_code_mode_bridge

        path = create_code_mode_bridge().active_notebook()
    else:
        path = Path(notebook).expanduser().resolve()
    if not path.is_file():
        raise ConfigurationError(f"Notebook does not exist: {path}")
    return Workspace._create(path)


__all__ = [
    "AnalysisAction",
    "BindingResult",
    "CellSelector",
    "InspectionResult",
    "Publication",
    "Starter",
    "StudioDiagnostic",
    "StudioOverview",
    "ValidationLevel",
    "ValidationReport",
    "View",
    "ViewActivationResult",
    "ViewDocument",
    "ViewFreshness",
    "ViewInspection",
    "ViewOverview",
    "Workspace",
    "open",
]
