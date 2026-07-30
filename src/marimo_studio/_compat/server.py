"""Read the Marimo server state used by presentation middleware."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Any, Literal
from urllib.parse import parse_qs
from weakref import WeakSet

import marimo
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from marimo_studio._assets import runtime_marimo_version
from marimo_studio.errors import ProtocolError

ServerMode = Literal["edit", "run"]
DOCUMENT_REPLAY_QUERY_PARAM = "marimo_studio_resume"

_DOCUMENT_REPLAY_MANAGERS: WeakSet[Any] = WeakSet()
_DOCUMENT_REPLAY_LOCK = Lock()
_DOCUMENT_REPLAY_PATCHED = False


@dataclass(frozen=True)
class ServerLocation:
    notebook: Path
    file_key: str
    base_url: str
    mode: ServerMode
    _state: Any
    _session_manager: Any


@dataclass(frozen=True)
class ServerContext:
    notebook: Path
    file_key: str
    base_url: str
    mode: ServerMode
    dev: bool
    user_config: dict[str, Any]
    config_overrides: dict[str, Any]
    server_token: str
    _session_manager: Any


def _reconnect_with_document_replay(
    connector: Any,
    session: Any,
    reconnect: Any,
    reconnect_type: Any,
) -> tuple[Any, Any]:
    requested = (
        connector.connection.query_params.get(DOCUMENT_REPLAY_QUERY_PARAM) == "1"
    )
    with _DOCUMENT_REPLAY_LOCK:
        enabled = connector.manager in _DOCUMENT_REPLAY_MANAGERS
    if not requested or not enabled:
        return reconnect(connector, session)

    session.disconnect_main_consumer()
    connector.handler._reconnect_session(session, replay=True)
    return session, reconnect_type


def assert_supported_version() -> None:
    """Require the Marimo version used to build the browser adapter."""
    expected = runtime_marimo_version()
    if marimo.__version__ != expected:
        raise ProtocolError(
            f"marimo {marimo.__version__} is incompatible with this runtime. "
            f"Install marimo {expected}."
        )


def enable_document_replay(context: ServerContext) -> None:
    """Replay session state for an opted-in document refresh."""
    global _DOCUMENT_REPLAY_PATCHED

    with _DOCUMENT_REPLAY_LOCK:
        _DOCUMENT_REPLAY_MANAGERS.add(context._session_manager)
        if _DOCUMENT_REPLAY_PATCHED:
            return

        from marimo._runtime.params import QueryParams
        from marimo._server.api.endpoints.ws.ws_session_connector import (
            ConnectionType,
            SessionConnector,
        )

        connector_class: Any = SessionConnector
        reconnect = connector_class._reconnect_session

        def reconnect_session(connector: Any, session: Any) -> tuple[Any, Any]:
            return _reconnect_with_document_replay(
                connector,
                session,
                reconnect,
                ConnectionType.RECONNECT,
            )

        connector_class._reconnect_session = reconnect_session
        QueryParams.IGNORED_KEYS.add(DOCUMENT_REPLAY_QUERY_PARAM)
        _DOCUMENT_REPLAY_PATCHED = True


def _effective_base_url(scope: Scope, configured: str) -> str:
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


def server_location(scope: Scope) -> ServerLocation | None:
    """Locate a single-notebook Marimo application without activating the adapter."""
    app = scope.get("app")
    state = getattr(app, "state", None)
    manager = getattr(state, "session_manager", None)
    if manager is None:
        return None
    assert state is not None
    file_key = manager.workspace.get_unique_file_key()
    if not file_key:
        return None
    resolved = manager.workspace.resolve(file_key)
    if resolved is None:
        return None

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
        base_url=_effective_base_url(
            scope,
            str(getattr(state, "base_url", "")),
        ),
        mode=mode,
        _state=state,
        _session_manager=manager,
    )


def server_context(location: ServerLocation) -> ServerContext:
    """Read the validated Marimo state needed by an active presentation."""
    assert_supported_version()
    configured_notebook = getattr(
        location._state,
        "_marimo_studio_configured_notebook",
        None,
    )
    if configured_notebook != location.notebook:
        config_manager = _config_manager_at_notebook(
            location._state.config_manager,
            location.notebook,
        )
        location._state.config_manager = config_manager
        location._session_manager._config_manager = config_manager
        location._state._marimo_studio_configured_notebook = location.notebook
    else:
        config_manager = location._state.config_manager
    return ServerContext(
        notebook=location.notebook,
        file_key=location.file_key,
        base_url=location.base_url,
        mode=location.mode,
        dev=location.mode == "edit"
        or bool(getattr(location._session_manager, "watch", False)),
        user_config=config_manager.get_user_config(),
        config_overrides=config_manager.get_config_overrides(),
        server_token=str(location._session_manager.skew_protection_token),
        _session_manager=location._session_manager,
    )


def relative_request_path(scope: Scope, base_url: str) -> str | None:
    """Resolve a request path relative to Marimo's configured base URL."""
    path = str(scope.get("path", "/"))
    base = base_url.rstrip("/")
    if not base:
        return path
    if path == base:
        return "/"
    if path.startswith(f"{base}/"):
        return path[len(base) :] or "/"
    # Dynamic-directory mounts pass a path relative to the selected notebook
    # while retaining its public base URL in application state.
    if path.startswith("/"):
        return path
    return None


