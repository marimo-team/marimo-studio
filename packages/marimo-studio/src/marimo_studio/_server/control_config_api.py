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
from marimo_studio._server.presentation.service import NotebookPresentation
from marimo_studio._server.records import ServerContext
from marimo_studio.errors._internal import RuntimeSyncError


async def control_config_response(
    request: Request,
    context: ServerContext,
    presentation: NotebookPresentation,
    clients: StudioClientRegistry,
    view_name: str,
    *,
    sessions: SessionState,
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
    try:
        cells = await sessions.live_cells(
            context, session_id, include_dependency_closures=False
        )
        bindings = await sessions.control_bindings(context, session_id)
    except RuntimeSyncError:
        return _session_pending()
    if await clients.session_for_client(client_id) != session_id:
        return _session_pending()
    controls = {
        "cells": snapshot.resolved.runtime_cell_refs(cells),
        "bindings": bindings,
    }
    encoded = json.dumps(
        [snapshot.revision, controls],
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
