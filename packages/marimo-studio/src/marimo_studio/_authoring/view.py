"""View-level authoring operations shared by public adapters."""

from __future__ import annotations

import asyncio
from functools import partial
from pathlib import Path, PurePosixPath

from marimo_studio._browser_client.client import activate_view as activate_browser_view
from marimo_studio._browser_client.records import ViewActivationResult
from marimo_studio._browser_client.transport import StudioServerConnection
from marimo_studio._delivery.export import StaticExportResult
from marimo_studio._delivery.export import export_view as export_view_bundle
from marimo_studio._processes.provider_operation import run_provider_operation
from marimo_studio._views.api import ViewRemovalResult
from marimo_studio._views.api import remove_view as remove_view_operation
from marimo_studio._views.build import build_view_project
from marimo_studio._views.inspect import inspect_view as inspect_view_project
from marimo_studio._views.records import Publication, ViewDocument, ViewInspection
from marimo_studio._views.sources import (
    read_source,
    read_view_manifest,
    write_source,
    write_view_manifest,
)
from marimo_studio._workspace import load_studio
from marimo_studio._workspace.config import load_studio_definition
from marimo_studio._workspace.project_manifest import VIEW_MANIFEST_PATH
from marimo_studio.errors import ProtocolError
from marimo_studio.view_providers import BuildProfile


async def read_document(
    notebook: Path,
    view: str,
    path: str | PurePosixPath,
) -> ViewDocument:
    """Read one authorized document and its current revision."""

    def operation() -> ViewDocument:
        name = str(path)
        if PurePosixPath(name) == VIEW_MANIFEST_PATH:
            return read_view_manifest(load_studio_definition(notebook), view)
        return read_source(load_studio(notebook), view, name)

    return await run_provider_operation(operation)


async def write_document(
    notebook: Path,
    view: str,
    path: str | PurePosixPath,
    content: str,
    *,
    expected_revision: str,
) -> ViewDocument:
    """Replace one authorized document when its revision still matches."""

    def operation() -> ViewDocument:
        name = str(path)
        if PurePosixPath(name) == VIEW_MANIFEST_PATH:
            return write_view_manifest(
                load_studio_definition(notebook),
                view,
                content,
                expected_revision,
            )
        return write_source(
            load_studio(notebook),
            view,
            name,
            content,
            expected_revision,
        )

    return await run_provider_operation(operation)


async def inspect_view(notebook: Path, view: str) -> ViewInspection:
    """Inspect source documents, diagnostics, and publication state."""
    studio = await asyncio.to_thread(load_studio, notebook)
    return await inspect_view_project(studio, view)


async def build_view(
    notebook: Path,
    view: str,
    *,
    profile: BuildProfile = "development",
) -> Publication:
    """Build and publish one view artifact."""
    if profile not in {"development", "production"}:
        raise ValueError("profile must be development or production")
    studio = await asyncio.to_thread(load_studio, notebook)
    return await build_view_project(studio.view(view), profile=profile)


async def activate_view(
    notebook: Path,
    view: str,
    connection: StudioServerConnection | None,
) -> ViewActivationResult:
    """Select one view in the browser bound to ``connection``."""
    if connection is None:
        raise ProtocolError("Browser activation requires an attached Studio browser.")
    studio = await asyncio.to_thread(load_studio, notebook)
    return await activate_browser_view(studio, connection, view)


async def export_view(
    notebook: Path,
    view: str,
    output: str | Path,
    *,
    force: bool = False,
) -> StaticExportResult:
    """Export one production view as a static WebAssembly site."""
    return await run_provider_operation(
        partial(
            export_view_bundle,
            notebook,
            output,
            view=view,
            force=force,
        )
    )


async def remove_view(notebook: Path, view: str) -> ViewRemovalResult:
    """Remove one named view and return the remaining workspace identity."""

    def operation() -> ViewRemovalResult:
        return remove_view_operation(load_studio(notebook), view)

    return await run_provider_operation(operation)
