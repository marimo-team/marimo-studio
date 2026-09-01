"""Request fresh rendered evidence from one connected Studio browser."""

from __future__ import annotations

import asyncio
import math
from typing import cast

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from marimo_studio._browser_client.protocol import decode_browser_observation
from marimo_studio._server.auth import (
    error_response,
    forbidden_response,
    has_edit_access,
    invalid_server_token_response,
)
from marimo_studio._server.headers import NO_STORE
from marimo_studio._server.notebook_scope import NotebookScope
from marimo_studio._server.ports import SessionState
from marimo_studio._server.presentation.evidence import validate_projection_evidence
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
from marimo_studio._workspace.models import StudioWorkspace
from marimo_studio.errors import AgentRequestError, MarimoStudioError, ProtocolError

_MAX_OBSERVATION_TIMEOUT = 300.0
_CLIENT_CONNECT_TIMEOUT = 1.0
_OBSERVATION_JSON_MAX_BYTES = 4 * 1024 * 1024
_OBSERVATION_REQUEST_JSON_MAX_BYTES = 512 * 1024


async def browser_observation_response(
    request: Request,
    context: ServerContext,
    view_name: str,
    notebook_scope: NotebookScope,
    runtimes: RuntimeRegistry,
) -> Response:
    """Record browser evidence for one server-issued observation request."""
    if request.method != "PUT":
        return Response(status_code=405)
    if not has_edit_access(request.scope):
        return forbidden_response()
    if token_error := invalid_server_token_response(request, context.server_token):
        return token_error
    try:
        payload = await read_json_body(request, max_bytes=_OBSERVATION_JSON_MAX_BYTES)
    except JSONBodyError as error:
        return json_body_error_response(error)
    try:
        observation = decode_browser_observation(payload, view_name)
    except ProtocolError:
        return _invalid_payload("invalid-browser-observation")
    if observation.runtime == "server" and observation.session_id is None:
        return _invalid_payload("invalid-browser-observation")
    snapshot = notebook_scope.presentation.snapshot_for_revision(
        view_name,
        observation.revision or "",
    )
    if snapshot is None:
        current = await notebook_scope.presentation.snapshot_async(view_name)
        if current.revision == observation.revision:
            snapshot = current
    if snapshot is None:
        return JSONResponse(
            {
                "error": "presentation-revision-unavailable",
                "message": "The observed presentation revision is no longer available.",
            },
            status_code=409,
            headers=NO_STORE,
        )
    try:
        runtime = await runtimes.project_evidence(
            snapshot,
            context,
            observation.runtime,
            observation.session_id,
            observation.session_id,
            observation.session_id,
            observation.session_id,
        )
        validate_projection_evidence(observation, snapshot, runtime)
    except (MarimoStudioError, ProtocolError):
        return _invalid_payload("invalid-browser-observation")
    if not await notebook_scope.agents.record(observation):
        return JSONResponse(
            {
                "error": "browser-observation-rejected",
                "message": "The browser observation does not match an active request.",
            },
            status_code=409,
            headers=NO_STORE,
        )
    return Response(status_code=204, headers=NO_STORE)


async def browser_observations_response(
    request: Request,
    context: ServerContext,
    studio: StudioWorkspace,
    notebook_scope: NotebookScope,
    sessions: SessionState,
    runtimes: RuntimeRegistry,
) -> Response:
    """Request and return fresh browser evidence for selected views."""
    if request.method != "POST":
        return Response(status_code=405)
    if not has_edit_access(request.scope):
        return forbidden_response()
    if token_error := invalid_server_token_response(request, context.server_token):
        return token_error
    try:
        body = await read_json_body(
            request,
            max_bytes=_OBSERVATION_REQUEST_JSON_MAX_BYTES,
        )
    except JSONBodyError as error:
        return json_body_error_response(error)
    if not isinstance(body, dict) or set(body) != {
        "schema",
        "views",
        "revisions",
        "runtime",
        "timeout",
        "browserClient",
    }:
        return _invalid_payload("invalid-browser-request")
    requested = body.get("views")
    raw_revisions = body.get("revisions")
    runtime_value = body.get("runtime")
    client_id = body.get("browserClient")
    if (
        type(body.get("schema")) is not int
        or body.get("schema") != 1
        or not isinstance(requested, list)
        or not all(isinstance(view, str) and view for view in requested)
        or not isinstance(raw_revisions, dict)
        or not all(
            isinstance(key, str) and isinstance(value, str) and value
            for key, value in raw_revisions.items()
        )
        or (
            runtime_value is not None
            and (not isinstance(runtime_value, str) or not runtime_value)
        )
        or (client_id is not None and (not isinstance(client_id, str) or not client_id))
    ):
        return _invalid_payload("invalid-browser-request")
    requested_views = cast(list[str], requested)
    revision_values = cast(dict[str, str], raw_revisions)
    views = (
        tuple(dict.fromkeys(requested_views))
        if requested_views
        else tuple(studio.views)
    )
    if len(views) > 100:
        return _invalid_payload("too-many-browser-views")
    if any(view not in studio.views for view in views):
        return JSONResponse(
            {
                "error": "view-not-found",
                "message": "Every requested view must exist in this workspace.",
            },
            status_code=404,
            headers=NO_STORE,
        )
    runtime = runtime_value or studio.default_runtime
    if runtime not in runtimes.ids:
        return _invalid_payload("invalid-runtime")
    timeout = _finite_timeout(body.get("timeout"), default=10.0)
    if timeout is None:
        return _invalid_payload("invalid-browser-timeout")
    if set(revision_values) != set(views):
        return _invalid_payload("invalid-browser-revisions")
    session_id = request.headers.get("Marimo-Session-Id")
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout

    async def observe_before_deadline() -> tuple[BrowserObservation, ...]:
        remaining = max(0.0, deadline - loop.time())
        try:
            return await asyncio.wait_for(
                observe_views(
                    context,
                    notebook_scope,
                    views,
                    revision_values,
                    runtime=runtime,
                    timeout=remaining,
                    session_id=session_id,
                    client_id=client_id,
                    allow_view_activation=session_id is None,
                    sessions=sessions,
                    runtimes=runtimes,
                ),
                timeout=remaining,
            )
        except asyncio.TimeoutError as error:
            raise AgentRequestError(
                "browser-observation-timeout",
                "Studio did not return fresh browser evidence in time.",
                status_code=504,
            ) from error

    try:
        observations = await run_while_connected(
            request,
            observe_before_deadline(),
        )
    except RequestDisconnected:
        return Response(status_code=499)
    except MarimoStudioError as error:
        return error_response(error)
    return JSONResponse(
        {
            "schema": 1,
            "notebook": str(studio.notebook),
            "observations": [item.to_dict() for item in observations],
        },
        headers=NO_STORE,
    )


