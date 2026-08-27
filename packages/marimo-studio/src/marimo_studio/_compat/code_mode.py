"""Read the callback connection from a Marimo code-mode request."""

from __future__ import annotations

from pathlib import Path

from starlette.datastructures import Headers
from starlette.types import Scope

from marimo_studio._browser_client.transport import StudioServerConnection
from marimo_studio.errors import ProtocolError

STUDIO_SESSION_ID_KEY = "marimo_studio_session_id"
STUDIO_NOTEBOOK_PATH_KEY = "marimo_studio_notebook_path"


def attach_code_mode_session(scope: Scope, notebook: Path) -> Scope:
    """Attach the calling Marimo session to a code-mode request scope."""
    updated = dict(scope)
    raw_meta = scope.get("meta")
    meta = dict(raw_meta) if isinstance(raw_meta, dict) else {}
    session_id = Headers(raw=list(scope.get("headers", []))).get("Marimo-Session-Id")
    if session_id:
        meta[STUDIO_SESSION_ID_KEY] = session_id
    meta[STUDIO_NOTEBOOK_PATH_KEY] = str(notebook.resolve())
    updated["meta"] = meta
    return updated


def active_notebook() -> Path:
    """Return the saved notebook attached to the active code-mode request."""
    from marimo._messaging.context import HTTP_REQUEST_CTX

    request = HTTP_REQUEST_CTX.get(None)
    if request is None:
        raise ProtocolError(
            "Studio operations require an active Marimo code-mode request."
        )
    value = request.meta.get(STUDIO_NOTEBOOK_PATH_KEY)
    if not isinstance(value, str) or not value:
        raise ProtocolError("The active Marimo notebook path is unavailable.")
    notebook = Path(value).expanduser().resolve()
    if not notebook.is_file():
        raise ProtocolError(f"The active Marimo notebook is unavailable: {notebook}")
    return notebook


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
    session_id = request.meta.get(STUDIO_SESSION_ID_KEY)
    if not isinstance(server_url, str) or not server_url:
        raise ProtocolError("The Marimo server callback URL is unavailable.")
    if not isinstance(auth_token, str):
        raise ProtocolError("The Marimo server callback token is unavailable.")
    if not isinstance(session_id, str) or not session_id:
        raise ProtocolError("The Marimo session identifier is unavailable.")
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
        session_id=session_id,
    )