def _config_manager_at_notebook(config_manager: Any, notebook: Path) -> Any:
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


class _ProgrammaticApp:
    def __init__(
        self,
        app: ASGIApp,
        state: Any,
        configured_base_url: str,
    ) -> None:
        self.app = app
        self.state = state
        self.configured_base_url = configured_base_url
        self._public_base_url: str | None = None
        self._lock = Lock()

    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        if scope["type"] not in {"http", "websocket"}:
            await self.app(scope, receive, send)
            return

        public_base_url = _effective_base_url(
            scope,
            self.configured_base_url,
        )
        with self._lock:
            if self._public_base_url is None:
                self._public_base_url = public_base_url
                self.state.base_url = public_base_url
            elif self._public_base_url != public_base_url:
                raise ProtocolError(
                    "A programmatic Marimo app must use one public mount path"
                )

        if scope["type"] != "http" or not public_base_url:
            await self.app(scope, receive, send)
            return

        async def send_with_public_base(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers: list[tuple[bytes, bytes]] = []
                for name, value in message.get("headers", []):
                    # Marimo resolves the login route inside its notebook app,
                    # so Starlette cannot include an outer ASGI mount here.
                    if name.lower() == b"location" and (
                        value == b"/auth/login" or value.startswith(b"/auth/login?")
                    ):
                        value = (f"{public_base_url}{value.decode('latin-1')}").encode(
                            "latin-1"
                        )
                    headers.append((name, value))
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_with_public_base)


class _ProgrammaticMiddleware:
    def __init__(self, notebook: Path) -> None:
        self.notebook = notebook

    def __call__(self, app: ASGIApp) -> ASGIApp:
        state = getattr(app, "state", None)
        session_manager = getattr(state, "session_manager", None)
        if state is None or session_manager is None:
            raise ProtocolError("Marimo did not expose single-notebook server state")
        config_manager = _config_manager_at_notebook(
            state.config_manager,
            self.notebook,
        )
        state.config_manager = config_manager
        session_manager._config_manager = config_manager
        state._marimo_studio_configured_notebook = self.notebook
        return _ProgrammaticApp(
            app,
            state,
            str(getattr(state, "base_url", "")),
        )


def programmatic_middleware(
    notebook: Path,
) -> _ProgrammaticMiddleware:
    """Bind notebook configuration and its public mount to a Marimo app."""
    return _ProgrammaticMiddleware(notebook)


def has_read_access(scope: Scope) -> bool:
    auth = scope.get("auth")
    scopes = getattr(auth, "scopes", ())
    return "read" in scopes


def has_access_token(scope: Scope) -> bool:
    raw = scope.get("query_string", b"")
    query = parse_qs(bytes(raw).decode("latin-1"), keep_blank_values=True)
    return "access_token" in query


def current_session(context: ServerContext, session_id: str) -> Any | None:
    from marimo._types.ids import SessionId

    return context._session_manager.get_session(SessionId(session_id))


def has_notebook_session(context: ServerContext) -> bool:
    """Return whether edit mode has a primary session for this notebook."""
    return (
        context._session_manager.get_session_by_file_key(context.file_key) is not None
    )
