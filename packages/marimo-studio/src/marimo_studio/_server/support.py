"""Serve authenticated Studio support routes."""

from __future__ import annotations

import asyncio
import re
from functools import partial

from starlette.requests import Request
from starlette.responses import (
    JSONResponse,
    Response,
    StreamingResponse,
)
from starlette.types import Receive, Scope, Send

import marimo_studio._delivery.assets as _assets
from marimo_studio._delivery.urls import (
    ACTIVE_VIEW_QUERY_PARAM,
    EDITOR_BINDING_CAPABILITY_QUERY_PARAM,
    SERVER_INSTANCE_QUERY_PARAM,
    STUDIO_CLIENT_QUERY_PARAM,
    WORKSPACE_EVENTS_CAPABILITY_QUERY_PARAM,
    WORKSPACE_STREAM_QUERY_PARAM,
)
from marimo_studio._processes.ownership import (
    propagate_cancellation,
    settle_ownership,
)
from marimo_studio._processes.provider_operation import run_provider_operation
from marimo_studio._server.agent.api import (
    activation_ack_response,
    active_view_handoff_response,
    agent_connection_response,
    show_view_response,
    validate_views_response,
)
from marimo_studio._server.agent.browser import (
    browser_observation_response,
    browser_observations_response,
)
from marimo_studio._server.auth import (
    authentication_required_response,
    forbidden_response,
    has_edit_access,
    has_read_access,
)
from marimo_studio._server.auth import error_response as auth_error_response
from marimo_studio._server.development.routes import change_events
from marimo_studio._server.files import file_response
from marimo_studio._server.headers import NO_STORE
from marimo_studio._server.notebook_scope import NotebookScope
from marimo_studio._server.ports import (
    ExistingSessionAttachment,
    ServerGateway,
    SessionState,
)
from marimo_studio._server.presentation.capability import PresentationCapability
from marimo_studio._server.presentation.ports import KernelProjectionHost
from marimo_studio._server.presentation.projection_routes import (
    outputs_response,
    values_response,
)
from marimo_studio._server.presentation.query_routes import query_response
from marimo_studio._server.records import ServerContext
from marimo_studio._server.runtime.catalog import RuntimeRegistry
from marimo_studio._server.runtime.routes import runtime_config_response
from marimo_studio._server.server_instance import server_instance_id
from marimo_studio._server.studio.document import studio_bootstrap_payload
from marimo_studio._server.studio.editor_capability import (
    editor_binding_capability_matches,
)
from marimo_studio._server.studio.event_capability import (
    workspace_events_capability_matches,
)
from marimo_studio._server.studio.routes import (
    create_view_response,
    delete_view_response,
    project_response,
    source_response,
    unconfigured_view_inventory_payload,
    view_inventory_payload,
)
from marimo_studio._server.workspace_lifecycle import (
    Invalid,
    NeedsView,
    Ready,
    Unconfigured,
    WorkspaceLifecycle,
)
from marimo_studio._workspace.generation import unconfigured_catalog_generation
from marimo_studio._workspace.models import StudioWorkspace
from marimo_studio.errors import MarimoStudioError


class StreamingResponseCleanupError(RuntimeError):
    """Report a body-owner failure observed during response teardown."""

    def __init__(self, errors: tuple[Exception, ...]) -> None:
        self.errors = errors
        super().__init__(
            "Streaming response cleanup failed: "
            + ", ".join(str(error) for error in errors)
        )


class _OwnedStreamingResponse(StreamingResponse):
    """Close an async body iterator whenever response delivery ends."""

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        stream = asyncio.create_task(self.stream_response(send))
        disconnect = asyncio.create_task(self.listen_for_disconnect(receive))
        observed: set[asyncio.Task[None]] = set()
        try:
            completed, _pending = await asyncio.wait(
                (stream, disconnect),
                return_when=asyncio.FIRST_COMPLETED,
            )
            if stream in completed:
                observed.add(stream)
                await stream
            if disconnect in completed:
                observed.add(disconnect)
                await disconnect
        finally:
            stream.cancel()
            disconnect.cancel()
            results, cancellation = await settle_ownership(
                asyncio.gather(stream, disconnect, return_exceptions=True)
            )
            errors = tuple(
                result
                for task, result in zip(
                    (stream, disconnect),
                    results,
                    strict=True,
                )
                if task not in observed and isinstance(result, Exception)
            )
            if errors:
                error = StreamingResponseCleanupError(errors)
                if cancellation is not None:
                    raise error from cancellation
                raise error
            propagate_cancellation(cancellation)
        if self.background is not None:
            await self.background()

    async def stream_response(self, send: Send) -> None:
        try:
            await super().stream_response(send)
        finally:
            close = getattr(self.body_iterator, "aclose", None)
            if close is not None:
                await close()


