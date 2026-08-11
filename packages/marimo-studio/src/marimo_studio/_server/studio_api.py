"""HTTP adapters for Studio-authored views and source files."""

from __future__ import annotations

import json
from collections.abc import Collection, Sequence

from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse, Response

from marimo_studio._compat.server.sessions import has_edit_access
from marimo_studio._server.auth import (
    error_response,
    forbidden_response,
    invalid_server_token_response,
)
from marimo_studio._server.headers import NO_STORE
from marimo_studio._urls import studio_url, view_url, with_query
from marimo_studio._workspace.config import validate_view_name
from marimo_studio._workspace.models import StudioDefinition, StudioWorkspace
from marimo_studio._workspace.sources import read_source, write_source
from marimo_studio._workspace.views import delete_view
from marimo_studio.errors import MarimoStudioError
from marimo_studio.workspace import ensure_view


async def create_view_response(
    request: Request,
    definition: StudioDefinition,
    existing_views: Collection[str],
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
    if name in existing_views:
        return JSONResponse(
            {
                "error": "view-exists",
                "message": f"A view named {name!r} already exists.",
            },
            status_code=409,
            headers=NO_STORE,
        )
    try:
        ensure_view(definition.notebook, name)
    except MarimoStudioError as error:
        return error_response(error)
    return JSONResponse(
        {
            "schema": 1,
            "name": name,
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
) -> Response:
    """Delete a named view from an authenticated Studio workspace."""
    if request.method != "DELETE":
        return Response(status_code=405)
    if not has_edit_access(request.scope):
        return forbidden_response()
    if token_error := invalid_server_token_response(request, server_token):
        return token_error
    try:
        updated = delete_view(studio, name)
    except MarimoStudioError as error:
        return error_response(error)
    return JSONResponse(
        {
            "schema": 1,
            "name": name,
            "default_view": updated.default_view,
            "views": list(updated.views),
        },
        headers=NO_STORE,
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
        content = (await request.body()).decode("utf-8")
    except UnicodeDecodeError:
        return JSONResponse(
            {
                "error": "invalid-source-encoding",
                "message": "Studio source files must be UTF-8 text.",
            },
            status_code=400,
            headers=NO_STORE,
        )
    try:
        source = write_source(studio, view_name, name, content, expected)
    except MarimoStudioError as error:
        return error_response(error)
    return Response(
        status_code=204,
        headers={**NO_STORE, "ETag": f'"{source.revision}"'},
    )


__all__ = ["create_view_response", "delete_view_response", "source_response"]
