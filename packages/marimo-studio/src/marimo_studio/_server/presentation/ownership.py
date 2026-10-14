"""Distinguish Studio-owned frames from direct presentation clients."""

from __future__ import annotations

from starlette.requests import Request

from marimo_studio._delivery.urls import (
    DOCUMENT_LIFECYCLE_QUERY_PARAM,
    STUDIO_CLIENT_QUERY_PARAM,
)
from marimo_studio._server.query import positive_safe_integer


def studio_frame_identity(request: Request) -> tuple[str, int] | None:
    """Return one exact Studio client and bounded document lifecycle pair."""
    client_ids = request.query_params.getlist(STUDIO_CLIENT_QUERY_PARAM)
    lifecycles = request.query_params.getlist(DOCUMENT_LIFECYCLE_QUERY_PARAM)
    if len(client_ids) != 1 or not client_ids[0] or len(lifecycles) != 1:
        return None
    lifecycle_id = positive_safe_integer(lifecycles[0])
    return (client_ids[0], lifecycle_id) if lifecycle_id is not None else None


def studio_owned_request(request: Request) -> bool:
    """Return whether the request carries one bounded Studio frame identity."""
    return studio_frame_identity(request) is not None
