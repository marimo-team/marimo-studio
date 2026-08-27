"""HTTP adapters for Studio-authored views and source files."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence
from functools import partial

from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse, Response

from marimo_studio._artifacts.inputs import project_input_state
from marimo_studio._delivery.urls import studio_url, view_url, with_query
from marimo_studio._processes.ownership import (
    propagate_cancellation,
    settle_ownership,
)
from marimo_studio._processes.provider_operation import run_provider_operation
from marimo_studio._server.auth import (
    error_response,
    forbidden_response,
    has_edit_access,
    invalid_server_token_response,
)
from marimo_studio._server.development.coordinator import (
    DevelopmentCoordinator,
    ProjectCatalog,
)
from marimo_studio._server.headers import NO_STORE
from marimo_studio._server.presentation.service import NotebookPresentation
from marimo_studio._server.request_body import (
    BoundedBodyDisconnected,
    BoundedBodyTooLarge,
    InvalidContentLength,
    JSONBodyError,
    json_body_error_response,
    read_bounded_body,
    read_json_body,
)
from marimo_studio._views.api import create_view
from marimo_studio._views.catalog import starters
from marimo_studio._views.inspection import view_project_state
from marimo_studio._views.records import ViewDocument
from marimo_studio._views.remove import delete_view
from marimo_studio._views.sources import (
    SOURCE_DOCUMENT_MAX_BYTES,
    PreparedSourceWrite,
    read_project_source,
    read_view_manifest,
    source_spec,
    write_project_source,
    write_view_manifest,
)
from marimo_studio._workspace.config import validate_view_name
from marimo_studio._workspace.models import StudioDefinition, StudioWorkspace
from marimo_studio._workspace.mutation_lock import (
    workspace_catalog_lock,
)
from marimo_studio._workspace.project_manifest import (
    VIEW_MANIFEST_PATH,
)
from marimo_studio.errors import (
    MarimoStudioError,
    SourceConflictError,
    SourceTooLargeError,
)
from marimo_studio.errors._internal import ViewDeletionError
from marimo_studio.view_providers._host import provider_registry
from marimo_studio.view_providers._host.package_policy import DEFAULT_STARTER_ID

_STUDIO_MUTATION_JSON_MAX_BYTES = 64 * 1024


async def create_view_response(
    request: Request,
    definition: StudioDefinition,
    base_url: str,
    server_token: str,
    routing_query: Sequence[tuple[str, str]] = (),
) -> Response:
    """Create a named view from an authenticated Studio definition."""
    if request.method != "POST":
        return Response(status_code=405)
    if not has_edit_access(request.scope):
        return forbidden_response()
    if token_error := invalid_server_token_response(request, server_token):
        return token_error
    try:
        body = await read_json_body(
            request,
            max_bytes=_STUDIO_MUTATION_JSON_MAX_BYTES,
        )
    except JSONBodyError as error:
        return json_body_error_response(error)
    name = body.get("name") if isinstance(body, dict) else None
    starter = body.get("starter") if isinstance(body, dict) else None
    if not isinstance(name, str):
        return JSONResponse(
            {
                "error": "invalid-view-name",
                "message": "name must be a string.",
            },
            status_code=400,
            headers=NO_STORE,
        )
    if starter is not None and not isinstance(starter, str):
        return JSONResponse(
            {
                "error": "invalid-view-starter",
                "message": "starter must be a string when provided.",
            },
            status_code=400,
            headers=NO_STORE,
        )
    try:
        validate_view_name(name)
    except MarimoStudioError as error:
        return JSONResponse(
            {"error": "invalid-view-name", "message": str(error)},
            status_code=400,
            headers=NO_STORE,
        )
    try:
        result = await run_provider_operation(
            partial(
                create_view,
                definition.notebook,
                name,
                starter=starter,
            )
        )
    except MarimoStudioError as error:
        return error_response(error)
    return JSONResponse(
        {
            "schema": 2,
            "name": name,
            "provider": result.provider,
            "studio_url": with_query(studio_url(base_url, name), routing_query),
            "view_url": with_query(view_url(base_url, name), routing_query),
        },
        status_code=201,
        headers=NO_STORE,
    )


async def delete_view_response(
    request: Request,
    studio: StudioWorkspace,
    name: str,
    server_token: str,
    presentation: NotebookPresentation,
    development: DevelopmentCoordinator,
) -> Response:
    """Delete a named view from an authenticated Studio workspace."""
    if request.method != "DELETE":
        return Response(status_code=405)
    if not has_edit_access(request.scope):
        return forbidden_response()
    if token_error := invalid_server_token_response(request, server_token):
        return token_error
    try:

        def remove() -> StudioWorkspace:
            with (
                workspace_catalog_lock(studio.view_root),
                presentation.deleting_view(name),
            ):
                return delete_view(studio, name)

        async with development.deleting_view(name) as deletion:
            worker = asyncio.create_task(asyncio.to_thread(remove))
            try:
                updated = await asyncio.shield(worker)
            except ViewDeletionError as error:
                if error.cleanup is not None:
                    deletion.commit()
                raise
            except asyncio.CancelledError:
                while not worker.done():
                    try:
                        await asyncio.shield(worker)
                    except asyncio.CancelledError:
                        continue
                    except BaseException:
                        break
                try:
                    worker.result()
                except ViewDeletionError as error:
                    if error.cleanup is not None:
                        deletion.commit()
                except BaseException:
                    pass
                else:
                    deletion.commit()
                raise
    except MarimoStudioError as error:
        return error_response(error)
    inventory = await run_provider_operation(
        partial(view_inventory_payload, updated, updated)
    )
    return JSONResponse(
        {**inventory, "name": name},
        headers=NO_STORE,
    )


def view_inventory_payload(
    definition: StudioDefinition,
    workspace: StudioWorkspace | None,
) -> dict[str, object]:
    """Return configured views and installed starters."""
    return {
        "schema": 1,
        "default_view": definition.default_view,
        "default_starter": DEFAULT_STARTER_ID,
        "views": (
            [
                {
                    "name": project.name,
                    "provider": project.provider,
                }
                for project in workspace.views.values()
            ]
            if workspace is not None
            else []
        ),
        "starters": [item.to_dict() for item in starters()],
    }


async def source_response(
    request: Request,
    studio: StudioDefinition,
    view_name: str,
    name: str,
    server_token: str,
    development: DevelopmentCoordinator,
) -> Response:
    """Read or conditionally replace one authored view file."""
    manifest = name == VIEW_MANIFEST_PATH.as_posix()
    if request.method == "GET":
        if not has_edit_access(request.scope):
            return forbidden_response()
        try:
            if manifest:
                source = await asyncio.to_thread(
                    read_view_manifest,
                    studio,
                    view_name,
                )
            else:
                if not isinstance(studio, StudioWorkspace):
                    return Response(status_code=404)
                source = await _read_current_project_source(
                    studio,
                    view_name,
                    name,
                    development,
                )
        except MarimoStudioError as error:
            return error_response(error)
        return PlainTextResponse(
            source.content,
            media_type="text/plain",
            headers={**NO_STORE, "ETag": f'"{source.revision}"'},
        )
    if request.method != "PUT":
        return Response(status_code=405)
    if not has_edit_access(request.scope):
        return forbidden_response()
    if token_error := invalid_server_token_response(request, server_token):
        return token_error
    expected = request.headers.get("If-Match")
    if expected is None:
        return JSONResponse(
            {
                "error": "source-revision-required",
                "message": "If-Match must contain the loaded source revision.",
            },
            status_code=428,
            headers=NO_STORE,
        )
    expected = expected.removeprefix("W/").strip('"')
    try:
        content = await _source_body(request)
    except BoundedBodyDisconnected:
        return Response(status_code=499, headers=NO_STORE)
    except InvalidContentLength as error:
        return JSONResponse(
            {
                "error": "invalid-source-body",
                "message": str(error),
            },
            status_code=400,
            headers=NO_STORE,
        )
    except UnicodeDecodeError:
        return JSONResponse(
            {
                "error": "invalid-source-encoding",
                "message": "Studio source files must be UTF-8 text.",
            },
            status_code=400,
            headers=NO_STORE,
        )
    except MarimoStudioError as error:
        return error_response(error)
    try:
        if manifest:
            expected_provider = (
                studio.views[view_name].provider
                if isinstance(studio, StudioWorkspace) and view_name in studio.views
                else await development.retained_provider(view_name)
            )
            source = await _write_source_and_refresh(
                partial(
                    write_view_manifest,
                    studio,
                    view_name,
                    content,
                    expected,
                    expected_provider,
                ),
                development,
                view_name,
            )
        else:
            if not isinstance(studio, StudioWorkspace):
                return Response(status_code=404)
            prepared = await _prepare_source_write(
                studio,
                view_name,
                name,
                development,
            )
            source = await _write_source_and_refresh(
                partial(
                    write_project_source,
                    studio,
                    prepared,
                    content,
                    expected,
                ),
                development,
                view_name,
            )
    except MarimoStudioError as error:
        return error_response(error)
    return Response(
        status_code=204,
        headers={
            **NO_STORE,
            "ETag": f'"{source.revision}"',
            "Marimo-Studio-Source-Language": source.language,
            "Marimo-Studio-Source-Access": source.access,
        },
    )


async def _write_source_and_refresh(
    operation: Callable[[], ViewDocument],
    development: DevelopmentCoordinator,
    view_name: str,
) -> ViewDocument:
    async def commit() -> ViewDocument:
        source = await run_provider_operation(operation)
        await development.refresh(view_name)
        return source

    source, cancellation = await settle_ownership(commit())
    propagate_cancellation(cancellation)
    return source


async def _read_current_project_source(
    studio: StudioWorkspace,
    view_name: str,
    name: str,
    development: DevelopmentCoordinator,
) -> ViewDocument:
    for _attempt in range(2):
        catalog = await development.project_catalog(studio, view_name)
        spec = source_spec(catalog.inspection, name, view_name)
        source = await asyncio.to_thread(
            read_project_source,
            studio,
            catalog.project,
            spec,
        )
        current = await development.project_catalog(studio, view_name)
        current_spec = source_spec(current.inspection, name, view_name)
        if (
            current.project == catalog.project
            and current.input_id == catalog.input_id
            and current_spec == spec
        ):
            return source
    raise SourceConflictError(spec.path.as_posix(), source.revision)


async def _prepare_source_write(
    studio: StudioWorkspace,
    view_name: str,
    name: str,
    development: DevelopmentCoordinator,
) -> PreparedSourceWrite:
    for _attempt in range(2):
        catalog = await development.project_catalog(studio, view_name)
        spec = source_spec(catalog.inspection, name, view_name)
        state = await asyncio.to_thread(
            project_input_state,
            catalog.project,
            catalog.inspection,
        )
        current = await development.project_catalog(studio, view_name)
        current_spec = source_spec(current.inspection, name, view_name)
        if (
            current.project == catalog.project
            and current.input_id == catalog.input_id
            and current_spec == spec
        ):
            return PreparedSourceWrite(
                catalog.project,
                catalog.inspection,
                catalog.input_id,
                spec,
                state,
            )
    raise SourceConflictError(spec.path.as_posix(), None)


async def _source_body(request: Request) -> str:
    try:
        payload = await read_bounded_body(
            request,
            max_bytes=SOURCE_DOCUMENT_MAX_BYTES,
        )
    except BoundedBodyTooLarge as error:
        raise SourceTooLargeError(
            f"Studio source exceeds the {SOURCE_DOCUMENT_MAX_BYTES}-byte limit."
        ) from error
    return payload.decode("utf-8")


async def project_response(
    request: Request,
    studio: StudioWorkspace,
    view_name: str,
    development: DevelopmentCoordinator,
) -> Response:
    """Return the provider-discovered project and published artifact state."""
    if request.method != "GET":
        return Response(status_code=405)
    if not has_edit_access(request.scope):
        return forbidden_response()
    try:
        catalog = await development.project_catalog(studio, view_name)
        payload = await asyncio.to_thread(_project_payload, catalog, view_name)
    except MarimoStudioError as error:
        return error_response(error)
    return JSONResponse(payload, headers=NO_STORE)


def _project_payload(
    catalog: ProjectCatalog,
    view_name: str,
) -> dict[str, object]:
    project = provider_registry().validate_project(catalog.project)
    inspection = catalog.inspection
    state = view_project_state(project, inspection, input_id=catalog.input_id)
    artifact = state.artifact
    documents = [spec.to_dict() for spec in inspection.editor_documents]
    return {
        "schema": 1,
        "view": view_name,
        "provider": project.provider,
        "provider_options": dict(project.options),
        "documents": documents,
        "mounts": [item.to_dict() for item in inspection.mounts],
        "diagnostics": [item.to_dict() for item in inspection.diagnostics],
        "build": state.build.to_dict(),
        "artifact": (
            {
                "profile": artifact.profile,
                "input_id": artifact.project_revision,
                "artifact_id": artifact.artifact_revision,
            }
            if artifact is not None
            else None
        ),
    }
