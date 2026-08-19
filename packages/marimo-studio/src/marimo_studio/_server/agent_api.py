"""Serve targeted activation and fresh browser analysis requests."""

from __future__ import annotations

import json
from typing import Any

from starlette.background import BackgroundTask
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from marimo_studio._capabilities import ServerContext, SessionState
from marimo_studio._runtime_process import check_runtime_studio_isolated
from marimo_studio._server.auth import (
    error_response,
    forbidden_response,
    has_edit_access,
    invalid_server_token_response,
)
from marimo_studio._server.browser_agent import observe_views
from marimo_studio._server.headers import NO_STORE
from marimo_studio._server.notebook_scope import NotebookScope
from marimo_studio._server.request_lifecycle import (
    RequestDisconnected,
    run_while_connected,
)
from marimo_studio._server.runtimes import RuntimeRegistry
from marimo_studio._server.view_activation import (
    BrowserViewTarget,
    SessionViewTarget,
    activate_studio_view,
)
from marimo_studio._workspace.models import StudioWorkspace
from marimo_studio.activation import ViewActivationRequest
from marimo_studio.agent_models import BrowserObservation
from marimo_studio.analysis import AnalysisRequest, analyze_studio
from marimo_studio.errors import (
    CapabilityInputError,
    MarimoStudioError,
)


def agent_connection_response(
    request: Request,
    context: ServerContext,
    studio: StudioWorkspace,
) -> Response:
    """Return the mutation token to an authenticated edit client."""
    if request.method != "GET":
        return Response(status_code=405)
    if not has_edit_access(request.scope):
        return forbidden_response()
    return JSONResponse(
        {
            "schema": 1,
            "notebook": str(studio.notebook),
            "server_token": context.server_token,
        },
        headers=NO_STORE,
    )


async def activate_view_response(
    request: Request,
    context: ServerContext,
    studio: StudioWorkspace,
    view_name: str,
    notebook_scope: NotebookScope,
    sessions: SessionState,
) -> Response:
    """Select one view in a session-bound or external Studio browser."""
    if request.method != "PATCH":
        return Response(status_code=405)
    if not has_edit_access(request.scope):
        return forbidden_response()
    if token_error := invalid_server_token_response(request, context.server_token):
        return token_error
    session_id = request.headers.get("Marimo-Session-Id")
    try:
        activation_request = ViewActivationRequest.from_dict(
            view_name,
            await _json_body(request),
        )
        if session_id is not None and activation_request.browser_client is not None:
            raise CapabilityInputError(
                "invalid-activation-request",
                "browser_client",
                "Session-bound activation cannot select another browser client",
            )
        target = (
            SessionViewTarget(session_id)
            if session_id is not None
            else BrowserViewTarget(activation_request.browser_client)
        )
    except CapabilityInputError as error:
        return error_response(error)

    try:
        result = await run_while_connected(
            request,
            activate_studio_view(
                context,
                studio,
                notebook_scope,
                sessions,
                view_name,
                target,
            ),
        )
    except RequestDisconnected:
        return Response(status_code=499)
    except MarimoStudioError as error:
        return error_response(error)
    background = (
        BackgroundTask(
            sessions.reload_page,
            context,
            result.view,
            result.session_id,
        )
        if result.state == "reload-requested"
        else None
    )
    return JSONResponse(
        result.to_dict(),
        status_code=202 if result.state == "reload-requested" else 200,
        headers=NO_STORE,
        background=background,
    )


async def activation_ack_response(
    request: Request,
    context: ServerContext,
    notebook_scope: NotebookScope,
    generation: int,
) -> Response:
    """Acknowledge a completed in-place view transition."""
    if request.method != "POST":
        return Response(status_code=405)
    if not has_edit_access(request.scope):
        return forbidden_response()
    if token_error := invalid_server_token_response(request, context.server_token):
        return token_error
    body = await _json_body(request)
    schema = body.get("schema") if isinstance(body, dict) else None
    if (
        not isinstance(body, dict)
        or set(body) != {"schema", "clientId", "view"}
        or not isinstance(schema, int)
        or isinstance(schema, bool)
        or schema != 1
        or not _nonempty(body.get("clientId"))
        or not _nonempty(body.get("view"))
    ):
        return _invalid_payload("invalid-activation-ack")
    acknowledged = await notebook_scope.agents.acknowledge_activation(
        body["clientId"],
        generation,
        body["view"],
    )
    if not acknowledged:
        return JSONResponse(
            {
                "error": "activation-not-pending",
                "message": "The view activation is no longer pending.",
            },
            status_code=409,
            headers=NO_STORE,
        )
    return Response(status_code=204, headers=NO_STORE)


async def analyze_views_response(
    request: Request,
    context: ServerContext,
    studio: StudioWorkspace,
    notebook_scope: NotebookScope,
    sessions: SessionState,
    runtimes: RuntimeRegistry,
) -> Response:
    """Analyze source, runtime, and fresh rendered browser evidence."""
    if request.method != "POST":
        return Response(status_code=405)
    if not has_edit_access(request.scope):
        return forbidden_response()
    if token_error := invalid_server_token_response(request, context.server_token):
        return token_error
    session_id = request.headers.get("Marimo-Session-Id")
    if session_id is not None and not sessions.exists(context, session_id):
        return JSONResponse(
            {
                "error": "unknown-session",
                "message": "Analysis requires the active Marimo session.",
            },
            status_code=409,
            headers=NO_STORE,
        )
    try:
        analysis_request = AnalysisRequest.from_dict(await _json_body(request))
    except CapabilityInputError as error:
        return error_response(error)
    if session_id is not None:
        try:
            analysis_request.require_focused_view()
        except CapabilityInputError as error:
            return error_response(error)

    async def observe(
        _studio: StudioWorkspace,
        views: tuple[str, ...],
        revisions: dict[str, str],
    ) -> tuple[BrowserObservation, ...]:
        return await observe_views(
            context,
            notebook_scope,
            views,
            revisions,
            runtime=studio.default_runtime,
            timeout=analysis_request.browser_timeout,
            session_id=session_id,
            client_id=analysis_request.browser_client,
            allow_view_activation=session_id is None,
            sessions=sessions,
            runtimes=runtimes,
        )

    try:
        report = await run_while_connected(
            request,
            analyze_studio(
                studio,
                analysis_request.options,
                observe_browser=(observe if analysis_request.require_browser else None),
                runtime_checker=check_runtime_studio_isolated,
            ),
        )
    except RequestDisconnected:
        return Response(status_code=499)
    except MarimoStudioError as error:
        return error_response(error)
    return JSONResponse(report.to_dict(), headers=NO_STORE)


def _invalid_payload(code: str) -> JSONResponse:
    return JSONResponse(
        {"error": code, "message": "The agent request payload is invalid."},
        status_code=400,
        headers=NO_STORE,
    )


async def _json_body(request: Request) -> Any:
    try:
        return await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None


def _nonempty(value: object) -> bool:
    return isinstance(value, str) and bool(value)


__all__ = [
    "activate_view_response",
    "activation_ack_response",
    "agent_connection_response",
    "analyze_views_response",
]
