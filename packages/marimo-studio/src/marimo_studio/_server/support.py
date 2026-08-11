"""Serve authenticated Studio support routes."""

from __future__ import annotations

import re

from starlette.requests import Request
from starlette.responses import (
    HTMLResponse,
    JSONResponse,
    Response,
    StreamingResponse,
)

from marimo_studio import _assets
from marimo_studio._compat.server.context import server_shutdown_requested
from marimo_studio._compat.server.models import ServerContext
from marimo_studio._compat.server.sessions import has_read_access
from marimo_studio._html import cell_host, render
from marimo_studio._server.agent_api import (
    activate_view_response,
    activation_ack_response,
    agent_connection_response,
    analyze_views_response,
)
from marimo_studio._server.auth import authentication_required_response
from marimo_studio._server.browser_agent import (
    browser_observation_response,
    browser_observations_response,
)
from marimo_studio._server.dev import change_events
from marimo_studio._server.files import file_response
from marimo_studio._server.headers import NO_STORE
from marimo_studio._server.notebook_scope import NotebookScope
from marimo_studio._server.projection_api import (
    outputs_response,
    values_response,
)
from marimo_studio._server.query_api import query_response
from marimo_studio._server.runtime_config_api import runtime_config_response
from marimo_studio._server.studio_api import (
    create_view_response,
    delete_view_response,
    source_response,
)
from marimo_studio._server.workspace_lifecycle import (
    Invalid,
    NeedsView,
    Ready,
    WorkspaceLifecycle,
)
from marimo_studio._urls import ACTIVE_VIEW_QUERY_PARAM, STUDIO_CLIENT_QUERY_PARAM
from marimo_studio._workspace.models import StudioWorkspace
from marimo_studio.errors import MarimoStudioError


async def support_response(
    request: Request,
    context: ServerContext,
    lifecycle: WorkspaceLifecycle,
    notebook_scope: NotebookScope,
    support_path: str,
) -> Response:
    """Dispatch one namespaced Studio support request."""
    if support_path.startswith("/assets/"):
        return file_response(
            _assets.runtime_assets_path(),
            support_path.removeprefix("/assets/"),
        )
    if not has_read_access(request.scope):
        return authentication_required_response()
    if support_path == "/status" and request.method == "GET":
        return _status_response(lifecycle)
    if isinstance(lifecycle, Invalid):
        return _lifecycle_error_response(lifecycle.error)
    if not isinstance(lifecycle, (NeedsView, Ready)):
        return Response(status_code=404)
    definition = lifecycle.definition
    workspace = lifecycle.workspace if isinstance(lifecycle, Ready) else None
    if support_path == "/views":
        if request.method == "GET":
            return JSONResponse(
                {
                    "schema": 1,
                    "default_view": definition.default_view,
                    "views": list(workspace.views) if workspace is not None else [],
                },
                headers=NO_STORE,
            )
        return await create_view_response(
            request,
            definition,
            workspace.views if workspace is not None else (),
            context.base_url,
            context.server_token,
            context.routing_query,
        )
    if isinstance(lifecycle, NeedsView):
        return _lifecycle_error_response(lifecycle.error)
    assert workspace is not None
    if support_path == "/agent/connection":
        return agent_connection_response(request, context, workspace)
    if support_path == "/dev/events" and request.method == "GET" and context.dev:
        return events_response(
            request,
            workspace,
            context=context,
            notebook_scope=notebook_scope,
        )
    if support_path == "/analyze":
        return await analyze_views_response(request, context, workspace, notebook_scope)
    if support_path == "/observations":
        return await browser_observations_response(
            request,
            context,
            workspace,
            notebook_scope,
        )
    if support_path.startswith("/activations/") and support_path.endswith("/ack"):
        raw_generation = support_path.removeprefix("/activations/").removesuffix("/ack")
        if not raw_generation.isdecimal():
            return Response(status_code=404)
        return await activation_ack_response(
            request,
            context,
            notebook_scope,
            int(raw_generation),
        )
    if support_path == "/query" and request.method == "POST":
        return await query_response(request, context, notebook_scope.clients)
    if support_path.startswith("/views/"):
        return await _view_response(
            request,
            context,
            workspace,
            notebook_scope,
            support_path.removeprefix("/views/"),
        )
    return Response(status_code=404)


