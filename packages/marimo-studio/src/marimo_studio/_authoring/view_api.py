"""Named-view interface over shared authoring operations."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Literal, TypeVar

from marimo_studio._authoring.ports import WorkspaceHandle
from marimo_studio._authoring.validation import validate as validate_workspace
from marimo_studio._authoring.view import (
    build_view,
    export_view,
    inspect_view,
    preflight_view,
    read_document,
    remove_view,
    write_document,
)
from marimo_studio._delivery.export import (
    DEFAULT_STATIC_RUNTIME,
    StaticExportResult,
    StaticRuntime,
)
from marimo_studio._delivery.preflight import StaticPreflightReport
from marimo_studio._delivery.progress import StaticExportProgress
from marimo_studio._processes.limits import DEFAULT_RUNTIME_TIMEOUT
from marimo_studio._validation.records import ValidationReport
from marimo_studio._views.api import ViewRemovalResult
from marimo_studio._views.records import ViewBuild, ViewDocument, ViewInspection
from marimo_studio._workspace.ownership import ObservedViewOwner, PresentViewOwner
from marimo_studio.errors import WorkspaceGenerationConflictError
from marimo_studio.view_providers import BuildProfile

_View = TypeVar("_View", bound="View")


@dataclass(frozen=True, init=False)
class View:
    """One named view in a notebook-bound workspace."""

    workspace: WorkspaceHandle
    name: str
    _owner: ObservedViewOwner | None

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        raise TypeError("Create views through a Studio authoring workspace")

    @classmethod
    def _create(
        cls: type[_View],
        workspace: WorkspaceHandle,
        name: str,
        *,
        owner: ObservedViewOwner | None,
    ) -> _View:
        view = object.__new__(cls)
        object.__setattr__(view, "workspace", workspace)
        object.__setattr__(view, "name", name)
        object.__setattr__(view, "_owner", owner)
        return view

    @property
    def catalog_generation(self) -> str | None:
        """Return the catalog generation captured by this handle."""
        return self._owner.catalog_generation if self._owner is not None else None

    @property
    def generation(self) -> str | None:
        """Return the captured generation when the view was present."""
        return self._owner.view_generation if self._owner is not None else None

    async def inspect(self) -> ViewInspection:
        """Inspect source documents, diagnostics, and build state."""
        return await inspect_view(
            self.workspace.notebook,
            self.name,
            expected_catalog_generation=self.catalog_generation,
            expected_generation=self.generation,
        )

    async def read(self, path: str | PurePosixPath) -> ViewDocument:
        """Read one document with its current content revision."""
        return await read_document(
            self.workspace.notebook,
            self.name,
            path,
            expected_catalog_generation=self.catalog_generation,
            expected_generation=self.generation,
        )

    async def write(
        self,
        path: str | PurePosixPath,
        content: str,
        *,
        expected_revision: str,
    ) -> ViewDocument:
        """Conditionally replace one editable document."""
        return await write_document(
            self.workspace.notebook,
            self.name,
            path,
            content,
            expected_revision=expected_revision,
            expected_catalog_generation=self.catalog_generation,
            expected_generation=self.generation,
        )

    async def build(
        self,
        *,
        profile: BuildProfile = "development",
    ) -> ViewBuild:
        """Build this view and return the resulting page revision."""
        return await build_view(
            self.workspace.notebook,
            self.name,
            profile=profile,
            expected_catalog_generation=self.catalog_generation,
            expected_generation=self.generation,
        )

    async def validate(
        self,
        *,
        level: Literal["static", "runtime"] = "static",
        runtime_timeout: float = DEFAULT_RUNTIME_TIMEOUT,
    ) -> ValidationReport:
        """Validate saved source or isolated notebook execution."""
        return await validate_workspace(
            self.workspace.notebook,
            level=level,
            view=self.name,
            runtime_timeout=runtime_timeout,
            expected_catalog_generation=self.catalog_generation,
            expected_generation=self.generation,
        )

    async def export(
        self,
        output: str | Path,
        *,
        runtime: StaticRuntime = DEFAULT_STATIC_RUNTIME,
        force: bool = False,
        prepare_timeout: float | None = None,
        progress: Callable[[StaticExportProgress], None] | None = None,
    ) -> StaticExportResult:
        """Export this view through a selected static runtime."""
        return await export_view(
            self.workspace.notebook,
            self.name,
            output,
            runtime=runtime,
            force=force,
            prepare_timeout=prepare_timeout,
            expected_catalog_generation=self.catalog_generation,
            expected_generation=self.generation,
            progress=progress,
        )

    async def preflight(
        self,
        *,
        runtime: StaticRuntime = DEFAULT_STATIC_RUNTIME,
        prepare_timeout: float | None = None,
        progress: Callable[[StaticExportProgress], None] | None = None,
    ) -> StaticPreflightReport:
        """Verify this static view without publishing a destination."""
        return await preflight_view(
            self.workspace.notebook,
            self.name,
            runtime=runtime,
            prepare_timeout=prepare_timeout,
            expected_catalog_generation=self.catalog_generation,
            expected_generation=self.generation,
            progress=progress,
        )

    async def remove(self) -> ViewRemovalResult:
        """Remove this view and return the remaining workspace identity."""
        if not isinstance(self._owner, PresentViewOwner):
            raise WorkspaceGenerationConflictError()
        result = await remove_view(
            self.workspace.notebook,
            self.name,
            expected_catalog_generation=self._owner.catalog_generation,
            expected_generation=self._owner.view_generation,
        )
        self.workspace._capture_catalog_generation(result.catalog_generation)
        return result
