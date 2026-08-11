"""Synchronize public view query state into one Studio editor session."""

from __future__ import annotations

import json
import re
from urllib.parse import parse_qs

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from marimo_studio._capabilities import (
    KernelProjectionHost,
    QuerySyncUnavailable,
    ServerContext,
    SessionState,
)
from marimo_studio._server.auth import (
    forbidden_response,
    has_edit_access,
    invalid_server_token_response,
)
from marimo_studio._server.headers import NO_STORE
from marimo_studio._server.live_clients import StudioClientRegistry
from marimo_studio._urls import PRIVATE_QUERY_KEYS

_QUERY_OPERATION_PATTERN = re.compile(r"[A-Za-z0-9_-]{1,128}")


async def query_response(
    request: Request,
    context: ServerContext,
    clients: StudioClientRegistry,
    sessions: SessionState,
    projections: KernelProjectionHost,
) -> Response:
    if context.mode != "edit" or not has_edit_access(request.scope):
        return forbidden_response()
    if token_error := invalid_server_token_response(request, context.server_token):
        return token_error
    body = await _json_body(request)
    query = body.get("query") if isinstance(body, dict) else None
    client_id = body.get("clientId") if isinstance(body, dict) else None
    operation_id = body.get("operationId") if isinstance(body, dict) else None
    if (
        not isinstance(body, dict)
        or set(body) != {"clientId", "operationId", "query"}
        or not isinstance(query, str)
        or len(query) > 16_384
        or not isinstance(client_id, str)
        or not client_id
        or not isinstance(operation_id, str)
        or _QUERY_OPERATION_PATTERN.fullmatch(operation_id) is None
    ):
        return JSONResponse(
            {
                "error": "invalid-query",
                "message": (
                    "clientId and operationId must be non-empty identifiers, "
                    "and query must be a string of at most 16384 characters."
                ),
            },
            status_code=400,
            headers=NO_STORE,
        )
    try:
        parsed = parse_qs(
            query.removeprefix("?"),
            keep_blank_values=True,
            max_num_fields=100,
        )
    except ValueError:
        return JSONResponse(
            {
                "error": "invalid-query",
                "message": "query may contain at most 100 fields.",
            },
            status_code=400,
            headers=NO_STORE,
        )
    values = {
        key: items[0] if len(items) == 1 else items for key, items in parsed.items()
    }
    if set(values).intersection(PRIVATE_QUERY_KEYS):
        return JSONResponse(
            {
                "error": "invalid-query",
                "message": "query contains a private Studio routing key.",
            },
            status_code=400,
            headers=NO_STORE,
        )
    session_id = await clients.session_for_client(client_id)
    if session_id is None or not sessions.exists(context, session_id):
        return _session_unavailable()
    claimed = await clients.claim_query_operation(
        client_id,
        operation_id,
        session_id,
    )
    if claimed is None:
        return _session_unavailable()
    if not claimed:
        return Response(status_code=202, headers=NO_STORE)
    try:
        projections.sync_query(context, session_id, values, operation_id)
    except QuerySyncUnavailable as error:
        await clients.release_query_operation(client_id, operation_id)
        return JSONResponse(
            {
                "error": "query-sync-unavailable",
                "message": str(error),
                "transient": True,
            },
            status_code=409,
            headers=NO_STORE,
        )
    return Response(status_code=202, headers=NO_STORE)


async def _json_body(request: Request) -> object:
    try:
        return await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None


def _session_unavailable() -> JSONResponse:
    return JSONResponse(
        {
            "error": "query-session-unavailable",
            "message": "The Studio editor session is still connecting.",
            "transient": True,
        },
        status_code=409,
        headers=NO_STORE,
    )


__all__ = ["query_response"]
