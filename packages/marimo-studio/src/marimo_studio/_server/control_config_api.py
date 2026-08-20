"""Serve control synchronization metadata without mounting a runtime session."""

from __future__ import annotations

from hashlib import sha256

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from marimo_studio._capabilities import (
    RuntimeProjectionServices,
    ServerContext,
    SessionState,
)
from marimo_studio._server.auth import forbidden_response, has_edit_access
from marimo_studio._server.client_identity import parse_studio_client_id
from marimo_studio._server.headers import NO_STORE
from marimo_studio._server.live_clients import StudioClientRegistry
from marimo_studio._server.presentation import NotebookPresentation
from marimo_studio._server.presentation_payload import build_runtime_config
from marimo_studio._server.runtimes import (
    RuntimeProjectionRequest,
    RuntimeRegistry,
    projection_requirements,
)
from marimo_studio._urls import STUDIO_CLIENT_QUERY_PARAM


async def control_config_response(
    request: Request,
    context: ServerContext,
    presentation: NotebookPresentation,
    clients: StudioClientRegistry,
    view_name: str,
    *,
    services: RuntimeProjectionServices,
    sessions: SessionState,
    runtimes: RuntimeRegistry,
) -> Response:
    """Return exact control identities for one validated Studio editor."""
    if context.mode != "edit" or not has_edit_access(request.scope):
        return forbidden_response()
    client_id = parse_studio_client_id(
        request.query_params.get(STUDIO_CLIENT_QUERY_PARAM)
    )
    if client_id is None:
        return _invalid_client()
    revision = request.query_params.get("revision")
    if revision is None:
        return _revision_unavailable()
    snapshot = presentation.snapshot_for_revision(view_name, revision)
    if snapshot is None:
        return _revision_unavailable()
    session_id = await clients.session_for_client(client_id)
    supplied_session_id = request.headers.get("Marimo-Session-Id")
    if (
        session_id is None
        or supplied_session_id != session_id
        or not sessions.is_session_id(session_id)
        or not sessions.exists(context, session_id)
    ):
        return _session_pending()
    provider, _available = runtimes.select(
        snapshot.resolved.workspace,
        context,
        request.query_params.get("runtime"),
        projection_requirements(snapshot),
    )
    control_revision = sessions.control_revision(context, session_id)
    etag = _control_etag(
        snapshot.revision,
        snapshot.notebook_revision,
        session_id,
        provider.descriptor.id,
        control_revision,
    )
    headers = {**NO_STORE, "ETag": etag}
    if request.headers.get("If-None-Match") == etag:
        return Response(status_code=304, headers=headers)
    controls: object | None = None
    if provider.descriptor.execution != "prepared":
        payload = await build_runtime_config(
            RuntimeProjectionRequest(
                snapshot=snapshot,
                context=context,
                authority="edit",
                session_id=session_id,
                binding_id=client_id,
                services=services,
                control_revision=control_revision,
            ),
            provider,
        )
        runtime = payload["runtime"]
        if isinstance(runtime, dict):
            controls = runtime.get("controls")
    return JSONResponse(
        {
            "schema": 1,
            "revision": snapshot.revision,
            "runtime": provider.descriptor.id,
            "controlRevision": control_revision,
            **({"controls": controls} if controls is not None else {}),
        },
        headers=headers,
    )


def _control_etag(
    revision: str,
    notebook_revision: str,
    session_id: str,
    runtime: str,
    control_revision: int,
) -> str:
    digest = sha256()
    for value in (
        revision,
        notebook_revision,
        session_id,
        runtime,
        str(control_revision),
    ):
        digest.update(value.encode("utf-8"))
        digest.update(b"\0")
    return f'"{digest.hexdigest()}"'


def _invalid_client() -> JSONResponse:
    return JSONResponse(
        {
            "error": "invalid-browser-client",
            "message": "The Studio browser client identifier is invalid.",
        },
        status_code=400,
        headers=NO_STORE,
    )


def _session_pending() -> JSONResponse:
    return JSONResponse(
        {
            "error": "runtime-sync-pending",
            "message": "The Studio editor session is still connecting.",
            "transient": True,
        },
        status_code=409,
        headers=NO_STORE,
    )


def _revision_unavailable() -> JSONResponse:
    return JSONResponse(
        {
            "error": "presentation-revision-unavailable",
            "message": "The requested presentation revision is no longer available.",
            "transient": True,
        },
        status_code=409,
        headers=NO_STORE,
    )


__all__ = ["control_config_response"]
