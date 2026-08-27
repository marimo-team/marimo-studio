"""Authorize Studio mutation routes and format expected failures."""

from __future__ import annotations

import hmac
from urllib.parse import parse_qs

from starlette.datastructures import Headers
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import Scope

from marimo_studio._server.headers import NO_STORE
from marimo_studio.errors import MarimoStudioError


def server_token_matches(scope: Scope, expected: str) -> bool:
    """Validate Marimo's server token for a Studio mutation route."""
    supplied = Headers(scope=scope).get("Marimo-Server-Token")
    return supplied is not None and hmac.compare_digest(supplied, expected)


def has_read_access(scope: Scope) -> bool:
    auth = scope.get("auth")
    return "read" in getattr(auth, "scopes", ())


def has_edit_access(scope: Scope) -> bool:
    auth = scope.get("auth")
    return "edit" in getattr(auth, "scopes", ())


def has_access_token(scope: Scope) -> bool:
    raw = scope.get("query_string", b"")
    query = parse_qs(bytes(raw).decode("latin-1"), keep_blank_values=True)
    return "access_token" in query


def error_response(error: MarimoStudioError) -> JSONResponse:
    return JSONResponse(
        {
            "error": error.code,
            "message": error.public_message(),
            **error.diagnostic_details(),
            **({"hint": error.public_hint} if error.public_hint else {}),
            **({"transient": True} if error.transient else {}),
        },
        status_code=error.status_code,
        headers={**NO_STORE, "Marimo-Studio-Error": error.code},
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
