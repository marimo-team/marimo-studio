"""View-level authoring operations shared by public adapters."""

from __future__ import annotations

import asyncio
from functools import partial
from pathlib import Path, PurePosixPath

from marimo_studio._browser_client.client import show_view as show_browser_view
from marimo_studio._browser_client.records import ShowResult
from marimo_studio._browser_client.transport import StudioServerConnection
from marimo_studio._delivery.export import StaticExportResult
from marimo_studio._delivery.export import export_view as export_view_bundle
from marimo_studio._processes.provider_operation import run_provider_operation
from marimo_studio._views.api import ViewRemovalResult
from marimo_studio._views.api import remove_view as remove_view_operation
from marimo_studio._views.build import build_view_project
from marimo_studio._views.inspect import inspect_view as inspect_view_project
from marimo_studio._views.records import ViewBuild, ViewDocument, ViewInspection
from marimo_studio._views.sources import (
    OwnedViewDocument,
    admit_source_owner,
    read_source,
    read_source_with_owner,
    read_view_manifest,
    read_view_manifest_with_owner,
    write_source,
    write_view_manifest,
)
from marimo_studio._workspace import load_studio
from marimo_studio._workspace.config import load_studio_definition
from marimo_studio._workspace.models import StudioWorkspace
from marimo_studio._workspace.project_manifest import VIEW_MANIFEST_PATH
from marimo_studio.errors import (
    ProtocolError,
    ViewGenerationConflictError,
    WorkspaceGenerationConflictError,
)
from marimo_studio.view_providers import BuildProfile


async def read_document(
    notebook: Path,
    view: str,
    path: str | PurePosixPath,
    *,
    expected_catalog_generation: str | None = None,
    expected_generation: str | None = None,
) -> ViewDocument:
    """Read one authorized document and its current revision."""

    def operation() -> ViewDocument:
        name = str(path)
        if PurePosixPath(name) == VIEW_MANIFEST_PATH:
            if (
                expected_catalog_generation is not None
                or expected_generation is not None
            ):
                admit_source_owner(
                    notebook,
                    view,
                    expected_catalog_generation=expected_catalog_generation,
                    expected_generation=expected_generation,
                )
            return read_view_manifest(load_studio_definition(notebook), view)
        studio = load_studio(notebook)
        _require_view_owner(
            studio,
            view,
            expected_catalog_generation=expected_catalog_generation,
            expected_generation=expected_generation,
        )
        return read_source(studio, view, name)

    return await run_provider_operation(operation)


async def read_document_with_owner(
    notebook: Path,
    view: str,
    path: str | PurePosixPath,
) -> OwnedViewDocument:
    """Read one authorized document with its current mutation owners."""

    def operation() -> OwnedViewDocument:
        name = str(path)
        if PurePosixPath(name) == VIEW_MANIFEST_PATH:
            return read_view_manifest_with_owner(
                load_studio_definition(notebook),
                view,
            )
        return read_source_with_owner(load_studio(notebook), view, name)

    return await run_provider_operation(operation)


async def write_document(
    notebook: Path,
    view: str,
    path: str | PurePosixPath,
    content: str,
    *,
    expected_revision: str,
    expected_catalog_generation: str | None = None,
    expected_generation: str | None = None,
) -> ViewDocument:
    """Replace one authorized document when its revision still matches."""

    def operation() -> ViewDocument:
        name = str(path)
        if expected_catalog_generation is not None or expected_generation is not None:
            admit_source_owner(
                notebook,
                view,
                expected_catalog_generation=expected_catalog_generation,
                expected_generation=expected_generation,
            )
        if PurePosixPath(name) == VIEW_MANIFEST_PATH:
            return write_view_manifest(
                load_studio_definition(notebook),
                view,
                content,
                expected_revision,
                expected_catalog_generation=expected_catalog_generation,
                expected_generation=expected_generation,
            )
        return write_source(
            load_studio(notebook),
            view,
            name,
            content,
            expected_revision,
            expected_catalog_generation=expected_catalog_generation,
            expected_generation=expected_generation,
        )

    return await run_provider_operation(operation)


async def inspect_view(
    notebook: Path,
    view: str,
    *,
    expected_catalog_generation: str | None = None,
    expected_generation: str | None = None,
) -> ViewInspection:
    """Inspect source documents, diagnostics, and build state."""
    studio = await asyncio.to_thread(load_studio, notebook)
    _require_view_owner(
        studio,
        view,
        expected_catalog_generation=expected_catalog_generation,
        expected_generation=expected_generation,
    )
    return await inspect_view_project(studio, view)


def _require_view_owner(
    studio: StudioWorkspace,
    view: str,
    *,
    expected_catalog_generation: str | None,
    expected_generation: str | None,
) -> None:
    current_generation = studio.view_generations.get(view)
    if expected_generation is not None and current_generation != expected_generation:
        raise ViewGenerationConflictError(view, current_generation)
    if (
        expected_catalog_generation is not None
        and studio.catalog_generation != expected_catalog_generation
    ):
        raise WorkspaceGenerationConflictError()


async def build_view(
    notebook: Path,
    view: str,
    *,
    profile: BuildProfile = "development",
    expected_catalog_generation: str | None = None,
    expected_generation: str | None = None,
) -> ViewBuild:
    """Build the browser page for one view."""
    if profile not in {"development", "production"}:
        raise ValueError("profile must be development or production")
    studio = await asyncio.to_thread(load_studio, notebook)
    current_generation = studio.view_generations.get(view)
    if expected_generation is not None and current_generation != expected_generation:
        raise ViewGenerationConflictError(view, current_generation)
    if (
        expected_catalog_generation is not None
        and studio.catalog_generation != expected_catalog_generation
    ):
        raise WorkspaceGenerationConflictError()
    return await build_view_project(
        studio.view(view),
        profile=profile,
        expected_generation=expected_generation,
    )


async def show_view(
    notebook: Path,
    view: str,
    connection: StudioServerConnection | None,
) -> ShowResult:
    """Show one view in the Studio tab bound to ``connection``."""
    if connection is None:
        raise ProtocolError("Showing a view requires an attached Studio browser.")
    studio = await asyncio.to_thread(load_studio, notebook)
    return await show_browser_view(studio, connection, view)


async def export_view(
    notebook: Path,
    view: str,
    output: str | Path,
    *,
    force: bool = False,
    expected_catalog_generation: str | None = None,
    expected_generation: str | None = None,
) -> StaticExportResult:
    """Export one production view as a static WebAssembly site."""
    return await run_provider_operation(
        partial(
            export_view_bundle,
            notebook,
            output,
            view=view,
            force=force,
            expected_catalog_generation=expected_catalog_generation,
            expected_generation=expected_generation,
        )
    )


async def remove_view(
    notebook: Path,
    view: str,
    *,
    expected_catalog_generation: str | None = None,
    expected_generation: str | None = None,
) -> ViewRemovalResult:
    """Remove one named view and return the remaining workspace identity."""

    def operation() -> ViewRemovalResult:
        return remove_view_operation(
            load_studio(notebook),
            view,
            expected_catalog_generation=expected_catalog_generation,
            expected_generation=expected_generation,
        )

    return await run_provider_operation(operation)
