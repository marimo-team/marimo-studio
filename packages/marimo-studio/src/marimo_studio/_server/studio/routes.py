"""HTTP adapters for Studio-authored views and source files."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from functools import partial
from pathlib import Path

from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse, Response

from marimo_studio._artifacts.inputs import project_input_state
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
from marimo_studio._server.studio.deletion import delete_owned_view
from marimo_studio._views.api import create_view
from marimo_studio._views.catalog import starters
from marimo_studio._views.inspection import view_project_state
from marimo_studio._views.records import ViewDocument
from marimo_studio._views.sources import (
    SOURCE_DOCUMENT_MAX_BYTES,
    PreparedSourceWrite,
    read_project_source,
    read_view_manifest_with_owner,
    source_spec,
    write_project_source,
    write_view_manifest,
)
from marimo_studio._workspace.config import (
    load_studio,
    materialize_studio_workspace_after_conflict,
    validate_view_name,
)
from marimo_studio._workspace.generation import unconfigured_catalog_generation
from marimo_studio._workspace.models import (
    DEFAULT_VIEW_NAME,
    StudioDefinition,
    StudioWorkspace,
)
from marimo_studio._workspace.project_manifest import (
    VIEW_MANIFEST_PATH,
)
from marimo_studio.errors import (
    MarimoStudioError,
    SourceConflictError,
    SourceTooLargeError,
    ViewGenerationConflictError,
    WorkspaceGenerationConflictError,
)
from marimo_studio.view_providers._host import provider_registry
from marimo_studio.view_providers._host.package_policy import DEFAULT_STARTER_ID

_STUDIO_MUTATION_JSON_MAX_BYTES = 64 * 1024


def _owner_generation(value: object) -> str | None:
    if (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    ):
        return value
    return None


async def create_view_response(
    request: Request,
    notebook: Path,
    current_catalog_generation: str,
    server_token: str,
) -> Response:
    """Create a named view from an authenticated workspace owner."""
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
    fields = {"catalog_generation", "name", "starter"}
    if not isinstance(body, dict) or set(body) != fields:
        return JSONResponse(
            {
                "error": "invalid-view-create-request",
                "message": (
                    "View creation requires name, starter, and catalog generation."
                ),
            },
            status_code=400,
            headers=NO_STORE,
        )
    name = body.get("name") if isinstance(body, dict) else None
    starter = body.get("starter") if isinstance(body, dict) else None
    catalog_generation = _owner_generation(body.get("catalog_generation"))
    if not isinstance(name, str):
        return JSONResponse(
            {
                "error": "invalid-view-name",
                "message": "name must be a string.",
            },
            status_code=400,
            headers=NO_STORE,
        )
    if not isinstance(starter, str):
        return JSONResponse(
            {
                "error": "invalid-view-starter",
                "message": "starter must be a string.",
            },
            status_code=400,
            headers=NO_STORE,
        )
    if catalog_generation is None:
        return JSONResponse(
            {
                "error": "invalid-view-create-request",
                "message": (
                    "View creation requires name, starter, and catalog generation."
                ),
            },
            status_code=400,
            headers=NO_STORE,
        )
    if catalog_generation != current_catalog_generation:
        return error_response(WorkspaceGenerationConflictError())
    try:
        validate_view_name(name)
    except MarimoStudioError as error:
        return JSONResponse(
            {"error": "invalid-view-name", "message": str(error)},
            status_code=400,
            headers=NO_STORE,
        )
    try:
        await run_provider_operation(
            partial(
                create_view,
                notebook,
                name,
                starter=starter,
                expected_catalog_generation=current_catalog_generation,
            )
        )
    except MarimoStudioError as error:
        return error_response(error)
    return JSONResponse(
        {
            "schema": 1,
            "name": name,
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
        body = await read_json_body(
            request,
            max_bytes=_STUDIO_MUTATION_JSON_MAX_BYTES,
        )
    except JSONBodyError as error:
        return json_body_error_response(error)
    fields = {"catalog_generation", "name", "view_generation"}
    if not isinstance(body, dict) or set(body) != fields:
        return JSONResponse(
            {
                "error": "invalid-view-delete-request",
                "message": "View deletion requires name and current owner generations.",
            },
            status_code=400,
            headers=NO_STORE,
        )
    request_name = body.get("name")
    catalog_generation = _owner_generation(body.get("catalog_generation"))
    view_generation = _owner_generation(body.get("view_generation"))
    if request_name != name or catalog_generation is None or view_generation is None:
        return JSONResponse(
            {
                "error": "invalid-view-delete-request",
                "message": "View deletion requires name and current owner generations.",
            },
            status_code=400,
            headers=NO_STORE,
        )
    try:
        starter_records = await run_provider_operation(
            lambda: tuple(item.to_dict() for item in starters())
        )
    except MarimoStudioError as error:
        return error_response(error)
    try:
        result = await delete_owned_view(
            studio,
            name,
            expected_catalog_generation=catalog_generation,
            expected_generation=view_generation,
            presentation=presentation,
            development=development,
        )
    except MarimoStudioError as error:
        return error_response(error)
    inventory = view_inventory_payload(
        result.workspace,
        result.workspace,
        starter_records=starter_records,
    )
    return JSONResponse(
        {
            **inventory,
            "name": name,
            **({"cleanup": str(result.cleanup)} if result.cleanup is not None else {}),
        },
        headers=NO_STORE,
    )


def view_inventory_payload(
    definition: StudioDefinition,
    workspace: StudioWorkspace | None,
    *,
    starter_records: tuple[dict[str, object], ...] | None = None,
) -> dict[str, object]:
    """Return configured views and installed starters."""
    return {
        "schema": 1,
        "generation": (
            workspace.catalog_generation
            if workspace is not None
            else definition.config_generation
        ),
        "default_view": definition.default_view,
        "default_starter": DEFAULT_STARTER_ID,
        "views": (
            [
                {
                    "generation": workspace.view_generations[project.name],
                    "name": project.name,
                }
                for project in workspace.views.values()
            ]
            if workspace is not None
            else []
        ),
        "starters": (
            list(starter_records)
            if starter_records is not None
            else [item.to_dict() for item in starters()]
        ),
    }


def unconfigured_view_inventory_payload(
    notebook: Path,
    *,
    starter_records: tuple[dict[str, object], ...] | None = None,
) -> dict[str, object]:
    """Return the first-view catalog for an unconfigured notebook."""
    return {
        "schema": 1,
        "generation": unconfigured_catalog_generation(notebook),
        "default_view": DEFAULT_VIEW_NAME,
        "default_starter": DEFAULT_STARTER_ID,
        "views": [],
        "starters": (
            list(starter_records)
            if starter_records is not None
            else [item.to_dict() for item in starters()]
        ),
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
            owner_headers: dict[str, str] = {}
            if manifest:
                snapshot = await asyncio.to_thread(
                    read_view_manifest_with_owner,
                    studio,
                    view_name,
                )
                source = snapshot.document
                owner_headers = {
                    "Marimo-Studio-Catalog-Generation": (snapshot.catalog_generation),
                    "Marimo-Studio-View-Generation": snapshot.view_generation,
                }
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
            headers={
                **NO_STORE,
                **owner_headers,
                "ETag": f'"{source.revision}"',
            },
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
    catalog_generation = _owner_generation(
        request.headers.get("Marimo-Studio-Catalog-Generation")
    )
    view_generation = _owner_generation(
        request.headers.get("Marimo-Studio-View-Generation")
    )
    if catalog_generation is None or view_generation is None:
        return JSONResponse(
            {
                "error": "source-generation-required",
                "message": (
                    "Source writes require current catalog and view generations."
                ),
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
                    expected_catalog_generation=catalog_generation,
                    expected_generation=view_generation,
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
                expected_catalog_generation=catalog_generation,
                expected_generation=view_generation,
            )
            source = await _write_source_and_refresh(
                partial(
                    write_project_source,
                    studio,
                    prepared,
                    content,
                    expected,
                    expected_catalog_generation=catalog_generation,
                    expected_generation=view_generation,
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
    last_conflict: tuple[str, str] | None = None
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
        last_conflict = (spec.path.as_posix(), source.revision)
    if last_conflict is None:
        raise RuntimeError("Source read made no attempts")
    raise SourceConflictError(*last_conflict)


async def _prepare_source_write(
    studio: StudioWorkspace,
    view_name: str,
    name: str,
    development: DevelopmentCoordinator,
    *,
    expected_catalog_generation: str,
    expected_generation: str,
) -> PreparedSourceWrite:
    current_studio = await asyncio.to_thread(load_studio, studio.config_path)
    current_generation = current_studio.view_generations.get(view_name)
    if current_generation != expected_generation:
        raise ViewGenerationConflictError(view_name, current_generation)
    if current_studio.catalog_generation != expected_catalog_generation:
        raise WorkspaceGenerationConflictError()
    studio = current_studio
    last_conflict_path: str | None = None
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
        last_conflict_path = spec.path.as_posix()
    if last_conflict_path is None:
        raise RuntimeError("Source write preparation made no attempts")
    raise SourceConflictError(last_conflict_path, None)


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
        try:
            current = await asyncio.to_thread(load_studio, studio.config_path)
        except WorkspaceGenerationConflictError:
            await development.require_view_available(view_name)
            current = await asyncio.to_thread(
                _load_studio_after_catalog_settles,
                studio,
            )
        catalog = await development.project_catalog(current, view_name)
        payload = await asyncio.to_thread(
            _project_payload,
            catalog,
            view_name,
            current.catalog_generation,
            current.view_generations[view_name],
        )
    except MarimoStudioError as error:
        return error_response(error)
    return JSONResponse(payload, headers=NO_STORE)


def _load_studio_after_catalog_settles(studio: StudioWorkspace) -> StudioWorkspace:
    return materialize_studio_workspace_after_conflict(studio)


def _project_payload(
    catalog: ProjectCatalog,
    view_name: str,
    catalog_generation: str,
    view_generation: str,
) -> dict[str, object]:
    project = provider_registry().validate_project(catalog.project)
    inspection = catalog.inspection
    state = view_project_state(project, inspection, input_id=catalog.input_id)
    artifact = state.artifact
    documents = [spec.to_dict() for spec in inspection.editor_documents]
    return {
        "schema": 1,
        "catalog_generation": catalog_generation,
        "view_generation": view_generation,
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