async def observe_views(
    context: ServerContext,
    notebook_scope: NotebookScope,
    views: tuple[str, ...],
    revisions: dict[str, str],
    *,
    runtime: str,
    timeout: float,
    session_id: str | None,
    client_id: str | None,
    allow_view_activation: bool = True,
    sessions: SessionState,
    runtimes: RuntimeRegistry,
) -> tuple[BrowserObservation, ...]:
    if set(revisions) != set(views):
        raise AgentRequestError(
            "invalid-browser-revisions",
            "Browser validation requires one source revision for every view.",
            status_code=400,
        )
    if client_id is None and session_id is not None:
        target = await notebook_scope.clients.wait_for_session_target(
            session_id,
            _CLIENT_CONNECT_TIMEOUT,
        )
    else:
        target = None
    if target is None:
        target = await notebook_scope.clients.select_target(
            session_id=session_id,
            client_id=client_id,
        )
    bound_session_id = target.session_id
    if session_id is not None and bound_session_id != session_id:
        raise AgentRequestError(
            "browser-session-changed",
            "The Studio browser is attached to a different Marimo session.",
            status_code=409,
        )
    if bound_session_id is None or not sessions.exists(context, bound_session_id):
        raise AgentRequestError(
            "browser-session-unavailable",
            "The Studio editor session is still connecting.",
            status_code=409,
        )
    if not allow_view_activation:
        if len(views) != 1:
            raise AgentRequestError(
                "focused-view-required",
                "Code-mode browser validation accepts one active view at a time.",
                status_code=400,
            )
        active_view = target.active_view
        if active_view != views[0]:
            raise AgentRequestError(
                "browser-view-not-active",
                (
                    f"Activate view {views[0]!r} in one code-mode call, then "
                    "validate it in the next call."
                ),
                status_code=409,
            )
    session_id = bound_session_id
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    observations: list[BrowserObservation] = []
    for view in views:
        remaining = max(0.0, deadline - loop.time())
        if allow_view_activation and target.active_view != view:
            activation = await notebook_scope.agents.activate(target, view)
            await notebook_scope.agents.wait_for_activation(activation, remaining)
            current_target = await notebook_scope.clients.target_for_client(
                target.client_id
            )
            if (
                current_target is None
                or current_target.session_id != session_id
                or current_target.binding_generation != target.binding_generation
                or current_target.active_view != view
            ):
                raise AgentRequestError(
                    "browser-view-not-active",
                    "The Studio browser changed before browser validation began.",
                    status_code=409,
                )
            target = current_target
        snapshot = await notebook_scope.presentation.snapshot_async(view)
        if snapshot.revision != revisions[view]:
            raise AgentRequestError(
                "validation-source-changed",
                "Studio sources changed before browser validation began.",
                status_code=409,
            )
        runtime_instance = (
            await runtimes.project(
                snapshot,
                context,
                runtime,
                session_id,
                session_id,
                session_id,
                session_id,
            )
        ).instance
        observation_request = await notebook_scope.agents.request_observation(
            target,
            view,
            runtime,
            runtime_instance,
            revisions[view],
            active_view_generation=target.active_view_generation,
        )
        remaining = max(0.0, deadline - loop.time())
        observations.append(
            await notebook_scope.agents.wait_for_observation(
                observation_request,
                remaining,
            )
        )
    return tuple(observations)


def _finite_timeout(raw: object, *, default: float) -> float | None:
    if raw is None:
        return default
    if not isinstance(raw, (int, float)) or isinstance(raw, bool):
        return None
    if not 0 <= raw <= _MAX_OBSERVATION_TIMEOUT:
        return None
    value = float(raw)
    if math.isfinite(value):
        return value
    return None


def _invalid_payload(code: str) -> JSONResponse:
    return JSONResponse(
        {"error": code, "message": "The agent request payload is invalid."},
        status_code=400,
        headers=NO_STORE,
    )
