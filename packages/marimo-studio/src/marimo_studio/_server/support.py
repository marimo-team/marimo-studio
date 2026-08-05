"""Serve authenticated Studio support routes."""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast
from urllib.parse import parse_qs

from starlette.requests import Request
from starlette.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    Response,
    StreamingResponse,
)

from marimo_studio import _assets
from marimo_studio._compat.kernel_values import (
    ValueReadUnavailable,
    read_session_values,
)
from marimo_studio._compat.kernel_values.query import (
    QuerySyncUnavailable,
    queue_query_sync,
)
from marimo_studio._compat.server.context import server_shutdown_requested
from marimo_studio._compat.server.models import ServerContext
from marimo_studio._compat.server.sessions import (
    current_session,
    has_read_access,
    server_token_matches,
)
from marimo_studio._html import cell_host, render
from marimo_studio._server.dev import change_events
from marimo_studio._server.headers import NO_STORE
from marimo_studio._server.presentation import NotebookPresentation
from marimo_studio._server.studio_api import (
    create_view_response,
    delete_view_response,
    source_response,
)
from marimo_studio._workspace.models import ResolvedView, StudioConfig


async def support_response(
    request: Request,
    context: ServerContext,
    studio: StudioConfig,
    presentation: NotebookPresentation,
    support_path: str,
) -> Response:
    """Dispatch one namespaced Studio support request."""
    if support_path.startswith("/assets/"):
        return file_response(
            _assets.runtime_assets_path(),
            support_path.removeprefix("/assets/"),
        )
    if not has_read_access(request.scope):
        return JSONResponse(
            {
                "error": "authentication-required",
                "message": "Authenticate with Marimo before using this route.",
            },
            status_code=401,
            headers=NO_STORE,
        )
    if support_path == "/views":
        if request.method == "GET":
            return JSONResponse(
                {
                    "schema": 1,
                    "default_view": studio.default_view,
                    "views": list(studio.views),
                },
                headers=NO_STORE,
            )
        return await create_view_response(
            request,
            studio,
            context.base_url,
            context.server_token,
        )
    if support_path == "/dev/events" and request.method == "GET" and context.dev:
        return events_response(studio, context=context)
    if support_path == "/query" and request.method == "POST":
        return await _query_response(request, context)
    if support_path.startswith("/views/"):
        return await _view_response(
            request,
            context,
            studio,
            presentation,
            support_path.removeprefix("/views/"),
        )
    return Response(status_code=404)


async def _view_response(
    request: Request,
    context: ServerContext,
    studio: StudioConfig,
    presentation: NotebookPresentation,
    relative: str,
) -> Response:
    view_name, separator, route = relative.partition("/")
    if not separator:
        return await delete_view_response(
            request,
            studio,
            view_name,
            context.server_token,
        )
    if view_name not in studio.views:
        return Response(status_code=404)
    if route.startswith("static/") and request.method in {"GET", "HEAD"}:
        relative = route.removeprefix("static/")
        if (
            relative == "theme.css"
            and not (studio.views[view_name].root / relative).exists()
        ):
            return Response(
                media_type="text/css",
                headers={"Cache-Control": "no-cache"},
            )
        return file_response(
            studio.views[view_name].root,
            relative,
        )
    if route == "dev/events" and request.method == "GET" and context.dev:
        return events_response(studio, context=context, view_name=view_name)
    if route.startswith("source/"):
        return await source_response(
            request,
            studio,
            view_name,
            route.removeprefix("source/"),
            context.server_token,
        )
    snapshot = presentation.snapshot(view_name)
    resolved = snapshot.resolved
    view = resolved.views[view_name]
    if route == "config" and request.method == "GET":
        return JSONResponse(
            presentation.runtime_config(
                snapshot,
                context,
                request.query_params.get("runtime"),
                request.headers.get("Marimo-Session-Id"),
            ),
            headers=NO_STORE,
        )
    if route == "values" and request.method == "POST":
        return await _values_response(request, context, view)
    if route.startswith("cells/") and request.method == "GET":
        alias = route.removeprefix("cells/")
        if "/" in alias or (
            alias not in resolved.aliases and alias not in view.cell_aliases
        ):
            return JSONResponse(
                {"error": "unknown-cell", "message": f"Unknown cell {alias!r}."},
                status_code=404,
                headers=NO_STORE,
            )
        return HTMLResponse(render(cell_host(alias)), headers=NO_STORE)
    return Response(status_code=404)


