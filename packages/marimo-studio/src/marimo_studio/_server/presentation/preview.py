"""Return view references with optional presentation preconditions."""

from __future__ import annotations

import asyncio

from starlette.requests import Request
from starlette.responses import PlainTextResponse, Response

from marimo_studio._delivery.urls import (
    EDITOR_SESSION_QUERY_PARAM,
    PRESENTATION_REVISION_QUERY_PARAM,
    STUDIO_CLIENT_QUERY_PARAM,
    UNFRAMED_QUERY_PARAM,
    view_path,
    with_query,
)
from marimo_studio._server.auth import forbidden_response, has_edit_access
from marimo_studio._server.headers import NO_STORE
from marimo_studio._server.notebook_scope import NotebookScope
from marimo_studio._server.ports import SessionState
from marimo_studio._server.records import ServerContext
from marimo_studio._server.request_path import request_reference
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
    if context.mode == "edit" and runtime != "wasm":
        # Server and Prepared previews follow one Studio tab's notebook session.
        binding = await _preview_binding(request, notebook_scope, session, runtime)
        if binding is not None:
            query.extend(
                (
                    (STUDIO_CLIENT_QUERY_PARAM, binding[0]),
                    (EDITOR_SESSION_QUERY_PARAM, binding[1]),
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
        request_reference(request, with_query(view_path(view), query)), headers=NO_STORE
    )


async def _preview_binding(
    request: Request,
    notebook_scope: NotebookScope,
    session: str | None,
    runtime: str,
) -> tuple[str, str] | None:
    """Return the Studio client and editor session that a preview follows.

    Code mode names its session, and other callers may name a browser client.
    A Prepared preview needs a tab, so it falls back to the only connected one.
    """
    clients = notebook_scope.clients
    if session is not None:
        return (await clients.session_target(session)).client_id, session
    client_id = request.query_params.get(STUDIO_CLIENT_QUERY_PARAM)
    if client_id is None and runtime != "zero-python":
        return None
    try:
        target = await clients.select_target(client_id=client_id)
    except AgentRequestError as error:
        if client_id is not None or error.code != "browser-client-unavailable":
            raise
        raise _prepared_tab_unavailable() from error
    if target.session_id is None:
        raise _prepared_tab_unavailable()
    return target.client_id, target.session_id


def _prepared_tab_unavailable() -> AgentRequestError:
    return AgentRequestError(
        "browser-client-unavailable",
        "A Prepared preview follows a Studio tab with a notebook session, and "
        "none is connected for this notebook.",
        status_code=409,
        details={"hint": "Open the notebook in Studio, then request the URL."},
    )
