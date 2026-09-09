"""Translate private Marimo server state into Studio-owned records."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, quote, urlencode

from starlette.authentication import AuthCredentials, SimpleUser
from starlette.requests import Request
from starlette.types import Scope
from starlette.websockets import WebSocket

from marimo_studio._delivery.urls import public_url
from marimo_studio._server.records import (
    ServerContext,
    ServerHandle,
    ServerLocation,
    ServerMode,
)


@dataclass(frozen=True)
class _LocationHandle:
    config_manager: Any
    state: Any
    session_manager: Any


@dataclass(frozen=True)
class _ContextHandle:
    server: Any
    session_manager: Any


def effective_base_url(scope: Scope, configured: str) -> str:
    root_path = str(scope.get("root_path", "")).rstrip("/")
    configured = configured.rstrip("/")
    if not root_path:
        return configured
    if not configured:
        return root_path
    if root_path == configured or root_path.endswith(f"/{configured.lstrip('/')}"):
        return root_path
    if configured.startswith(f"{root_path}/"):
        return configured
    return f"{root_path}/{configured.lstrip('/')}"


def _server_base_url(scope: Scope) -> str | None:
    app = scope.get("app")
    state = getattr(app, "state", None)
    manager = getattr(state, "session_manager", None)
    if manager is None:
        return None
    assert state is not None
    return effective_base_url(scope, str(getattr(state, "base_url", "")))


def _server_mode(scope: Scope) -> ServerMode | None:
    app = scope.get("app")
    state = getattr(app, "state", None)
    manager = getattr(state, "session_manager", None)
    if manager is None:
        return None

    from marimo._session.model import SessionMode

    if manager.mode is SessionMode.RUN:
        return "run"
    if manager.mode is SessionMode.EDIT:
        return "edit"
    return None


def _server_uses_file_routing(scope: Scope) -> bool:
    app = scope.get("app")
    state = getattr(app, "state", None)
    manager = getattr(state, "session_manager", None)
    return manager is not None and manager.workspace.get_unique_file_key() is None


def _internal_server_url(scope: Scope, base_url: str) -> str | None:
    server = scope.get("server")
    if server is None:
        return None
    host, port = server
    if not isinstance(host, str) or not host or not isinstance(port, int) or port <= 0:
        return None
    host = host.strip("[]")
    if host == "0.0.0.0":
        host = "127.0.0.1"
    elif host == "::":
        host = "::1"
    authority = f"[{host}]" if ":" in host else host
    return f"http://{authority}:{port}{public_url(base_url, '/')}"


async def _server_location(
    request: Request | WebSocket,
    selected_file: str | None = None,
) -> ServerLocation | None:
    scope = request.scope
    app = scope.get("app")
    state = getattr(app, "state", None)
    manager = getattr(state, "session_manager", None)
    if manager is None:
        return None
    assert state is not None
    unique_file = manager.workspace.get_unique_file_key()
    file_key = (
        unique_file
        if unique_file is not None
        else selected_file or request.query_params.get("file")
    )
    if not file_key:
        return None

    from marimo._utils.http import HTTPException

    try:
        resolved = await asyncio.to_thread(manager.workspace.resolve, file_key)
    except HTTPException:
        return None
    if resolved is None:
        return None
    notebook = Path(resolved)

    from marimo._session.model import SessionMode

    if manager.mode is SessionMode.RUN:
        mode: ServerMode = "run"
    elif manager.mode is SessionMode.EDIT:
        mode = "edit"
    else:
        return None
    base_url = effective_base_url(scope, str(getattr(state, "base_url", "")))
    return ServerLocation(
        notebook=notebook,
        file_key=str(file_key),
        base_url=base_url,
        internal_url=_internal_server_url(scope, base_url),
        mode=mode,
        routing_query=((("file", str(file_key)),) if unique_file is None else ()),
        handle=ServerHandle(
            _LocationHandle(
                config_manager=config_manager_at_notebook(
                    state.config_manager,
                    notebook,
                ),
                state=state,
                session_manager=manager,
            )
        ),
    )


async def _server_session_location(
    request: Request | WebSocket,
    session_id: str,
) -> ServerLocation | None:
    app = request.scope.get("app")
    state = getattr(app, "state", None)
    manager = getattr(state, "session_manager", None)
    if manager is None:
        return None
    from marimo._types.ids import SessionId

    session = manager.get_session(SessionId(session_id))
    path = getattr(getattr(session, "app_file_manager", None), "path", None)
    if not isinstance(path, str) or not path:
        return None
    file_key = path
    directory = manager.workspace.directory
    if directory is not None:
        with suppress(ValueError):
            file_key = Path(path).relative_to(Path(directory)).as_posix()
    return await _server_location(request, file_key)


def location_handle(location: ServerLocation) -> _LocationHandle:
    handle = location.handle
    if not isinstance(handle, _LocationHandle):
        raise TypeError("Server location belongs to another Marimo adapter")
    return handle


def _server_context(location: ServerLocation) -> ServerContext:
    handle = location_handle(location)
    config_manager = handle.config_manager
    return ServerContext(
        notebook=location.notebook,
        file_key=location.file_key,
        base_url=location.base_url,
        internal_url=location.internal_url,
        mode=location.mode,
        dev=location.mode == "edit"
        or bool(getattr(handle.session_manager, "watch", False)),
        routing_query=location.routing_query,
        user_config=config_manager.get_user_config(),
        config_overrides=config_manager.get_config_overrides(),
        server_token=str(handle.session_manager.skew_protection_token),
        access_token=str(handle.session_manager.auth_token) or None,
        handle=ServerHandle(
            _ContextHandle(
                server=getattr(handle.state, "server", None),
                session_manager=handle.session_manager,
            )
        ),
    )


def context_handle(context: ServerContext) -> _ContextHandle:
    """Return the private state carried by one adapter-owned context."""
    handle = context.handle
    if not isinstance(handle, _ContextHandle):
        raise TypeError("Server context belongs to another Marimo adapter")
    return handle


def _relative_request_path(scope: Scope, base_url: str) -> str | None:
    path = str(scope.get("path", "/"))
    base = base_url.rstrip("/")
    if not base:
        return path

    relative = _path_beneath(path, base)
    if relative is not None:
        return relative

    root_path = str(scope.get("root_path", "")).rstrip("/")
    if not root_path:
        return None
    if base == root_path:
        mounted_base = ""
    elif base.startswith(f"{root_path}/"):
        mounted_base = base[len(root_path) :]
    else:
        return None
    return _path_beneath(path, mounted_base)


def _authorize_presentation_request(
    scope: Scope,
    context: ServerContext,
) -> Scope:
    """Attach private Marimo credentials after Studio authorizes a capability."""
    handle = context_handle(context)
    headers = [
        (name, value)
        for name, value in scope.get("headers", ())
        if bytes(name).lower() not in {b"marimo-server-token", b"x-notebook-id"}
    ]
    headers.append((b"marimo-server-token", context.server_token.encode()))
    headers.append(
        (
            b"x-notebook-id",
            quote(context.file_key, safe="~()*!.'").encode("ascii"),
        )
    )
    query = [
        (name, value)
        for name, value in parse_qsl(
            bytes(scope.get("query_string", b"")).decode("latin-1"),
            keep_blank_values=True,
        )
        if name != "access_token"
    ]
    auth_token = str(getattr(handle.session_manager, "auth_token", ""))
    if auth_token:
        query.append(("access_token", auth_token))
    authorized = dict(scope)
    authorized["headers"] = headers
    authorized["query_string"] = urlencode(query).encode("latin-1")
    authorized["auth"] = AuthCredentials(
        ["read", "edit"] if context.mode == "edit" else ["read"]
    )
    authorized["user"] = SimpleUser("user")
    return authorized


def _path_beneath(path: str, base: str) -> str | None:
    if not base:
        return path
    if path == base:
        return "/"
    if path.startswith(f"{base}/"):
        return path[len(base) :] or "/"
    return None


def config_manager_at_notebook(config_manager: Any, notebook: Path) -> Any:
    from marimo._config.manager import (
        MarimoConfigManager,
        ProjectConfigManager,
        ScriptConfigManager,
    )

    partials: list[Any] = []
    has_project = False
    has_script = False
    for partial in config_manager.partials:
        if isinstance(partial, ProjectConfigManager):
            partials.append(ProjectConfigManager(str(notebook)))
            has_project = True
        elif isinstance(partial, ScriptConfigManager):
            partials.append(ScriptConfigManager(str(notebook)))
            has_script = True
        else:
            partials.append(partial)
    if not has_project:
        partials.insert(0, ProjectConfigManager(str(notebook)))
    if not has_script:
        partials.insert(1, ScriptConfigManager(str(notebook)))
    return MarimoConfigManager(
        config_manager.user_config_mgr,
        *partials,
        *config_manager.security_partials,
    )


class PrivateServerGateway:
    """Read Marimo server state through the pinned release adapter."""

    def base_url(self, scope: Scope) -> str | None:
        return _server_base_url(scope)

    def mode(self, scope: Scope) -> ServerMode | None:
        return _server_mode(scope)

    def uses_file_routing(self, scope: Scope) -> bool:
        return _server_uses_file_routing(scope)

    async def location(
        self,
        request: Request | WebSocket,
        selected_file: str | None = None,
    ) -> ServerLocation | None:
        return await _server_location(request, selected_file)

    async def session_location(
        self,
        request: Request | WebSocket,
        session_id: str,
    ) -> ServerLocation | None:
        return await _server_session_location(request, session_id)

    def context(self, location: ServerLocation) -> ServerContext:
        return _server_context(location)

    def relative_path(self, scope: Scope, base_url: str) -> str | None:
        return _relative_request_path(scope, base_url)

    def authorize_presentation(
        self,
        scope: Scope,
        context: ServerContext,
    ) -> Scope:
        return _authorize_presentation_request(scope, context)

    def shutdown_requested(self, context: ServerContext) -> bool:
        return bool(getattr(context_handle(context).server, "should_exit", False))
