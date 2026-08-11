"""Serve targeted activation and fresh browser analysis requests."""

from __future__ import annotations

import json
import math
from typing import Any

from starlette.background import BackgroundTask
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from marimo_studio._capabilities import ServerContext, SessionState
from marimo_studio._runtime_limits import (
    DEFAULT_RUNTIME_TIMEOUT,
    MAX_RUNTIME_TIMEOUT,
)
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
from marimo_studio._workspace.models import StudioWorkspace
from marimo_studio.agent_models import BrowserObservation
from marimo_studio.analysis import analyze_studio
from marimo_studio.errors import AgentRequestError, MarimoStudioError

_MAX_ANALYSIS_BROWSER_TIMEOUT = 20.0
_ACTIVATION_TIMEOUT = 5.0
_CLIENT_CONNECT_TIMEOUT = 1.0


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
    """Select one view in the Studio tab that owns the calling code session."""
    if request.method != "PATCH":
        return Response(status_code=405)
    if not has_edit_access(request.scope):
        return forbidden_response()
    if token_error := invalid_server_token_response(request, context.server_token):
        return token_error
    if view_name not in studio.views:
        return Response(status_code=404)
    session_id = request.headers.get("Marimo-Session-Id")
    if not session_id or not sessions.exists(context, session_id):
        return JSONResponse(
            {
                "error": "unknown-session",
                "message": "View activation requires the active Marimo session.",
            },
            status_code=409,
            headers=NO_STORE,
        )

    async def activate() -> Response:
        target = await notebook_scope.clients.wait_for_session_target(
            session_id,
            _CLIENT_CONNECT_TIMEOUT,
        )
        if target is not None:
            activation = await notebook_scope.agents.activate(
                target,
                view_name,
            )
            await notebook_scope.agents.wait_for_activation(
                activation,
                _ACTIVATION_TIMEOUT,
            )
            return JSONResponse(
                {
                    "schema": 1,
                    "notebook": str(studio.notebook),
                    "view": view_name,
                    "state": "active",
                    "generation": activation.generation,
                    "transition": "in-place",
                    "client_id": target.client_id,
                    "session_id": session_id,
                },
                headers=NO_STORE,
            )

        retained = await notebook_scope.clients.binding_for_session(session_id)
        if retained is not None:
            raise AgentRequestError(
                "browser-client-unavailable",
                "The Studio browser is reconnecting. Retry view activation shortly.",
                status_code=409,
            )
        generation = await notebook_scope.agents.reserve_generation()
        return JSONResponse(
            {
                "schema": 1,
                "notebook": str(studio.notebook),
                "view": view_name,
                "state": "reload-requested",
                "generation": generation,
                "transition": "reload",
                "session_id": session_id,
            },
            status_code=202,
            headers=NO_STORE,
            background=BackgroundTask(
                sessions.reload_page,
                context,
                view_name,
                session_id,
            ),
        )

    try:
        return await run_while_connected(request, activate())
    except RequestDisconnected:
        return Response(status_code=499)
    except MarimoStudioError as error:
        return error_response(error)


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
    if (
        not isinstance(body, dict)
        or set(body) != {"schema", "clientId", "view"}
        or body.get("schema") != 1
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
    body = await _json_body(request)
    if not isinstance(body, dict) or not set(body).issubset(
        {
            "view",
            "timeout",
            "runtime_timeout",
            "require_browser",
            "browser_client",
        }
    ):
        return _invalid_analysis_request()
    view_name = body.get("view")
    timeout = body.get("timeout", 10.0)
    runtime_timeout = body.get("runtime_timeout", DEFAULT_RUNTIME_TIMEOUT)
    require_browser = body.get("require_browser", True)
    client_id = body.get("browser_client")
    if (
        (view_name is not None and not isinstance(view_name, str))
        or not _valid_number(timeout, _MAX_ANALYSIS_BROWSER_TIMEOUT)
        or not _valid_number(runtime_timeout, MAX_RUNTIME_TIMEOUT)
        or not isinstance(require_browser, bool)
        or (client_id is not None and not _nonempty(client_id))
    ):
        return _invalid_analysis_request()
    if session_id is not None and require_browser and view_name is None:
        return JSONResponse(
            {
                "error": "focused-analysis-required",
                "message": (
                    "Code-mode browser analysis requires one active view. "
                    "Activate it in one call, then analyze it in the next call."
                ),
            },
            status_code=400,
            headers=NO_STORE,
        )

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
            timeout=float(timeout),
            session_id=session_id,
            client_id=client_id,
            allow_view_activation=session_id is None,
            sessions=sessions,
            runtimes=runtimes,
        )

    try:
        report = await run_while_connected(
            request,
            analyze_studio(
                studio,
                view_name=view_name,
                observe_browser=observe if require_browser else None,
                require_browser=require_browser,
                runtime_checker=check_runtime_studio_isolated,
                runtime_timeout=float(runtime_timeout),
            ),
        )
    except RequestDisconnected:
        return Response(status_code=499)
    except MarimoStudioError as error:
        return error_response(error)
    return JSONResponse(report.to_dict(), headers=NO_STORE)


def _invalid_analysis_request() -> JSONResponse:
    return JSONResponse(
        {
            "error": "invalid-analysis-request",
            "message": (
                "view must be a string or null, timeout must be a finite number "
                f"between 0 and {_MAX_ANALYSIS_BROWSER_TIMEOUT:g}, runtime_timeout "
                f"must be a finite number between 0 and {MAX_RUNTIME_TIMEOUT:g}, "
                "require_browser must be a boolean, and browser_client must be a "
                "string or null."
            ),
        },
        status_code=400,
        headers=NO_STORE,
    )


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


def _valid_number(value: object, maximum: float) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and 0 <= value <= maximum
    )


def _nonempty(value: object) -> bool:
    return isinstance(value, str) and bool(value)


__all__ = [
    "activate_view_response",
    "activation_ack_response",
    "agent_connection_response",
    "analyze_views_response",
]
