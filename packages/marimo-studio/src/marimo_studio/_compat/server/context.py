"""Locate and configure the Marimo server behind Studio middleware."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from starlette.requests import Request
from starlette.types import Scope
from starlette.websockets import WebSocket

from marimo_studio._compat.server.models import (
    ServerContext,
    ServerLocation,
    ServerMode,
)
from marimo_studio._compat.version import assert_supported_version


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


def server_base_url(scope: Scope) -> str | None:
    """Return the public base URL of a Marimo server application."""
    app = scope.get("app")
    state = getattr(app, "state", None)
    manager = getattr(state, "session_manager", None)
    if manager is None:
        return None
    assert state is not None
    return effective_base_url(scope, str(getattr(state, "base_url", "")))


def server_mode(scope: Scope) -> str | None:
    """Return the active Marimo server mode."""
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


def server_uses_file_routing(scope: Scope) -> bool:
    """Return whether requests select notebooks within this server."""
    app = scope.get("app")
    state = getattr(app, "state", None)
    manager = getattr(state, "session_manager", None)
    return manager is not None and manager.workspace.get_unique_file_key() is None


def server_location(
    request: Request | WebSocket,
    selected_file: str | None = None,
) -> ServerLocation | None:
    """Locate the notebook selected for one Marimo server request."""
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
        resolved = manager.workspace.resolve(file_key)
    except HTTPException:
        return None
    if resolved is None:
        return None

    from marimo._server.api.deps import AppState
    from marimo._session.model import SessionMode

    if manager.mode is SessionMode.RUN:
        mode: ServerMode = "run"
    elif manager.mode is SessionMode.EDIT:
        mode = "edit"
    else:
        return None
    return ServerLocation(
        notebook=Path(resolved).resolve(),
        file_key=str(file_key),
        base_url=effective_base_url(scope, str(getattr(state, "base_url", ""))),
        mode=mode,
        routing_query=((("file", str(file_key)),) if unique_file is None else ()),
        _config_manager=AppState(request).config_manager_at_file(str(file_key)),
        _state=state,
        _session_manager=manager,
    )


def server_context(location: ServerLocation) -> ServerContext:
    """Read the validated Marimo state needed by a presentation."""
    assert_supported_version()
    config_manager = location._config_manager
    return ServerContext(
        notebook=location.notebook,
        file_key=location.file_key,
        base_url=location.base_url,
        mode=location.mode,
        dev=location.mode == "edit"
        or bool(getattr(location._session_manager, "watch", False)),
        routing_query=location.routing_query,
        user_config=config_manager.get_user_config(),
        config_overrides=config_manager.get_config_overrides(),
        server_token=str(location._session_manager.skew_protection_token),
        _server=getattr(location._state, "server", None),
        _session_manager=location._session_manager,
    )


def server_shutdown_requested(context: ServerContext) -> bool:
    """Return whether Marimo has begun shutting down its HTTP server."""
    return bool(getattr(context._server, "should_exit", False))


def relative_request_path(scope: Scope, base_url: str) -> str | None:
    """Resolve a request path relative to Marimo's configured base URL."""
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
