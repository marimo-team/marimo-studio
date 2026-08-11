"""Authorize Studio mutation routes and format expected failures."""

from __future__ import annotations

from starlette.requests import Request
from starlette.responses import JSONResponse

from marimo_studio._compat.server.sessions import server_token_matches
from marimo_studio._server.headers import NO_STORE
from marimo_studio.errors import MarimoStudioError


def error_response(error: MarimoStudioError) -> JSONResponse:
    return JSONResponse(
        {
            "error": error.code,
            "message": error.public_message(),
            **error.diagnostic_details(),
        },
        status_code=error.status_code,
        headers=NO_STORE,
    )


def authentication_required_response() -> JSONResponse:
    return JSONResponse(
        {
            "error": "authentication-required",
            "message": "Authenticate with Marimo before using this route.",
        },
        status_code=401,
        headers=NO_STORE,
    )


def forbidden_response() -> JSONResponse:
    return JSONResponse(
        {
            "error": "edit-access-required",
            "message": "Open Studio from an editable Marimo session.",
        },
        status_code=403,
        headers=NO_STORE,
    )


def invalid_server_token_response(
    request: Request,
    expected: str,
) -> JSONResponse | None:
    if server_token_matches(request.scope, expected):
        return None
    missing = request.headers.get("Marimo-Server-Token") is None
    return JSONResponse(
        {
            "error": "missing-server-token" if missing else "invalid-server-token",
            "message": (
                "Marimo-Server-Token is required."
                if missing
                else "Marimo-Server-Token does not match this server."
            ),
        },
        status_code=401,
        headers=NO_STORE,
    )


__all__ = [
    "authentication_required_response",
    "error_response",
    "forbidden_response",
    "invalid_server_token_response",
]
