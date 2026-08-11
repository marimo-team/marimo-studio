"""Serve runtime configuration for standalone and Studio-owned views."""

from __future__ import annotations

import re

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from marimo_studio._capabilities import (
    ExistingSessionAttachment,
    ServerContext,
    SessionState,
)
from marimo_studio._server.auth import forbidden_response, has_edit_access
from marimo_studio._server.headers import NO_STORE
from marimo_studio._server.live_clients import StudioClientRegistry
from marimo_studio._server.presentation import NotebookPresentation
from marimo_studio._server.presentation_payload import build_runtime_config
from marimo_studio._server.runtimes import RuntimeRegistry
from marimo_studio._urls import STUDIO_CLIENT_QUERY_PARAM

_CLIENT_PATTERN = re.compile(r"[A-Za-z0-9_-]{16,128}")
_PREVIEW_SESSION_HEADER = "Marimo-Studio-Preview-Session-Id"


async def runtime_config_response(
    request: Request,
    context: ServerContext,
    presentation: NotebookPresentation,
    clients: StudioClientRegistry,
    view_name: str,
    *,
    sessions: SessionState,
    attachment: ExistingSessionAttachment,
    runtimes: RuntimeRegistry,
) -> Response:
    """Return configuration bound to the requesting Studio editor session."""
    client_id = request.query_params.get(STUDIO_CLIENT_QUERY_PARAM)
    session_id = request.headers.get("Marimo-Session-Id")
    preview_session_id = request.headers.get(_PREVIEW_SESSION_HEADER)
    if client_id is not None:
        if not has_edit_access(request.scope):
            return forbidden_response()
        if (
            _CLIENT_PATTERN.fullmatch(client_id) is None
            or preview_session_id is None
            or not sessions.is_session_id(preview_session_id)
        ):
            return _invalid_studio_session()

    requested_revision = request.query_params.get("revision")
    if requested_revision is None:
        snapshot = await presentation.snapshot_async(view_name)
    else:
        snapshot = presentation.snapshot_for_revision(view_name, requested_revision)
        if snapshot is None:
            return _revision_unavailable()
    if client_id is not None:
        session_id = await clients.session_for_client(client_id)
        if session_id is None:
            return _session_pending()
        if not sessions.exists(context, session_id):
            return _session_pending()
    payload = build_runtime_config(
        snapshot,
        context,
        runtimes,
        request.query_params.get("runtime"),
        session_id,
        session_id if client_id is not None else None,
    )
    if client_id is not None:
        assert preview_session_id is not None
        payload["editorSessionId"] = session_id
        runtime = payload.get("runtime")
        if (
            isinstance(runtime, dict)
            and runtime.get("id") == "server"
            and session_id is not None
            and not attachment.attach(
                context,
                preview_session_id,
                session_id,
            )
        ):
            return _session_pending(
                "Studio is waiting for an earlier preview connection to finish."
            )
    return JSONResponse(payload, headers=NO_STORE)


def _invalid_studio_session() -> JSONResponse:
    return JSONResponse(
        {
            "error": "invalid-studio-session",
            "message": "The Studio preview session context is invalid.",
        },
        status_code=400,
        headers=NO_STORE,
    )


def _session_pending(
    message: str = "The Studio editor session is still connecting.",
) -> JSONResponse:
    return JSONResponse(
        {
            "error": "runtime-sync-pending",
            "message": message,
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


__all__ = ["runtime_config_response"]
