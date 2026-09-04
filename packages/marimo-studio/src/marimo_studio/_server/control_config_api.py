"""Serve control synchronization metadata for one Studio preview."""

from __future__ import annotations

import json
from hashlib import sha256

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from marimo_studio._delivery.urls import STUDIO_CLIENT_QUERY_PARAM
from marimo_studio._server.agent.clients import StudioClientRegistry
from marimo_studio._server.auth import forbidden_response, has_edit_access
from marimo_studio._server.headers import NO_STORE
from marimo_studio._server.ports import SessionState
from marimo_studio._server.presentation.payload import build_runtime_config
from marimo_studio._server.presentation.service import NotebookPresentation
from marimo_studio._server.records import ServerContext
from marimo_studio._server.runtime.catalog import RuntimeRegistry


async def control_config_response(
    request: Request,
    context: ServerContext,
    presentation: NotebookPresentation,
    clients: StudioClientRegistry,
    view_name: str,
    *,
    sessions: SessionState,
    runtimes: RuntimeRegistry,
) -> Response:
    if context.mode != "edit" or not has_edit_access(request.scope):
        return forbidden_response()
    client_id = request.query_params.get(STUDIO_CLIENT_QUERY_PARAM)
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
    payload = await build_runtime_config(
        snapshot,
        context,
        runtimes,
        request.query_params.get("runtime"),
        session_id,
        client_id,
        request.headers.get("Marimo-Studio-Preview-Session-Id"),
        session_id,
    )
    runtime = payload["runtime"]
    bindings = payload["runtimeBindings"]
    runtime_id = runtime.get("id") if isinstance(runtime, dict) else None
    controls = bindings if isinstance(bindings, dict) else {"cellRefs": {}}
    encoded = json.dumps(
        [snapshot.revision, runtime_id, controls],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    etag = f'"{sha256(encoded).hexdigest()}"'
    headers = {**NO_STORE, "ETag": etag}
    if request.headers.get("If-None-Match") == etag:
        return Response(status_code=304, headers=headers)
    return JSONResponse(
        {
            "schema": 1,
            "revision": snapshot.revision,
            "runtime": runtime_id,
            "controls": controls,
        },
        headers=headers,
    )


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
