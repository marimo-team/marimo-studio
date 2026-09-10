"""View-level authoring operations shared by public adapters."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from functools import partial
from pathlib import Path, PurePosixPath

from marimo_studio._browser_client.client import show_view as show_browser_view
from marimo_studio._browser_client.records import ShowResult
from marimo_studio._browser_client.transport import StudioServerConnection
from marimo_studio._delivery.export import (
    DEFAULT_STATIC_RUNTIME,
    StaticExportResult,
    StaticRuntime,
)
from marimo_studio._delivery.export import export_view as export_view_bundle
from marimo_studio._delivery.export import preflight_view as preflight_view_bundle
from marimo_studio._delivery.preflight import StaticPreflightReport
from marimo_studio._delivery.progress import StaticExportProgress
from marimo_studio._processes.provider_operation import run_provider_operation
from marimo_studio._views.api import ViewRemovalResult
from marimo_studio._views.api import remove_view as remove_view_operation
from marimo_studio._views.build import build_view_project
from marimo_studio._views.inspect import inspect_view as inspect_view_project
from marimo_studio._views.publication_hold import (
    DEFAULT_PUBLICATION_HOLD_SECONDS,
    PublicationHold,
    acquire_publication_hold,
    release_publication_hold,
)
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
from marimo_studio._workspace.config import load_studio_definition, validate_view_name
from marimo_studio._workspace.models import StudioWorkspace
from marimo_studio._workspace.mutation_lock import workspace_catalog_lock
from marimo_studio._workspace.ownership import ObservedViewOwner
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
    from marimo_studio._views.inspect import inspect_view_manifest
    from marimo_studio._workspace.project_manifest import load_view_project
    from marimo_studio.errors import ConfigurationError, MarimoStudioError
    from marimo_studio.view_providers._host import provider_registry

    try:
        studio = await asyncio.to_thread(load_studio, notebook)
    except ConfigurationError as workspace_error:

        def repair_inspection(
            load_error: ConfigurationError = workspace_error,
        ) -> ViewInspection:
            definition = load_studio_definition(notebook)
            try:
                project = load_view_project(definition.view_root / view)
                provider_registry().validate_project(project)
            except MarimoStudioError as error:
                admit_source_owner(
                    notebook,
                    view,
                    expected_catalog_generation=expected_catalog_generation,
                    expected_generation=expected_generation,
                )
                result = inspect_view_manifest(definition, view, error)
                if (
                    expected_generation is not None
                    and result.generation != expected_generation
                ):
                    raise ViewGenerationConflictError(view, result.generation) from None
                if (
                    expected_catalog_generation is not None
                    and result.catalog_generation != expected_catalog_generation
                ):
                    raise WorkspaceGenerationConflictError() from None
                return result
            raise load_error from None

        return await asyncio.to_thread(repair_inspection)
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


async def hold_publication(
    notebook: Path,
    view: str,
    *,
    owner: str,
    ttl: float = DEFAULT_PUBLICATION_HOLD_SECONDS,
    expected_generation: str | None = None,
) -> PublicationHold:
    """Retain the current publication during a bounded source-editing interval."""

    def operation() -> PublicationHold:
        validate_view_name(view)
        root = load_studio_definition(notebook).view_root
        with workspace_catalog_lock(root):
            if load_studio_definition(notebook).view_root != root:
                raise WorkspaceGenerationConflictError()
            return acquire_publication_hold(
                root / view,
                owner=owner,
                ttl=ttl,
                expected_generation=expected_generation,
            )

    return await run_provider_operation(operation)


async def release_publication(
    notebook: Path,
    view: str,
    token: str,
    *,
    expected_generation: str | None = None,
) -> PublicationHold | None:
    """Release a matching hold so current source can publish again."""

    def operation() -> PublicationHold | None:
        validate_view_name(view)
        root = load_studio_definition(notebook).view_root
        with workspace_catalog_lock(root):
            if load_studio_definition(notebook).view_root != root:
                raise WorkspaceGenerationConflictError()
            return release_publication_hold(
                root / view,
                token,
                expected_generation=expected_generation,
            )

    return await run_provider_operation(operation)


async def show_view(
    notebook: Path,
    view: str,
    connection: StudioServerConnection | None,
    *,
    owner: ObservedViewOwner | None = None,
) -> ShowResult:
    """Show one view in the Studio tab bound to ``connection``."""
    if connection is None:
        raise ProtocolError("Showing a view requires an attached Studio browser.")
    studio = await asyncio.to_thread(load_studio, notebook)
    return await show_browser_view(
        studio,
        connection,
        view,
        owner=owner,
    )


async def export_view(
    notebook: Path,
    view: str,
    output: str | Path,
    *,
    runtime: StaticRuntime = DEFAULT_STATIC_RUNTIME,
    force: bool = False,
    prepare_timeout: float | None = None,
    expected_catalog_generation: str | None = None,
    expected_generation: str | None = None,
    progress: Callable[[StaticExportProgress], None] | None = None,
) -> StaticExportResult:
    """Export one production view through a selected static runtime."""
    return await run_provider_operation(
        partial(
            export_view_bundle,
            notebook,
            output,
            view=view,
            runtime=runtime,
            force=force,
            prepare_timeout=prepare_timeout,
            expected_catalog_generation=expected_catalog_generation,
            expected_generation=expected_generation,
            progress=progress,
        )
    )


async def preflight_view(
    notebook: Path,
    view: str,
    *,
    runtime: StaticRuntime = DEFAULT_STATIC_RUNTIME,
    prepare_timeout: float | None = None,
    expected_catalog_generation: str | None = None,
    expected_generation: str | None = None,
    progress: Callable[[StaticExportProgress], None] | None = None,
) -> StaticPreflightReport:
    """Verify one production static view without publishing a destination."""
    return await run_provider_operation(
        partial(
            preflight_view_bundle,
            notebook,
            view=view,
            runtime=runtime,
            prepare_timeout=prepare_timeout,
            expected_catalog_generation=expected_catalog_generation,
            expected_generation=expected_generation,
            progress=progress,
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