def _status_response(
    lifecycle: WorkspaceLifecycle,
) -> JSONResponse:
    if isinstance(lifecycle, Ready):
        payload: dict[str, object] = {
            "schema": 1,
            "state": "ready",
            "default_view": lifecycle.workspace.default_view,
            "views": list(lifecycle.workspace.views),
        }
    elif isinstance(lifecycle, NeedsView):
        payload = {
            "schema": 1,
            "state": "needs-view",
            "default_view": lifecycle.definition.default_view,
            "views": [],
        }
    elif isinstance(lifecycle, Invalid):
        payload = {
            "schema": 1,
            "state": "error",
            "error": lifecycle.error.code,
            "message": lifecycle.error.public_message(),
        }
    else:
        payload = {"schema": 1, "state": "unconfigured"}
    return JSONResponse(payload, headers=NO_STORE)


def _lifecycle_error_response(error: MarimoStudioError) -> JSONResponse:
    return JSONResponse(
        {
            "error": error.code,
            "message": error.public_message(),
            **error.diagnostic_details(),
            **({"hint": error.public_hint} if error.public_hint else {}),
        },
        status_code=error.status_code,
        headers=NO_STORE,
    )


async def _view_response(
    request: Request,
    context: ServerContext,
    studio: StudioWorkspace,
    notebook_scope: NotebookScope,
    relative: str,
) -> Response:
    presentation = notebook_scope.presentation
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
    if route == "dev/events" and request.method == "GET" and context.dev:
        return events_response(
            request,
            studio,
            context=context,
            notebook_scope=notebook_scope,
            view_name=view_name,
        )
    if route == "activate":
        return await activate_view_response(
            request,
            context,
            studio,
            view_name,
            notebook_scope,
        )
    if route == "observation":
        return await browser_observation_response(
            request,
            view_name,
            notebook_scope,
            context.server_token,
        )
    if route.startswith("source/"):
        return await source_response(
            request,
            studio,
            view_name,
            route.removeprefix("source/"),
            context.server_token,
        )
    if route == "config" and request.method == "GET":
        return await runtime_config_response(
            request,
            context,
            presentation,
            notebook_scope.clients,
            view_name,
        )
    if route == "values" and request.method == "POST":
        return await values_response(request, context, presentation, view_name)
    if route == "outputs" and request.method == "POST":
        return await outputs_response(request, context, presentation, view_name)
    snapshot = await presentation.latest_snapshot_async(view_name)
    resolved = snapshot.resolved
    view = resolved.views[view_name]
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
    request: Request,
    studio: StudioWorkspace,
    context: ServerContext,
    notebook_scope: NotebookScope,
    view_name: str | None = None,
) -> Response:
    """Stream source and notebook changes until the server shuts down."""
    client_id = (
        request.query_params.get(STUDIO_CLIENT_QUERY_PARAM)
        if view_name is None
        else None
    )
    active_view = (
        request.query_params.get(ACTIVE_VIEW_QUERY_PARAM)
        if client_id is not None
        else None
    )
    if (
        client_id is not None
        and re.fullmatch(r"[A-Za-z0-9_-]{16,128}", client_id) is None
    ):
        return JSONResponse(
            {
                "error": "invalid-browser-client",
                "message": "The Studio browser client identifier is invalid.",
            },
            status_code=400,
            headers=NO_STORE,
        )
    if active_view is not None and active_view not in studio.views:
        return JSONResponse(
            {
                "error": "view-not-found",
                "message": "The active Studio view does not exist.",
            },
            status_code=404,
            headers=NO_STORE,
        )
    return StreamingResponse(
        change_events(
            studio,
            view_name,
            stop_requested=lambda: server_shutdown_requested(context),
            clients=notebook_scope.clients,
            agents=notebook_scope.agents,
            client_id=client_id,
            active_view=active_view,
        ),
        media_type="text/event-stream",
        headers={**NO_STORE, "X-Accel-Buffering": "no"},
    )
