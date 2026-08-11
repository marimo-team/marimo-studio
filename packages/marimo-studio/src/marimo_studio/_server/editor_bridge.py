"""Delegate native editor traffic while attaching Studio session context."""

from __future__ import annotations

import re
from pathlib import Path

from starlette.requests import HTTPConnection, Request
from starlette.types import ASGIApp, Receive, Scope, Send
from starlette.websockets import WebSocket

from marimo_studio._compat.code_mode import attach_code_mode_session
from marimo_studio._compat.server.cell_aliases import enable_cell_alias_sync
from marimo_studio._compat.server.context import server_location
from marimo_studio._compat.server.sessions import has_edit_access, is_session_id
from marimo_studio._server.notebook_scope import NotebookScopeRegistry
from marimo_studio._server.routing import native_editor_target
from marimo_studio._urls import STUDIO_CLIENT_QUERY_PARAM
from marimo_studio._workspace import discover_studio
from marimo_studio.errors import MarimoStudioError

_CODE_MODE_ROUTES = {"/api/ai/chat", "/api/kernel/execute"}


async def delegate_editor_request(
    app: ASGIApp,
    notebooks: NotebookScopeRegistry,
    scope: Scope,
    receive: Receive,
    send: Send,
    *,
    relative: str,
    mode: str,
) -> bool:
    """Delegate one editor or code-mode request and report whether it matched."""
    editor_target = native_editor_target(relative)
    if editor_target is not None and mode == "edit":
        delegated_scope = _replace_relative_path(scope, relative, editor_target)
        connection = (
            Request(scope, receive)
            if scope["type"] == "http"
            else WebSocket(scope, receive, send)
        )
        location = server_location(connection)
        if location is not None:
            await _bind_editor_session(notebooks, connection, location.notebook)
        if scope["type"] == "http" and location is not None:
            try:
                workspace = discover_studio(location.notebook)
            except MarimoStudioError:
                workspace = None
            if workspace is not None and workspace.cells:
                enable_cell_alias_sync(location)
            if editor_target.rstrip("/") in _CODE_MODE_ROUTES:
                delegated_scope = attach_code_mode_session(delegated_scope)
        await app(delegated_scope, receive, send)
        return True

    if (
        scope["type"] == "http"
        and mode == "edit"
        and relative.rstrip("/") in _CODE_MODE_ROUTES
    ):
        delegated_scope = attach_code_mode_session(scope)
        await app(delegated_scope, receive, send)
        return True
    return False


async def _bind_editor_session(
    notebooks: NotebookScopeRegistry,
    connection: HTTPConnection,
    notebook: Path,
) -> None:
    if not has_edit_access(connection.scope):
        return
    client_id = connection.query_params.get(STUDIO_CLIENT_QUERY_PARAM)
    session_id = connection.query_params.get("session_id")
    if (
        client_id is None
        or session_id is None
        or re.fullmatch(r"[A-Za-z0-9_-]{16,128}", client_id) is None
        or not is_session_id(session_id)
    ):
        return
    notebook_scope = notebooks.get(notebook)
    await notebook_scope.clients.bind_session(session_id, client_id)


def _replace_relative_path(scope: Scope, current: str, target: str) -> Scope:
    path = str(scope.get("path", "/"))
    prefix = path[: -len(current)] if current and path.endswith(current) else ""
    updated = dict(scope)
    updated_path = f"{prefix}{target}"
    updated["path"] = updated_path
    updated["raw_path"] = updated_path.encode()
    return updated


__all__ = ["delegate_editor_request"]
