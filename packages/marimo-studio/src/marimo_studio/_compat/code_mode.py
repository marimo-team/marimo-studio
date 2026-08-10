"""Read trusted callback credentials from a Marimo code-mode request."""

from __future__ import annotations

from marimo_studio._agent_client import StudioServerConnection
from marimo_studio.errors import ProtocolError


def code_mode_connection() -> StudioServerConnection:
    """Return the running server connection attached to code mode."""
    from marimo._code_mode.screenshot_meta import (
        SCREENSHOT_AUTH_TOKEN_KEY,
        SCREENSHOT_SERVER_URL_KEY,
    )
    from marimo._messaging.context import HTTP_REQUEST_CTX

    request = HTTP_REQUEST_CTX.get(None)
    if request is None:
        raise ProtocolError(
            "Studio browser operations require an active Marimo code-mode request."
        )
    server_url = request.meta.get(SCREENSHOT_SERVER_URL_KEY)
    auth_token = request.meta.get(SCREENSHOT_AUTH_TOKEN_KEY)
    if not isinstance(server_url, str) or not server_url:
        raise ProtocolError("The Marimo server callback URL is unavailable.")
    if not isinstance(auth_token, str):
        raise ProtocolError("The Marimo server callback token is unavailable.")
    routing_query = tuple(
        (key, item)
        for key in ("file",)
        for item in request.query_params.get(key, [])
        if isinstance(item, str)
    )
    return StudioServerConnection(
        server_url=server_url,
        auth_token=auth_token,
        routing_query=routing_query,
    )


__all__ = ["code_mode_connection"]
