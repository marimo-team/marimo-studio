"""Read bounded request bodies for Studio-owned routes."""

from __future__ import annotations

import json
from typing import Any

from starlette.requests import ClientDisconnect, Request
from starlette.responses import JSONResponse, Response

from marimo_studio._server.headers import NO_STORE


class BoundedBodyError(ValueError):
    """A bounded request body cannot be collected."""


class BoundedBodyTooLarge(BoundedBodyError):
    """A request body exceeds its route budget."""


class InvalidContentLength(BoundedBodyError):
    """Content-Length is invalid or disagrees with the received bytes."""


class BoundedBodyDisconnected(BoundedBodyError):
    """The request stream ended before a complete terminal body event."""


class JSONBodyError(ValueError):
    """A JSON request body cannot be accepted."""


class JSONBodyTooLarge(JSONBodyError):
    """A JSON request body exceeds its route budget."""


class InvalidJSONBody(JSONBodyError):
    """A request body is not one complete UTF-8 JSON value."""


class JSONBodyDisconnected(JSONBodyError):
    """The request stream ended before a complete terminal JSON body."""


def _declared_content_length(request: Request) -> int | None:
    values = [
        value
        for name, value in request.scope.get("headers", ())
        if name.lower() == b"content-length"
    ]
    if not values:
        return None
    if len(values) != 1:
        raise InvalidContentLength("Content-Length must appear exactly once")
    value = values[0].strip()
    if not value or not value.isdigit():
        raise InvalidContentLength(
            "Content-Length must be one non-negative decimal integer"
        )
    try:
        return int(value)
    except ValueError as error:
        raise InvalidContentLength("Content-Length is too large to parse") from error


async def read_bounded_body(request: Request, *, max_bytes: int) -> bytes:
    """Collect one bounded body and verify its declared terminal length."""
    if type(max_bytes) is not int or max_bytes < 1:
        raise ValueError("Body limit must be a positive integer")
    declared_size = _declared_content_length(request)
    if declared_size is not None and declared_size > max_bytes:
        raise BoundedBodyTooLarge
    payload = bytearray()
    try:
        async for chunk in request.stream():
            next_size = len(payload) + len(chunk)
            if declared_size is not None and next_size > declared_size:
                raise InvalidContentLength(
                    "Request body exceeds its declared Content-Length"
                )
            if next_size > max_bytes:
                raise BoundedBodyTooLarge
            payload.extend(chunk)
    except ClientDisconnect as error:
        raise BoundedBodyDisconnected from error
    if declared_size is not None and len(payload) != declared_size:
        raise BoundedBodyDisconnected
    return bytes(payload)


async def read_json_body(request: Request, *, max_bytes: int) -> Any:
    """Parse one JSON value after collecting at most ``max_bytes`` bytes."""
    try:
        payload = await read_bounded_body(request, max_bytes=max_bytes)
    except BoundedBodyTooLarge as error:
        raise JSONBodyTooLarge from error
    except InvalidContentLength as error:
        raise InvalidJSONBody(str(error)) from error
    except BoundedBodyDisconnected as error:
        raise JSONBodyDisconnected from error
    try:
        source = payload.decode("utf-8")
        return json.loads(source)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise InvalidJSONBody from error


def json_body_error_response(error: JSONBodyError) -> Response:
    """Return the shared malformed or oversized JSON response."""
    if isinstance(error, JSONBodyDisconnected):
        return Response(status_code=499, headers=NO_STORE)
    if isinstance(error, JSONBodyTooLarge):
        return JSONResponse(
            {
                "error": "request-body-too-large",
                "message": "The JSON request body exceeds this route's byte limit.",
            },
            status_code=413,
            headers=NO_STORE,
        )
    return JSONResponse(
        {
            "error": "invalid-json",
            "message": "The request body must contain one UTF-8 JSON value.",
        },
        status_code=400,
        headers=NO_STORE,
    )


def bounded_body_error_response(error: BoundedBodyError) -> Response:
    """Return the shared response for a bounded raw request body failure."""
    if isinstance(error, BoundedBodyDisconnected):
        return Response(status_code=499, headers=NO_STORE)
    if isinstance(error, BoundedBodyTooLarge):
        return JSONResponse(
            {
                "error": "request-body-too-large",
                "message": "The request body exceeds this route's byte limit.",
            },
            status_code=413,
            headers=NO_STORE,
        )
    return JSONResponse(
        {
            "error": "invalid-request-body",
            "message": "The request body length is invalid.",
        },
        status_code=400,
        headers=NO_STORE,
    )
