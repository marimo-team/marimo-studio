"""Serve live value and rich output projection requests."""

from __future__ import annotations

from collections.abc import Mapping

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from marimo_studio._notebook.records import CellRef
from marimo_studio._projections.resolution import (
    MAX_ACTIVE_PROJECTION_INSTANCES,
    MAX_UNIQUE_VALUE_TARGETS,
    ProjectionRequest,
    ProjectionResolutionError,
    ResolvedProjection,
    resolve_projection,
)
from marimo_studio._projections.runtime_records import ValueReadError
from marimo_studio._projections.values import MAX_OUTPUT_SELECTORS
from marimo_studio._server.headers import NO_STORE
from marimo_studio._server.ports import SessionState
from marimo_studio._server.presentation.ports import (
    STALE_PROJECTION_BINDING_CODE,
    KernelProjectionHost,
    ProjectionUnavailable,
)
from marimo_studio._server.presentation.service import (
    NotebookPresentation,
    PresentationSnapshot,
)
from marimo_studio._server.records import ServerContext
from marimo_studio._server.request_body import (
    JSONBodyError,
    json_body_error_response,
    read_json_body,
)
from marimo_studio.errors._internal import RuntimeSyncError
from marimo_studio.view_providers import ProjectionKind

_PROJECTION_JSON_MAX_BYTES = 2 * 1024 * 1024


async def values_response(
    request: Request,
    context: ServerContext,
    presentation: NotebookPresentation,
    view_name: str,
    projections: KernelProjectionHost,
    sessions: SessionState,
    authorized_revision: str | None = None,
) -> Response:
    try:
        body = await read_json_body(request, max_bytes=_PROJECTION_JSON_MAX_BYTES)
    except JSONBodyError as error:
        return json_body_error_response(error)
    revision = body.get("revision") if isinstance(body, dict) else None
    projections_value = body.get("projections") if isinstance(body, dict) else None
    active_value = body.get("activeProjections") if isinstance(body, dict) else None
    if (
        not isinstance(body, dict)
        or set(body) != {"revision", "projections", "activeProjections"}
        or not isinstance(revision, str)
        or not revision
        or not isinstance(projections_value, list)
        or len(projections_value) > MAX_ACTIVE_PROJECTION_INSTANCES
        or not isinstance(active_value, list)
        or len(active_value) > MAX_ACTIVE_PROJECTION_INSTANCES
    ):
        return JSONResponse(
            {
                "error": "invalid-value-request",
                "message": (
                    "revision must be a non-empty string, and projections and "
                    "activeProjections must be arrays within the active projection "
                    "instance limit."
                ),
            },
            status_code=400,
            headers=NO_STORE,
        )
    if authorized_revision is not None and revision != authorized_revision:
        return _capability_revision_forbidden()
    snapshot = presentation.snapshot_for_revision(view_name, revision)
    if snapshot is None:
        return _revision_unavailable()
    try:
        requested = _resolve_requests(snapshot, projections_value, kind="value")
        active = _resolve_requests(snapshot, active_value, kind="value")
    except ProjectionResolutionError as error:
        return _resolution_error(error)
    active_requests = {item.request for item in active}
    if not all(item.request in active_requests for item in requested):
        return JSONResponse(
            {
                "error": "invalid-value-request",
                "message": "Every requested projection must also be active.",
            },
            status_code=400,
            headers=NO_STORE,
        )
    if len({item.request.target for item in active}) > MAX_UNIQUE_VALUE_TARGETS:
        return JSONResponse(
            {
                "error": "too-many-value-targets",
                "message": (
                    "A value request may contain at most "
                    f"{MAX_UNIQUE_VALUE_TARGETS} unique targets."
                ),
            },
            status_code=400,
            headers=NO_STORE,
        )
    session_id = request.headers.get("Marimo-Session-Id")
    if not session_id:
        return _session_unavailable(session_id)
    if sessions.ownership(context, session_id) == "foreign":
        return _session_unavailable(session_id)
    try:
        runtime_cell_refs = _runtime_cell_refs(snapshot, context, session_id, sessions)
    except RuntimeSyncError as error:
        return _runtime_sync_pending(error)
    try:
        result = await projections.read_values(
            context,
            session_id,
            snapshot.revision,
            requested,
            active,
            consumer_id=session_id,
            runtime_cell_refs=runtime_cell_refs,
        )
    except ProjectionUnavailable as error:
        return _value_error(error)
    if stale := _stale_binding_error(result.errors):
        return stale
    return JSONResponse(result.to_dict(), headers=NO_STORE)


