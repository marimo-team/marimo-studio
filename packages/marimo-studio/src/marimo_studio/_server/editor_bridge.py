"""Delegate native editor traffic while attaching Studio session context."""

from __future__ import annotations

import re
from pathlib import Path

from starlette.requests import HTTPConnection, Request
from starlette.types import ASGIApp, Receive, Scope, Send
from starlette.websockets import WebSocket

from marimo_studio._capabilities import (
    CodeModeBridge,
    NotebookSaveTransform,
    ServerGateway,
    SessionState,
)
from marimo_studio._server.auth import has_edit_access
from marimo_studio._server.notebook_scope import NotebookScopeRegistry
from marimo_studio._server.routing import native_editor_target
from marimo_studio._server.server_instance import server_instance_id
from marimo_studio._urls import (
    SERVER_INSTANCE_QUERY_PARAM,
    STUDIO_CLIENT_QUERY_PARAM,
)
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
    server: ServerGateway,
    sessions: SessionState,
    persistence: NotebookSaveTransform,
    code_mode: CodeModeBridge,
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
        location = server.location(connection)
        if location is not None:
            context = server.context(location)
            await _bind_editor_session(
                notebooks,
                connection,
                location.notebook,
                sessions,
                expected_server_instance=server_instance_id(context.server_token),
            )
        if scope["type"] == "http" and location is not None:
            try:
                workspace = discover_studio(location.notebook)
            except MarimoStudioError:
                workspace = None
            if workspace is not None and workspace.cells:
                persistence.enable(location)
            if editor_target.rstrip("/") in _CODE_MODE_ROUTES:
                delegated_scope = code_mode.attach_session(delegated_scope)
        await app(delegated_scope, receive, send)
        return True

    if (
        scope["type"] == "http"
        and mode == "edit"
        and relative.rstrip("/") in _CODE_MODE_ROUTES
    ):
        delegated_scope = code_mode.attach_session(scope)
        await app(delegated_scope, receive, send)
        return True
    return False


async def _bind_editor_session(
    notebooks: NotebookScopeRegistry,
    connection: HTTPConnection,
    notebook: Path,
    sessions: SessionState,
    *,
    expected_server_instance: str,
) -> None:
    if not has_edit_access(connection.scope):
        return
    if (
        connection.query_params.get(SERVER_INSTANCE_QUERY_PARAM)
        != expected_server_instance
    ):
        return
    client_id = connection.query_params.get(STUDIO_CLIENT_QUERY_PARAM)
    session_id = connection.query_params.get("session_id")
    if (
        client_id is None
        or session_id is None
        or re.fullmatch(r"[A-Za-z0-9_-]{16,128}", client_id) is None
        or not sessions.is_session_id(session_id)
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