def _manifest_source_view(support_path: str) -> str | None:
    match = re.fullmatch(r"/views/([^/]+)/source/view\.toml", support_path)
    return match.group(1) if match is not None else None


async def support_response(
    request: Request,
    context: ServerContext,
    lifecycle: WorkspaceLifecycle,
    notebook_scope: NotebookScope,
    support_path: str,
    *,
    server: ServerGateway,
    session_state: SessionState,
    sessions: ExistingSessionAttachment,
    projections: KernelProjectionHost,
    runtimes: RuntimeRegistry,
    presentation_capability: PresentationCapability | None = None,
    presentation_view: str | None = None,
) -> Response:
    """Dispatch one namespaced Studio support request."""
    if support_path.startswith("/assets/"):
        return await file_response(
            _assets.runtime_assets_path(),
            support_path.removeprefix("/assets/"),
        )
    if presentation_capability is None and not has_read_access(request.scope):
        return authentication_required_response()
    if support_path == "/status" and request.method == "GET":
        return _status_response(lifecycle)
    if (
        support_path == "/views"
        and request.method == "GET"
        and isinstance(lifecycle, Invalid)
        and lifecycle.definition is not None
    ):
        return JSONResponse(
            await run_provider_operation(
                partial(
                    view_inventory_payload,
                    lifecycle.definition,
                    None,
                )
            ),
            headers=NO_STORE,
        )
    workspace = lifecycle.workspace if isinstance(lifecycle, Ready) else None
    if support_path == "/dev/events" and request.method == "GET" and context.dev:
        return events_response(
            request,
            workspace,
            context=context,
            notebook_scope=notebook_scope,
            view_name=presentation_view,
            server=server,
        )
    if isinstance(lifecycle, Invalid):
        manifest_view = _manifest_source_view(support_path)
        if lifecycle.definition is not None and manifest_view is not None:
            return await source_response(
                request,
                lifecycle.definition,
                manifest_view,
                "view.toml",
                context.server_token,
                notebook_scope.development,
            )
        return _lifecycle_error_response(lifecycle.error)
    if support_path == "/bootstrap" and request.method == "GET":
        if not isinstance(lifecycle, Ready):
            return _workspace_pending_response(lifecycle)
        return _bootstrap_response(
            request,
            context,
            lifecycle.workspace,
            runtimes,
            session_state,
        )
    if (
        context.mode == "edit"
        and support_path == "/views"
        and isinstance(lifecycle, Unconfigured)
    ):
        generation = unconfigured_catalog_generation(lifecycle.notebook)
        if request.method == "GET":
            return JSONResponse(
                await run_provider_operation(
                    partial(
                        unconfigured_view_inventory_payload,
                        lifecycle.notebook,
                    )
                ),
                headers=NO_STORE,
            )
        return await create_view_response(
            request,
            lifecycle.notebook,
            generation,
            context.server_token,
        )
    if not isinstance(lifecycle, (NeedsView, Ready)):
        return Response(status_code=404)
    definition = lifecycle.definition
    if support_path == "/views":
        if request.method == "GET":
            return JSONResponse(
                await run_provider_operation(
                    partial(
                        view_inventory_payload,
                        definition,
                        workspace,
                    )
                ),
                headers=NO_STORE,
            )
        generation = (
            workspace.catalog_generation
            if workspace is not None
            else definition.config_generation
        )
        return await create_view_response(
            request,
            definition.notebook,
            generation,
            context.server_token,
        )
    if isinstance(lifecycle, NeedsView):
        return _lifecycle_error_response(lifecycle.error)
    assert workspace is not None
    if support_path == "/agent/connection":
        return agent_connection_response(request, context, workspace)
    if support_path == "/validate":
        return await validate_views_response(
            request,
            context,
            workspace,
            notebook_scope,
            session_state,
            runtimes,
        )
    if support_path == "/observations":
        return await browser_observations_response(
            request,
            context,
            workspace,
            notebook_scope,
            session_state,
            runtimes,
        )
    if support_path.startswith("/activations/") and support_path.endswith("/ack"):
        raw_generation = support_path.removeprefix("/activations/").removesuffix("/ack")
        if not raw_generation.isdecimal():
            return Response(status_code=404)
        return await activation_ack_response(
            request,
            context,
            workspace,
            notebook_scope,
            int(raw_generation),
        )
    if support_path.startswith("/active-view-handoffs/"):
        operation_id = support_path.removeprefix("/active-view-handoffs/")
        return await active_view_handoff_response(
            request,
            context,
            workspace,
            notebook_scope,
            operation_id,
        )
    if support_path == "/query" and request.method == "POST":
        return await query_response(
            request,
            context,
            notebook_scope.clients,
            session_state,
            projections,
        )
    if support_path.startswith("/views/"):
        return await _view_response(
            request,
            context,
            workspace,
            notebook_scope,
            support_path.removeprefix("/views/"),
            server=server,
            session_state=session_state,
            sessions=sessions,
            projections=projections,
            runtimes=runtimes,
            presentation_capability=presentation_capability,
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
    return auth_error_response(error)


def _workspace_pending_response(lifecycle: Unconfigured | NeedsView) -> JSONResponse:
    if isinstance(lifecycle, NeedsView):
        return _lifecycle_error_response(lifecycle.error)
    return JSONResponse(
        {
            "error": "workspace-unconfigured",
            "message": "Studio is not configured for this notebook.",
        },
        status_code=409,
        headers=NO_STORE,
    )


def _bootstrap_response(
    request: Request,
    context: ServerContext,
    studio: StudioWorkspace,
    runtimes: RuntimeRegistry,
    session_state: SessionState,
) -> Response:
    client_id = request.query_params.get(STUDIO_CLIENT_QUERY_PARAM)
    if client_id is None or re.fullmatch(r"[A-Za-z0-9_-]{16,128}", client_id) is None:
        return JSONResponse(
            {
                "error": "invalid-browser-client",
                "message": "The Studio browser client identifier is invalid.",
            },
            status_code=400,
            headers=NO_STORE,
        )
    if request.query_params.get(SERVER_INSTANCE_QUERY_PARAM) != server_instance_id(
        context.server_token
    ):
        return Response(status_code=204, headers=NO_STORE)
    native_session_id = request.query_params.get("session_id")
    if (
        not isinstance(native_session_id, str)
        or not session_state.is_session_id(native_session_id)
        or not editor_binding_capability_matches(
            request.query_params.get(EDITOR_BINDING_CAPABILITY_QUERY_PARAM),
            context,
            client_id,
            native_session_id,
        )
    ):
        return JSONResponse(
            {
                "error": "invalid-editor-binding",
                "message": "The Studio editor binding capability is invalid.",
            },
            status_code=403,
            headers=NO_STORE,
        )
    requested = request.query_params.get(ACTIVE_VIEW_QUERY_PARAM)
    selected = requested if requested in studio.views else studio.default_view
    return JSONResponse(
        studio_bootstrap_payload(
            studio,
            context.base_url,
            selected,
            context.server_token,
            context.file_key,
            request.query_params.multi_items(),
            context.routing_query,
            runtimes.options,
            client_id,
            native_session_id,
        ),
        headers=NO_STORE,
    )


async def _view_response(
    request: Request,
    context: ServerContext,
    studio: StudioWorkspace,
    notebook_scope: NotebookScope,
    relative: str,
    *,
    server: ServerGateway,
    session_state: SessionState,
    sessions: ExistingSessionAttachment,
    projections: KernelProjectionHost,
    runtimes: RuntimeRegistry,
    presentation_capability: PresentationCapability | None = None,
) -> Response:
    presentation = notebook_scope.presentation
    view_name, separator, route = relative.partition("/")
    if not separator:
        return await delete_view_response(
            request,
            studio,
            view_name,
            context.server_token,
            presentation,
            notebook_scope.development,
        )
    if route == "show":
        return await show_view_response(
            request,
            context,
            studio,
            view_name,
            notebook_scope,
            session_state,
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
            server=server,
        )
    if route == "observation":
        return await browser_observation_response(
            request,
            context,
            view_name,
            notebook_scope,
            runtimes,
        )
    if route == "project":
        return await project_response(
            request,
            studio,
            view_name,
            notebook_scope.development,
        )
    if route.startswith("source/"):
        return await source_response(
            request,
            studio,
            view_name,
            route.removeprefix("source/"),
            context.server_token,
            notebook_scope.development,
        )
    if route == "config" and request.method == "GET":
        return await runtime_config_response(
            request,
            context,
            presentation,
            notebook_scope.clients,
            view_name,
            sessions=session_state,
            attachment=sessions,
            runtimes=runtimes,
            session_ids=notebook_scope.session_ids,
            presentation_capability=presentation_capability,
        )
    if route == "values" and request.method == "POST":
        return await values_response(
            request,
            context,
            presentation,
            view_name,
            projections,
            session_state,
            authorized_revision=(
                presentation_capability.revision
                if presentation_capability is not None
                else None
            ),
        )
    if route == "outputs" and request.method == "POST":
        return await outputs_response(
            request,
            context,
            presentation,
            view_name,
            projections,
            session_state,
            authorized_revision=(
                presentation_capability.revision
                if presentation_capability is not None
                else None
            ),
        )
    return Response(status_code=404)


def events_response(
    request: Request,
    studio: StudioWorkspace | None,
    context: ServerContext,
    notebook_scope: NotebookScope,
    view_name: str | None = None,
    *,
    server: ServerGateway,
) -> Response:
    """Stream source and notebook changes until the server shuts down."""
    if request.query_params.get(SERVER_INSTANCE_QUERY_PARAM) != server_instance_id(
        context.server_token
    ):
        return Response(status_code=204, headers=NO_STORE)
    client_id = (
        request.query_params.get(STUDIO_CLIENT_QUERY_PARAM)
        if view_name is None
        else None
    )
    if client_id is not None and not has_edit_access(request.scope):
        return forbidden_response()
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
    if client_id is not None and not workspace_events_capability_matches(
        request.query_params.get(WORKSPACE_EVENTS_CAPABILITY_QUERY_PARAM),
        context,
        client_id,
    ):
        return JSONResponse(
            {
                "error": "workspace-events-forbidden",
                "message": "The Studio workspace event capability is invalid.",
            },
            status_code=403,
            headers=NO_STORE,
        )
    active_view = (
        request.query_params.get(ACTIVE_VIEW_QUERY_PARAM)
        if client_id is not None
        else None
    )
    stream_value = (
        request.query_params.get(WORKSPACE_STREAM_QUERY_PARAM)
        if client_id is not None
        else None
    )
    stream_generation = (
        int(stream_value)
        if stream_value is not None
        and re.fullmatch(r"[1-9][0-9]{0,15}", stream_value) is not None
        and int(stream_value) <= 9_007_199_254_740_991
        else None
    )
    if client_id is not None and stream_generation is None:
        return JSONResponse(
            {
                "error": "invalid-browser-connection",
                "message": "The Studio browser connection generation is invalid.",
            },
            status_code=400,
            headers=NO_STORE,
        )
    if active_view is not None and (studio is None or active_view not in studio.views):
        return JSONResponse(
            {
                "error": "view-not-found",
                "message": "The active Studio view does not exist.",
            },
            status_code=404,
            headers=NO_STORE,
        )
    return _OwnedStreamingResponse(
        change_events(
            studio,
            view_name,
            stop_requested=lambda: server.shutdown_requested(context),
            clients=notebook_scope.clients,
            agents=notebook_scope.agents,
            client_id=client_id,
            stream_generation=stream_generation,
            active_view=active_view,
            development=notebook_scope.development,
        ),
        media_type="text/event-stream",
        headers={**NO_STORE, "X-Accel-Buffering": "no"},
    )
