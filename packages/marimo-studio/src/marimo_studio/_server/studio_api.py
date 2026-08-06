"""HTTP adapters for Studio-authored views and source files."""

from __future__ import annotations

import json
from collections.abc import Collection

from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse, Response

from marimo_studio._compat.server.sessions import has_edit_access, server_token_matches
from marimo_studio._urls import studio_url, view_url
from marimo_studio._workspace.config import validate_view_name
from marimo_studio._workspace.models import StudioDefinition, StudioWorkspace
from marimo_studio._workspace.sources import read_source, write_source
from marimo_studio._workspace.views import delete_view
from marimo_studio.errors import MarimoStudioError, SourceConflictError
from marimo_studio.workspace import ensure_view

_NO_STORE = {"Cache-Control": "no-store"}


def _error(error: MarimoStudioError) -> JSONResponse:
    return JSONResponse(
        {
            "error": error.code,
            "message": error.public_message(),
            **error.diagnostic_details(),
        },
        status_code=error.status_code,
        headers=_NO_STORE,
    )


def _forbidden() -> JSONResponse:
    return JSONResponse(
        {
            "error": "edit-access-required",
            "message": "Open Studio from an editable Marimo session.",
        },
        status_code=403,
        headers=_NO_STORE,
    )


def _invalid_server_token(request: Request, expected: str) -> JSONResponse | None:
    if server_token_matches(request.scope, expected):
        return None
    missing = request.headers.get("Marimo-Server-Token") is None
    return JSONResponse(
        {
            "error": "missing-server-token" if missing else "invalid-server-token",
            "message": (
                "Marimo-Server-Token is required."
                if missing
                else "Marimo-Server-Token does not match this server."
            ),
        },
        status_code=401,
        headers=_NO_STORE,
    )


async def create_view_response(
    request: Request,
    definition: StudioDefinition,
    existing_views: Collection[str],
    base_url: str,
    server_token: str,
) -> Response:
    """Create a named view from an authenticated Studio definition."""
    if request.method != "POST":
        return Response(status_code=405)
    if not has_edit_access(request.scope):
        return _forbidden()
    if token_error := _invalid_server_token(request, server_token):
        return token_error
    try:
        body = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        body = None
    name = body.get("name") if isinstance(body, dict) else None
    if not isinstance(name, str):
        return JSONResponse(
            {
                "error": "invalid-view-name",
                "message": "name must be a string.",
            },
            status_code=400,
            headers=_NO_STORE,
        )
    try:
        validate_view_name(name)
    except MarimoStudioError as error:
        return JSONResponse(
            {"error": "invalid-view-name", "message": str(error)},
            status_code=400,
            headers=_NO_STORE,
        )
    if name in existing_views:
        return JSONResponse(
            {
                "error": "view-exists",
                "message": f"A view named {name!r} already exists.",
            },
            status_code=409,
            headers=_NO_STORE,
        )
    try:
        ensure_view(definition.notebook, name)
    except MarimoStudioError as error:
        return _error(error)
    return JSONResponse(
        {
            "schema": 1,
            "name": name,
            "studio_url": studio_url(base_url, name),
            "view_url": view_url(base_url, name),
        },
        status_code=201,
        headers=_NO_STORE,
    )


async def delete_view_response(
    request: Request,
    studio: StudioWorkspace,
    name: str,
    server_token: str,
) -> Response:
    """Delete a named view from an authenticated Studio workspace."""
    if request.method != "DELETE":
        return Response(status_code=405)
    if not has_edit_access(request.scope):
        return _forbidden()
    if token_error := _invalid_server_token(request, server_token):
        return token_error
    try:
        updated = delete_view(studio, name)
    except MarimoStudioError as error:
        return _error(error)
    return JSONResponse(
        {
            "schema": 1,
            "name": name,
            "default_view": updated.default_view,
            "views": list(updated.views),
        },
        headers=_NO_STORE,
    )


async def source_response(
    request: Request,
    studio: StudioWorkspace,
    view_name: str,
    name: str,
    server_token: str,
) -> Response:
    """Read or conditionally replace one authored view file."""
    if request.method == "GET":
        try:
            source = read_source(studio, view_name, name)
        except MarimoStudioError as error:
            return _error(error)
        return PlainTextResponse(
            source.content,
            media_type="text/plain",
            headers={**_NO_STORE, "ETag": f'"{source.revision}"'},
        )
    if request.method != "PUT":
        return Response(status_code=405)
    if not has_edit_access(request.scope):
        return _forbidden()
    if token_error := _invalid_server_token(request, server_token):
        return token_error
    expected = request.headers.get("If-Match")
    if expected is None:
        return JSONResponse(
            {
                "error": "source-revision-required",
                "message": "If-Match must contain the loaded source revision.",
            },
            status_code=428,
            headers=_NO_STORE,
        )
    expected = expected.removeprefix("W/").strip('"')
    try:
        content = (await request.body()).decode("utf-8")
    except UnicodeDecodeError:
        return JSONResponse(
            {
                "error": "invalid-source-encoding",
                "message": "Studio source files must be UTF-8 text.",
            },
            status_code=400,
            headers=_NO_STORE,
        )
    try:
        source = write_source(studio, view_name, name, content, expected)
    except SourceConflictError as error:
        return _error(error)
    except MarimoStudioError as error:
        return _error(error)
    return Response(
        status_code=204,
        headers={**_NO_STORE, "ETag": f'"{source.revision}"'},
    )
