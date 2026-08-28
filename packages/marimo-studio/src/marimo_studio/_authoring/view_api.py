"""Named-view interface over shared authoring operations."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Literal, TypeVar

from marimo_studio._authoring.ports import WorkspaceHandle
from marimo_studio._authoring.validation import validate as validate_workspace
from marimo_studio._authoring.view import (
    build_view,
    export_view,
    inspect_view,
    read_document,
    remove_view,
    write_document,
)
from marimo_studio._delivery.export import StaticExportResult
from marimo_studio._processes.limits import DEFAULT_RUNTIME_TIMEOUT
from marimo_studio._validation.records import ValidationReport
from marimo_studio._views.api import ViewRemovalResult
from marimo_studio._views.records import ViewBuild, ViewDocument, ViewInspection
from marimo_studio.view_providers import BuildProfile

_View = TypeVar("_View", bound="View")


@dataclass(frozen=True, init=False)
class View:
    """One named view in a notebook-bound workspace."""

    workspace: WorkspaceHandle
    name: str

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        raise TypeError("Create views through a Studio authoring workspace")

    @classmethod
    def _create(cls: type[_View], workspace: WorkspaceHandle, name: str) -> _View:
        view = object.__new__(cls)
        object.__setattr__(view, "workspace", workspace)
        object.__setattr__(view, "name", name)
        return view

    async def inspect(self) -> ViewInspection:
        """Inspect source documents, diagnostics, and build state."""
        return await inspect_view(self.workspace.notebook, self.name)

    async def read(self, path: str | PurePosixPath) -> ViewDocument:
        """Read one document with its current content revision."""
        return await read_document(self.workspace.notebook, self.name, path)

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
        )

    async def export(
        self,
        output: str | Path,
        *,
        force: bool = False,
    ) -> StaticExportResult:
        """Export this view as a static WebAssembly site."""
        return await export_view(
            self.workspace.notebook,
            self.name,
            output,
            force=force,
        )

    async def remove(self) -> ViewRemovalResult:
        """Remove this view and return the remaining workspace identity."""
        return await remove_view(self.workspace.notebook, self.name)