def events_response(
    studio: StudioConfig,
    context: ServerContext,
    view_name: str | None = None,
) -> Response:
    """Stream source and notebook changes until the server shuts down."""
    return StreamingResponse(
        change_events(
            studio,
            view_name,
            stop_requested=lambda: server_shutdown_requested(context),
        ),
        media_type="text/event-stream",
        headers={**NO_STORE, "X-Accel-Buffering": "no"},
    )


async def _values_response(
    request: Request,
    context: ServerContext,
    view: ResolvedView,
) -> Response:
    try:
        body = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        body = None
    selectors = body.get("selectors") if isinstance(body, dict) else None
    if (
        not isinstance(selectors, list)
        or len(selectors) > 100
        or not all(isinstance(selector, str) for selector in selectors)
    ):
        return JSONResponse(
            {
                "error": "invalid-value-request",
                "message": "selectors must be an array of at most 100 strings.",
            },
            status_code=400,
            headers=NO_STORE,
        )
    requested = tuple(dict.fromkeys(cast(list[str], selectors)))
    unknown = sorted(set(requested).difference(view.value_bindings))
    if unknown:
        return JSONResponse(
            {
                "error": "unknown-selector",
                "message": f"Unknown selectors: {', '.join(unknown)}.",
            },
            status_code=400,
            headers=NO_STORE,
        )
    session_id = request.headers.get("Marimo-Session-Id")
    if not session_id:
        return JSONResponse(
            {
                "error": "missing-session",
                "message": "Marimo-Session-Id is required.",
                "transient": True,
            },
            status_code=409,
            headers=NO_STORE,
        )
    session = current_session(context, session_id)
    if session is None:
        return JSONResponse(
            {
                "error": "unknown-session",
                "message": "The Marimo session is still connecting.",
                "transient": True,
            },
            status_code=409,
            headers=NO_STORE,
        )
    try:
        result = await read_session_values(
            session,
            requested,
            consumer_id=session_id,
        )
    except ValueReadUnavailable as error:
        return JSONResponse(
            {
                "error": error.code,
                "message": str(error),
                "transient": error.transient,
            },
            status_code=error.status_code,
            headers=NO_STORE,
        )
    return JSONResponse(result.to_dict(), headers=NO_STORE)


async def _query_response(
    request: Request,
    context: ServerContext,
) -> Response:
    if context.mode != "edit" or not server_token_matches(
        request.scope,
        context.server_token,
    ):
        return JSONResponse(
            {
                "error": "edit-required",
                "message": "Query synchronization requires the active Studio editor.",
            },
            status_code=403,
            headers=NO_STORE,
        )
    try:
        body = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        body = None
    query = body.get("query") if isinstance(body, dict) else None
    if not isinstance(query, str) or len(query) > 16_384:
        return JSONResponse(
            {
                "error": "invalid-query",
                "message": "query must be a string of at most 16384 characters.",
            },
            status_code=400,
            headers=NO_STORE,
        )
    try:
        parsed = parse_qs(
            query.removeprefix("?"),
            keep_blank_values=True,
            max_num_fields=100,
        )
    except ValueError:
        return JSONResponse(
            {
                "error": "invalid-query",
                "message": "query may contain at most 100 fields.",
            },
            status_code=400,
            headers=NO_STORE,
        )
    values = {
        key: items[0] if len(items) == 1 else items for key, items in parsed.items()
    }
    try:
        queue_query_sync(context, values)
    except QuerySyncUnavailable as error:
        return JSONResponse(
            {
                "error": "query-sync-unavailable",
                "message": str(error),
                "transient": True,
            },
            status_code=409,
            headers=NO_STORE,
        )
    return Response(status_code=202, headers=NO_STORE)


def file_response(root: Path, relative: str) -> Response:
    """Serve one file beneath an explicit asset root."""
    root = root.resolve()
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return Response(status_code=404)
    if not candidate.is_file():
        return Response(status_code=404)
    return FileResponse(candidate, headers={"Cache-Control": "no-cache"})
