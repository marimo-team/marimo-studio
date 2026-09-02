"""Synchronize public view query state into one Studio editor session."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable
from urllib.parse import parse_qs

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from marimo_studio._delivery.urls import PRIVATE_QUERY_KEYS
from marimo_studio._processes.ownership import (
    propagate_cancellation,
    settle_ownership,
)
from marimo_studio._server.agent.clients import (
    QueryOperationClaim,
    QueryOperationStatus,
    StudioClientRegistry,
)
from marimo_studio._server.auth import (
    forbidden_response,
    has_edit_access,
    invalid_server_token_response,
)
from marimo_studio._server.headers import NO_STORE
from marimo_studio._server.ports import SessionState
from marimo_studio._server.presentation.ports import (
    KernelProjectionHost,
    QuerySyncUnavailable,
)
from marimo_studio._server.presentation.query_state import (
    query_fingerprint,
    valid_query_operation_id,
)
from marimo_studio._server.records import ServerContext
from marimo_studio._server.request_body import (
    JSONBodyError,
    json_body_error_response,
    read_json_body,
)

_QUERY_JSON_MAX_BYTES = 32 * 1024
_QUERY_COMMAND_TTL_SECONDS = 5.0


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
    try:
        body = await read_json_body(request, max_bytes=_QUERY_JSON_MAX_BYTES)
    except JSONBodyError as error:
        return json_body_error_response(error)
    query = body.get("query") if isinstance(body, dict) else None
    client_id = body.get("clientId") if isinstance(body, dict) else None
    operation_id = body.get("operationId") if isinstance(body, dict) else None
    query_generation = body.get("writeGeneration") if isinstance(body, dict) else None
    if (
        not isinstance(body, dict)
        or set(body) != {"clientId", "operationId", "query", "writeGeneration"}
        or not isinstance(query, str)
        or len(query) > 16_384
        or not isinstance(client_id, str)
        or not client_id
        or not isinstance(operation_id, str)
        or not valid_query_operation_id(operation_id)
        or isinstance(query_generation, bool)
        or not isinstance(query_generation, int)
        or query_generation < 0
        or query_generation > 9_007_199_254_740_991
    ):
        return JSONResponse(
            {
                "error": "invalid-query",
                "message": (
                    "clientId and operationId must be non-empty identifiers, "
                    "writeGeneration must be a non-negative safe integer, "
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
    fingerprint = query_fingerprint(values)
    session_id = await clients.session_for_client(client_id)
    if session_id is None or not sessions.exists(context, session_id):
        return _session_unavailable()
    claim = await clients.claim_query_operation(
        client_id,
        operation_id,
        session_id,
        fingerprint,
        query_generation,
    )
    if claim is None:
        return _session_unavailable()
    if claim.status in {
        QueryOperationStatus.COMMITTED,
        QueryOperationStatus.SUPERSEDED,
    }:
        return Response(status_code=202, headers=NO_STORE)
    if claim.status is QueryOperationStatus.PENDING:
        return JSONResponse(
            {
                "error": "query-operation-pending",
                "message": "The matching query operation is still being applied.",
                "transient": True,
            },
            status_code=409,
            headers=NO_STORE,
        )
    if claim.status is QueryOperationStatus.CONFLICT:
        return JSONResponse(
            {
                "error": "query-operation-conflict",
                "message": "The query operation ID was already used for another query.",
                "transient": False,
            },
            status_code=409,
            headers=NO_STORE,
        )
    committed = False
    mutation_acquired = False
    mutation_deferred = False
    mutation_cancellation: asyncio.CancelledError | None = None
    command_deadline = time.monotonic() + _QUERY_COMMAND_TTL_SECONDS
    try:
        mutation_acquired = await clients.acquire_query_mutation(claim)
        if not mutation_acquired:
            return _session_unavailable()
        committed, mutation_cancellation, failure = await _settle_query_application(
            _apply_query_operation(
                context,
                clients,
                projections,
                session_id,
                values,
                claim,
                command_deadline,
            )
        )
        if failure is not None:
            raise failure
    except QuerySyncUnavailable as error:
        if mutation_acquired and error.terminal is not None:
            clients.defer_query_mutation(
                claim,
                error.terminal,
            )
            mutation_deferred = True
            mutation_acquired = False
        return JSONResponse(
            {
                "error": "query-sync-unavailable",
                "message": str(error),
                "transient": True,
            },
            status_code=409,
            headers=NO_STORE,
        )
    finally:
        _released, cancellation = await settle_ownership(
            _finish_query_operation(
                clients,
                claim,
                committed=committed,
                deferred=mutation_deferred,
                mutation_acquired=mutation_acquired,
            )
        )
        propagate_cancellation(mutation_cancellation or cancellation)
    return (
        Response(status_code=202, headers=NO_STORE)
        if committed
        else _session_unavailable()
    )


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


async def _finish_query_operation(
    clients: StudioClientRegistry,
    claim: QueryOperationClaim,
    *,
    committed: bool,
    deferred: bool,
    mutation_acquired: bool,
) -> None:
    try:
        if not committed and not deferred:
            await clients.release_query_operation(claim)
    finally:
        if mutation_acquired:
            await clients.finish_query_mutation(claim)


async def _apply_query_operation(
    context: ServerContext,
    clients: StudioClientRegistry,
    projections: KernelProjectionHost,
    session_id: str,
    query: dict[str, str | list[str]],
    claim: QueryOperationClaim,
    command_deadline: float,
) -> bool:
    await projections.sync_query(
        context,
        session_id,
        query,
        claim.operation_id,
        binding_generation=claim.binding_generation,
        query_generation=claim.query_generation,
        deadline=command_deadline,
    )
    return await clients.commit_query_operation(claim)


async def _settle_query_application(
    operation: Awaitable[bool],
) -> tuple[bool, asyncio.CancelledError | None, BaseException | None]:
    task = asyncio.ensure_future(operation)
    cancellation: asyncio.CancelledError | None = None
    while True:
        try:
            return await asyncio.shield(task), cancellation, None
        except asyncio.CancelledError as error:
            if task.cancelled():
                raise
            if cancellation is None:
                cancellation = error
        except BaseException as error:
            return False, cancellation, error
