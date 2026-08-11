"""Serve live value and rich output projection requests."""

from __future__ import annotations

import json
from typing import cast

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from marimo_studio._capabilities import (
    KernelProjectionHost,
    ProjectionUnavailable,
    ServerContext,
)
from marimo_studio._server.headers import NO_STORE
from marimo_studio._server.presentation import NotebookPresentation
from marimo_studio.values import MAX_OUTPUT_SELECTORS


async def values_response(
    request: Request,
    context: ServerContext,
    presentation: NotebookPresentation,
    view_name: str,
    projections: KernelProjectionHost,
) -> Response:
    body = await _json_body(request)
    revision = body.get("revision") if isinstance(body, dict) else None
    selectors = body.get("selectors") if isinstance(body, dict) else None
    if (
        not isinstance(revision, str)
        or not revision
        or not isinstance(selectors, list)
        or len(selectors) > 100
        or not all(isinstance(selector, str) for selector in selectors)
    ):
        return JSONResponse(
            {
                "error": "invalid-value-request",
                "message": (
                    "revision must be a non-empty string and selectors must be "
                    "an array of at most 100 strings."
                ),
            },
            status_code=400,
            headers=NO_STORE,
        )
    snapshot = presentation.snapshot_for_revision(view_name, revision)
    if snapshot is None:
        return _revision_unavailable()
    view = snapshot.resolved.views[view_name]
    requested = tuple(dict.fromkeys(cast(list[str], selectors)))
    unknown = sorted(set(requested).difference(view.value_bindings))
    if unknown:
        return JSONResponse(
            {
                "error": "unknown-selector",
                "message": f"Unknown selectors: {', '.join(unknown)}.",
            },
            status_code=400,
            headers=NO_STORE,
        )
    session_id = request.headers.get("Marimo-Session-Id")
    if not session_id:
        return _session_unavailable(session_id)
    try:
        result = await projections.read_values(
            context,
            session_id,
            requested,
            consumer_id=session_id,
        )
    except ProjectionUnavailable as error:
        return _value_error(error)
    return JSONResponse(result.to_dict(), headers=NO_STORE)


async def outputs_response(
    request: Request,
    context: ServerContext,
    presentation: NotebookPresentation,
    view_name: str,
    projections: KernelProjectionHost,
) -> Response:
    body = await _json_body(request)
    revision = body.get("revision") if isinstance(body, dict) else None
    selectors = body.get("selectors") if isinstance(body, dict) else None
    active_selectors = body.get("activeSelectors") if isinstance(body, dict) else None
    if (
        not isinstance(revision, str)
        or not revision
        or not isinstance(selectors, list)
        or len(selectors) > MAX_OUTPUT_SELECTORS
        or not all(isinstance(selector, str) for selector in selectors)
        or not isinstance(active_selectors, list)
        or len(active_selectors) > MAX_OUTPUT_SELECTORS
        or not all(isinstance(selector, str) for selector in active_selectors)
    ):
        return JSONResponse(
            {
                "error": "invalid-output-request",
                "message": (
                    "revision must be a non-empty string, and selectors and "
                    "activeSelectors must be arrays of at most "
                    f"{MAX_OUTPUT_SELECTORS} strings."
                ),
            },
            status_code=400,
            headers=NO_STORE,
        )
    snapshot = presentation.snapshot_for_revision(view_name, revision)
    if snapshot is None:
        return _revision_unavailable()
    view = snapshot.resolved.views[view_name]
    requested = tuple(dict.fromkeys(cast(list[str], selectors)))
    active = tuple(dict.fromkeys(cast(list[str], active_selectors)))
    unknown = sorted(set((*requested, *active)).difference(view.output_bindings))
    if unknown:
        return JSONResponse(
            {
                "error": "unknown-selector",
                "message": f"Unknown output selectors: {', '.join(unknown)}.",
            },
            status_code=400,
            headers=NO_STORE,
        )
    if not set(requested).issubset(active):
        return JSONResponse(
            {
                "error": "invalid-output-request",
                "message": "Every requested selector must also be active.",
            },
            status_code=400,
            headers=NO_STORE,
        )
    session_id = request.headers.get("Marimo-Session-Id")
    if not session_id:
        return _session_unavailable(session_id)
    try:
        result = await projections.render_outputs(
            context,
            session_id,
            requested,
            active,
            consumer_id=session_id,
        )
    except ProjectionUnavailable as error:
        return _value_error(error)
    return JSONResponse(result.to_dict(), headers=NO_STORE)


async def _json_body(request: Request) -> object:
    try:
        return await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None


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


__all__ = ["outputs_response", "values_response"]
