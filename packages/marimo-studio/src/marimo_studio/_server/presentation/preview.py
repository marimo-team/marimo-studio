"""Return ordinary view URLs with optional presentation preconditions."""

from __future__ import annotations

import asyncio

from starlette.requests import Request
from starlette.responses import PlainTextResponse, Response

from marimo_studio._delivery.urls import (
    EDITOR_SESSION_QUERY_PARAM,
    PRESENTATION_REVISION_QUERY_PARAM,
    STUDIO_CLIENT_QUERY_PARAM,
    UNFRAMED_QUERY_PARAM,
    view_url,
    with_query,
)
from marimo_studio._server.auth import forbidden_response, has_edit_access
from marimo_studio._server.headers import NO_STORE
from marimo_studio._server.notebook_scope import NotebookScope
from marimo_studio._server.ports import SessionState
from marimo_studio._server.records import ServerContext
from marimo_studio._server.runtime.catalog import RuntimeRegistry
from marimo_studio._workspace import load_studio
from marimo_studio._workspace.models import StudioWorkspace
from marimo_studio._workspace.ownership import (
    observed_view_owner,
    require_view_owner,
    workspace_view_owner,
)
from marimo_studio.errors import AgentRequestError
from marimo_studio.view_providers import BuildProfile


async def preview_url_response(
    request: Request,
    context: ServerContext,
    studio: StudioWorkspace,
    view: str,
    notebook_scope: NotebookScope,
    runtimes: RuntimeRegistry,
    sessions: SessionState,
) -> Response:
    """Resolve a URL using server-owned routing and publication identity."""
    if request.method != "GET":
        return Response(status_code=405)
    if context.mode == "edit" and not has_edit_access(request.scope):
        return forbidden_response()
    for key in ("runtime", "exact", "catalog_generation", "view_generation"):
        if len(request.query_params.getlist(key)) > 1:
            raise AgentRequestError(
                "invalid-preview-request", f"Specify {key} once.", status_code=400
            )
    runtime = request.query_params.get("runtime")
    exact = request.query_params.get("exact", "0")
    if not runtime or exact not in {"0", "1"}:
        raise AgentRequestError(
            "invalid-preview-request",
            "Select a runtime and a boolean exact option.",
            status_code=400,
        )
    runtimes.select(studio, context, runtime)
    catalog = request.query_params.get("catalog_generation")
    generation = request.query_params.get("view_generation")
    if (catalog is None) != (generation is None):
        raise AgentRequestError(
            "invalid-preview-request",
            "Supply both view owner generations.",
            status_code=400,
        )
    owner = (
        observed_view_owner(catalog, generation or None)
        if catalog is not None
        else workspace_view_owner(studio, view)
    )
    require_view_owner(studio, view, owner)
    session = request.headers.get("Marimo-Session-Id")
    if session is not None and not sessions.exists(context, session):
        raise AgentRequestError(
            "preview-session-unavailable",
            "The notebook session changed. Reacquire the workspace.",
            status_code=409,
        )
    query = [*context.routing_query, ("runtime", runtime), (UNFRAMED_QUERY_PARAM, "1")]
    if context.mode == "edit" and session is not None and runtime != "wasm":
        binding = await notebook_scope.clients.binding_for_session(session)
        if binding is None:
            raise AgentRequestError(
                "preview-session-unavailable",
                "The notebook session is not attached to Studio. Reopen its workspace.",
                status_code=409,
            )
        query.extend(
            (
                (STUDIO_CLIENT_QUERY_PARAM, binding.client_id),
                (EDITOR_SESSION_QUERY_PARAM, session),
            )
        )
    if exact == "1":
        profile: BuildProfile = (
            "development" if context.mode == "edit" else "production"
        )
        snapshot = await notebook_scope.presentation.current_published_snapshot_async(
            view, profile=profile
        )
        query.append((PRESENTATION_REVISION_QUERY_PARAM, snapshot.revision))
    current = await asyncio.to_thread(load_studio, context.notebook)
    require_view_owner(current, view, owner)
    return PlainTextResponse(
        with_query(view_url(context.base_url, view), query), headers=NO_STORE
    )
