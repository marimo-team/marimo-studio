"""Serve targeted activation and fresh browser validation requests."""

from __future__ import annotations

import re

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from marimo_studio._browser_client.protocol import ViewShowRequest
from marimo_studio._server.agent.activation import ActivationAckOutcome
from marimo_studio._server.agent.browser import observe_views
from marimo_studio._server.auth import (
    error_response,
    forbidden_response,
    has_edit_access,
    invalid_server_token_response,
)
from marimo_studio._server.headers import NO_STORE
from marimo_studio._server.notebook_scope import NotebookScope
from marimo_studio._server.ports import SessionState
from marimo_studio._server.presentation.activation import (
    BrowserViewTarget,
    SessionViewTarget,
    activate_studio_view,
)
from marimo_studio._server.records import ServerContext
from marimo_studio._server.request_body import (
    JSONBodyError,
    json_body_error_response,
    read_json_body,
)
from marimo_studio._server.request_lifecycle import (
    RequestDisconnected,
    run_while_connected,
)
from marimo_studio._server.runtime.catalog import RuntimeRegistry
from marimo_studio._validation.evidence import BrowserObservation
from marimo_studio._validation.progressive import (
    ValidationRequest,
    validate_progressively,
)
from marimo_studio._validation.runtime_process import check_runtime_studio_isolated
from marimo_studio._workspace.models import StudioWorkspace
from marimo_studio.errors import (
    CapabilityInputError,
    MarimoStudioError,
)

_AGENT_JSON_MAX_BYTES = 256 * 1024


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


async def show_view_response(
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
        body = await read_json_body(request, max_bytes=_AGENT_JSON_MAX_BYTES)
    except JSONBodyError as error:
        return json_body_error_response(error)
    try:
        activation_request = ViewShowRequest.from_dict(
            view_name,
            body,
        )
        if session_id is not None and activation_request.browser_client is not None:
            raise CapabilityInputError(
                "invalid-show-request",
                "browser_client",
                "A session-bound show request cannot select another browser client",
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
    return JSONResponse(
        result.to_dict(),
        headers=NO_STORE,
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
    try:
        body = await read_json_body(request, max_bytes=_AGENT_JSON_MAX_BYTES)
    except JSONBodyError as error:
        return json_body_error_response(error)
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
    outcome = await notebook_scope.agents.acknowledge_activation(
        body["clientId"],
        generation,
        body["view"],
    )
    return JSONResponse(
        {"schema": 1, "outcome": outcome.value},
        status_code=(
            200
            if outcome is ActivationAckOutcome.APPLIED
            else 202
            if outcome is ActivationAckOutcome.RETRYABLE
            else 409
        ),
        headers=NO_STORE,
    )


async def active_view_handoff_response(
    request: Request,
    context: ServerContext,
    studio: StudioWorkspace,
    notebook_scope: NotebookScope,
    operation_id: str,
) -> Response:
    """Suspend or restore agent targeting around a committed view handoff."""
    if request.method not in {"POST", "DELETE"}:
        return Response(status_code=405)
    if not has_edit_access(request.scope):
        return forbidden_response()
    if token_error := invalid_server_token_response(request, context.server_token):
        return token_error
    if re.fullmatch(r"[A-Za-z0-9_-]{16,128}", operation_id) is None:
        return Response(status_code=404)
    try:
        body = await read_json_body(request, max_bytes=_AGENT_JSON_MAX_BYTES)
    except JSONBodyError as error:
        return json_body_error_response(error)
    if request.method == "DELETE":
        if (
            not isinstance(body, dict)
            or set(body) != {"schema", "clientId"}
            or body.get("schema") != 1
            or isinstance(body.get("schema"), bool)
            or not _nonempty(body.get("clientId"))
        ):
            return _invalid_payload("invalid-active-view-handoff")
        restored = await notebook_scope.clients.rollback_active_view_handoff(
            body["clientId"],
            operation_id,
        )
        return Response(status_code=204 if restored else 409, headers=NO_STORE)
    if (
        not isinstance(body, dict)
        or set(body) != {"schema", "clientId", "fromView", "toView"}
        or body.get("schema") != 1
        or isinstance(body.get("schema"), bool)
        or not _nonempty(body.get("clientId"))
        or not _nonempty(body.get("fromView"))
        or not _nonempty(body.get("toView"))
        or body["fromView"] not in studio.views
        or body["toView"] not in studio.views
    ):
        return _invalid_payload("invalid-active-view-handoff")
    suspended = await notebook_scope.clients.begin_active_view_handoff(
        body["clientId"],
        operation_id,
        body["fromView"],
        body["toView"],
    )
    return Response(status_code=204 if suspended else 409, headers=NO_STORE)


async def validate_views_response(
    request: Request,
    context: ServerContext,
    studio: StudioWorkspace,
    notebook_scope: NotebookScope,
    sessions: SessionState,
    runtimes: RuntimeRegistry,
) -> Response:
    """Validate source, runtime, and fresh rendered browser evidence."""
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
                "message": "Browser validation requires the active Marimo session.",
            },
            status_code=409,
            headers=NO_STORE,
        )
    try:
        body = await read_json_body(request, max_bytes=_AGENT_JSON_MAX_BYTES)
    except JSONBodyError as error:
        return json_body_error_response(error)
    try:
        validation_request = ValidationRequest.from_dict(body)
    except CapabilityInputError as error:
        return error_response(error)
    if session_id is not None:
        try:
            validation_request.require_focused_view()
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
            timeout=validation_request.browser_timeout,
            session_id=session_id,
            client_id=validation_request.browser_client,
            allow_view_activation=session_id is None,
            sessions=sessions,
            runtimes=runtimes,
        )

    try:
        report = await run_while_connected(
            request,
            validate_progressively(
                studio,
                validation_request.options,
                observe_browser=(
                    observe if validation_request.require_browser else None
                ),
                runtime_checker=check_runtime_studio_isolated,
                development=notebook_scope.development,
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


def _nonempty(value: object) -> bool:
    return isinstance(value, str) and bool(value)
