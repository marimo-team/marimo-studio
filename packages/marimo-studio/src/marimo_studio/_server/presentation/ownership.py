"""Distinguish Studio-owned frames from direct presentation clients."""

from __future__ import annotations

from starlette.requests import Request

from marimo_studio._delivery.urls import (
    DOCUMENT_LIFECYCLE_QUERY_PARAM,
    STUDIO_CLIENT_QUERY_PARAM,
)

_MAX_SAFE_INTEGER = 9_007_199_254_740_991


def studio_frame_identity(request: Request) -> tuple[str, int] | None:
    """Return one exact Studio client and bounded document lifecycle pair."""
    client_ids = request.query_params.getlist(STUDIO_CLIENT_QUERY_PARAM)
    lifecycles = request.query_params.getlist(DOCUMENT_LIFECYCLE_QUERY_PARAM)
    if len(client_ids) != 1 or not client_ids[0] or len(lifecycles) != 1:
        return None
    lifecycle = lifecycles[0]
    if not lifecycle.isdecimal():
        return None
    lifecycle_id = int(lifecycle)
    return (
        (client_ids[0], lifecycle_id) if 0 < lifecycle_id <= _MAX_SAFE_INTEGER else None
    )


def studio_owned_request(request: Request) -> bool:
    """Return whether the request carries one bounded Studio frame identity."""
    return studio_frame_identity(request) is not None