async def outputs_response(
    request: Request,
    context: ServerContext,
    presentation: NotebookPresentation,
    view_name: str,
    projections: KernelProjectionHost,
    sessions: SessionState,
    authorized_revision: str | None = None,
) -> Response:
    try:
        body = await read_json_body(request, max_bytes=_PROJECTION_JSON_MAX_BYTES)
    except JSONBodyError as error:
        return json_body_error_response(error)
    revision = body.get("revision") if isinstance(body, dict) else None
    projections_value = body.get("projections") if isinstance(body, dict) else None
    active_value = body.get("activeProjections") if isinstance(body, dict) else None
    if (
        not isinstance(body, dict)
        or set(body) != {"revision", "projections", "activeProjections"}
        or not isinstance(revision, str)
        or not revision
        or not isinstance(projections_value, list)
        or len(projections_value) > MAX_OUTPUT_SELECTORS
        or not isinstance(active_value, list)
        or len(active_value) > MAX_OUTPUT_SELECTORS
    ):
        return JSONResponse(
            {
                "error": "invalid-output-request",
                "message": (
                    "revision must be a non-empty string, and projections and "
                    "activeProjections must be arrays of at most "
                    f"{MAX_OUTPUT_SELECTORS} projection requests."
                ),
            },
            status_code=400,
            headers=NO_STORE,
        )
    if authorized_revision is not None and revision != authorized_revision:
        return _capability_revision_forbidden()
    snapshot = presentation.snapshot_for_revision(view_name, revision)
    if snapshot is None:
        return _revision_unavailable()
    try:
        requested = _resolve_requests(snapshot, projections_value, kind="output")
        active = _resolve_requests(snapshot, active_value, kind="output")
    except ProjectionResolutionError as error:
        return _resolution_error(error)
    active_requests = {item.request for item in active}
    if not all(item.request in active_requests for item in requested):
        return JSONResponse(
            {
                "error": "invalid-output-request",
                "message": "Every requested projection must also be active.",
            },
            status_code=400,
            headers=NO_STORE,
        )
    session_id = request.headers.get("Marimo-Session-Id")
    if not session_id:
        return _session_unavailable(session_id)
    if sessions.ownership(context, session_id) == "foreign":
        return _session_unavailable(session_id)
    try:
        runtime_cell_refs = _runtime_cell_refs(snapshot, context, session_id, sessions)
    except RuntimeSyncError as error:
        return _runtime_sync_pending(error)
    try:
        result = await projections.render_outputs(
            context,
            session_id,
            snapshot.revision,
            requested,
            active,
            consumer_id=session_id,
            runtime_cell_refs=runtime_cell_refs,
        )
    except ProjectionUnavailable as error:
        return _value_error(error)
    if stale := _stale_binding_error(result.errors):
        return stale
    return JSONResponse(result.to_dict(), headers=NO_STORE)


def _resolve_requests(
    snapshot: PresentationSnapshot,
    values: list[object],
    *,
    kind: ProjectionKind,
) -> tuple[ResolvedProjection, ...]:
    requests = tuple(
        ProjectionRequest.from_dict(
            item,
        )
        for item in values
    )
    instance_ids = [request.instance_id for request in requests]
    if len(instance_ids) != len(set(instance_ids)):
        raise ProjectionResolutionError(
            "duplicate-projection-instance",
            "Projection instance IDs must be unique within one request.",
        )
    resolved = tuple(
        resolve_projection(
            snapshot.symbols,
            snapshot.mounts,
            request,
        )
        for request in requests
    )
    if any(item.kind != kind for item in resolved):
        raise ProjectionResolutionError(
            "projection-kind-mismatch",
            f"This endpoint accepts {kind} projections.",
        )
    if kind == "output":
        targets = [item.request.target for item in resolved]
        if len(targets) != len(set(targets)):
            raise ProjectionResolutionError(
                "duplicate-output-owner",
                "One presentation may mount one owner for each output target.",
            )
    return resolved


def _runtime_cell_refs(
    snapshot: PresentationSnapshot,
    context: ServerContext,
    session_id: str,
    sessions: SessionState,
) -> dict[CellRef, str]:
    live_cells = sessions.live_cells(context, session_id)
    return {
        CellRef.parse(reference): runtime_id
        for reference, runtime_id in snapshot.resolved.runtime_cell_refs(
            live_cells
        ).items()
    }


def _resolution_error(error: ProjectionResolutionError) -> JSONResponse:
    return JSONResponse(
        {"error": error.code, "message": str(error)},
        status_code=400,
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


def _capability_revision_forbidden() -> JSONResponse:
    return JSONResponse(
        {
            "error": "presentation-capability-forbidden",
            "message": "The presentation cannot use another published revision.",
        },
        status_code=403,
        headers=NO_STORE,
    )


def _session_unavailable(session_id: str | None) -> JSONResponse:
    if not session_id:
        return JSONResponse(
            {
                "error": "missing-session",
                "message": "Marimo-Session-Id is required.",
                "transient": True,
            },
            status_code=409,
            headers=NO_STORE,
        )
    return JSONResponse(
        {
            "error": "unknown-session",
            "message": "The Marimo session is still connecting.",
            "transient": True,
        },
        status_code=409,
        headers=NO_STORE,
    )


def _runtime_sync_pending(error: RuntimeSyncError) -> JSONResponse:
    return JSONResponse(
        {
            "error": error.code,
            "message": str(error),
            "transient": True,
        },
        status_code=error.status_code,
        headers=NO_STORE,
    )


def _value_error(error: ProjectionUnavailable) -> JSONResponse:
    return JSONResponse(
        {
            "error": error.code,
            "message": str(error),
            "transient": error.transient,
        },
        status_code=error.status_code,
        headers=NO_STORE,
    )


def _stale_binding_error(
    errors: Mapping[str, ValueReadError],
) -> JSONResponse | None:
    for error in errors.values():
        if error.code == STALE_PROJECTION_BINDING_CODE:
            return JSONResponse(
                {
                    "error": STALE_PROJECTION_BINDING_CODE,
                    "message": error.message,
                    "transient": True,
                },
                status_code=409,
                headers=NO_STORE,
            )
    return None
