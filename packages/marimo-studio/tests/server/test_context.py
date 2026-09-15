from __future__ import annotations

import asyncio
from pathlib import Path
from threading import get_ident
from types import SimpleNamespace
from urllib.parse import urlencode

import pytest
from marimo._config.manager import get_default_config_manager
from marimo._server.models.home import MarimoFile
from marimo._server.workspace._directory import DirectoryWorkspace
from marimo._server.workspace._empty import EmptyWorkspace
from marimo._server.workspace._fixed import FixedFilesWorkspace
from marimo._session.model import SessionMode
from starlette.datastructures import Headers, QueryParams
from starlette.requests import Request
from starlette.types import Message
from starlette.websockets import WebSocket

from marimo_studio._compat.server.gateway import PrivateServerGateway
from marimo_studio._server.records import ServerLocation

from ..helpers import notebook_source


def _location(
    gateway: PrivateServerGateway,
    connection: Request | WebSocket,
) -> ServerLocation | None:
    return asyncio.run(gateway.location(connection))


def _server(directory: Path) -> tuple[SimpleNamespace, object]:
    config_manager = get_default_config_manager(current_path=str(directory))
    workspace = DirectoryWorkspace(str(directory), include_markdown=False)
    assert isinstance(workspace.files, list)
    manager = SimpleNamespace(
        workspace=workspace,
        mode=SessionMode.EDIT,
        auth_token="browser-token",
        skew_protection_token="server-token",
    )
    state = SimpleNamespace(
        base_url="",
        config_manager=config_manager,
        session_manager=manager,
    )
    return state, config_manager


def _request(state: object, file_key: str) -> Request:
    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/",
        "raw_path": b"/",
        "query_string": urlencode({"file": file_key}).encode(),
        "headers": [],
        "client": ("test", 0),
        "server": ("test", 80),
        "app": SimpleNamespace(state=state),
    }
    return Request(scope)


def _websocket(state: object, file_key: str) -> WebSocket:
    scope = {
        **_request(state, file_key).scope,
        "type": "websocket",
        "scheme": "ws",
    }

    async def receive() -> dict[str, object]:
        return {"type": "websocket.disconnect", "code": 1000}

    async def send(_message: Message) -> None:
        return None

    return WebSocket(scope, receive, send)


def test_directory_request_resolves_notebook_without_mutating_server_config(
    tmp_path: Path,
) -> None:
    first = tmp_path / "first.py"
    second = tmp_path / "nested" / "second.py"
    second.parent.mkdir()
    first.write_text(notebook_source(tmp_path / "first-output"), encoding="utf-8")
    second.write_text(notebook_source(tmp_path / "second-output"), encoding="utf-8")
    state, config_manager = _server(tmp_path)
    state.session_manager.get_session = lambda _session_id: SimpleNamespace(
        app_file_manager=SimpleNamespace(path=str(second))
    )
    first_request = _request(state, "first.py")
    second_request = _request(state, "nested/second.py")

    gateway = PrivateServerGateway()
    first_location = _location(gateway, first_request)
    second_location = _location(gateway, second_request)

    assert first_location is not None
    assert first_location.notebook == first.resolve()
    assert first_location.routing_query == (("file", "first.py"),)
    assert first_request.app.state.config_manager is config_manager
    assert second_location is not None
    assert second_location.notebook == second.resolve()
    assert second_location.routing_query == (("file", "nested/second.py"),)
    session_location = asyncio.run(
        gateway.session_location(
            _request(state, ""),
            "s_123456",
        )
    )
    assert session_location is not None
    assert session_location.file_key == "nested/second.py"


def test_gateway_location_and_context_resolve_off_the_event_loop(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    notebook = tmp_path / "analysis.py"
    notebook.write_text(notebook_source(tmp_path / "output"), encoding="utf-8")
    state, _ = _server(tmp_path)
    resolve = state.session_manager.workspace.resolve
    event_loop_thread = get_ident()
    resolver_threads: list[int] = []

    def observed_resolve(file_key: str) -> str | None:
        resolver_threads.append(get_ident())
        return resolve(file_key)

    monkeypatch.setattr(
        state.session_manager.workspace,
        "resolve",
        observed_resolve,
    )
    gateway = PrivateServerGateway()

    http_location = _location(gateway, _request(state, "analysis.py"))
    websocket_location = _location(gateway, _websocket(state, "analysis.py"))

    assert http_location is not None
    assert websocket_location is not None
    assert http_location.notebook == notebook
    assert websocket_location.notebook == notebook
    assert gateway.context(http_location).notebook == notebook
    assert gateway.context(websocket_location).notebook == notebook
    assert _location(gateway, _request(state, "missing.py")) is None
    assert _location(gateway, _websocket(state, "missing.py")) is None
    assert resolver_threads
    assert all(thread != event_loop_thread for thread in resolver_threads)


def test_single_notebook_ignores_directory_file_selectors(tmp_path: Path) -> None:
    notebook = tmp_path / "only.py"
    notebook.write_text(notebook_source(tmp_path / "output"), encoding="utf-8")
    state, _ = _server(tmp_path)
    state.session_manager.workspace = SimpleNamespace(
        get_unique_file_key=lambda: "only.py",
        resolve=lambda key: str(notebook) if key == "only.py" else None,
        single_file=lambda: SimpleNamespace(path=str(notebook)),
    )

    location = _location(PrivateServerGateway(), _request(state, "other.py"))

    assert location is not None
    assert location.file_key == "only.py"
    assert location.notebook == notebook.resolve()
    assert location.routing_query == ()


def test_gateway_preserves_cached_temp_and_fixed_allowlists(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    temp_root = tmp_path / "tutorial"
    temp_root.mkdir()
    temp_notebook = temp_root / "lesson.py"
    temp_notebook.write_text(
        notebook_source(tmp_path / "temp-output"),
        encoding="utf-8",
    )
    state, _ = _server(root)
    workspace = state.session_manager.workspace
    workspace.register_temp_dir(str(temp_root))
    gateway = PrivateServerGateway()

    temp_location = _location(gateway, _request(state, str(temp_notebook)))

    fixed_notebook = root / "fixed.py"
    fixed_notebook.write_text(
        notebook_source(tmp_path / "fixed-output"),
        encoding="utf-8",
    )
    state.session_manager.workspace = FixedFilesWorkspace(
        [MarimoFile(name=fixed_notebook.name, path=str(fixed_notebook))],
        directory=str(root),
    )
    fixed_location = _location(gateway, _request(state, "fixed.py"))

    assert temp_location is not None
    assert temp_location.notebook == temp_notebook
    assert fixed_location is not None
    assert fixed_location.notebook == fixed_notebook


def test_gateway_preserves_workspace_symlink_policy_for_http_and_websocket(
    tmp_path: Path,
) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    outside = tmp_path / "outside.py"
    outside.write_text(notebook_source(tmp_path / "outside-output"), encoding="utf-8")
    (root / "escape.py").symlink_to(outside)
    state, _ = _server(root)
    gateway = PrivateServerGateway()

    http_location = _location(gateway, _request(state, "escape.py"))
    websocket_location = _location(gateway, _websocket(state, "escape.py"))

    assert http_location is not None
    assert websocket_location is not None
    assert http_location.notebook == root / "escape.py"
    assert websocket_location.notebook == root / "escape.py"


def test_presentation_authorization_restores_private_marimo_authentication(
    tmp_path: Path,
) -> None:
    notebook = tmp_path / "only.py"
    notebook.write_text(notebook_source(tmp_path / "output"), encoding="utf-8")
    state, _ = _server(tmp_path)
    state.session_manager.workspace = SimpleNamespace(
        get_unique_file_key=lambda: "only.py",
        resolve=lambda key: str(notebook) if key == "only.py" else None,
        single_file=lambda: SimpleNamespace(path=str(notebook)),
    )
    gateway = PrivateServerGateway()
    location = _location(gateway, _request(state, "only.py"))
    assert location is not None
    context = gateway.context(location)
    scope = {
        **_request(state, "only.py").scope,
        "headers": [(b"marimo-server-token", b"presentation-capability")],
    }

    authorized = gateway.authorize_presentation(scope, context)

    assert Headers(scope=authorized)["Marimo-Server-Token"] == "server-token"
    assert QueryParams(authorized["query_string"])["access_token"] == "browser-token"
    assert authorized["auth"].scopes == ["read", "edit"]
    assert authorized["user"].is_authenticated


def test_untitled_singleton_resolves_its_saved_notebook(tmp_path: Path) -> None:
    notebook = tmp_path / "first.py"
    notebook.write_text(notebook_source(tmp_path / "output"), encoding="utf-8")
    state, config_manager = _server(tmp_path)
    state.session_manager.workspace = EmptyWorkspace()
    state.session_manager.get_session = lambda _session_id: SimpleNamespace(
        app_file_manager=SimpleNamespace(path=str(notebook))
    )
    gateway = PrivateServerGateway()
    request = _request(state, "")
    assert _location(gateway, request) is None
    assert gateway.uses_file_routing(request.scope)
    saved = asyncio.run(gateway.session_location(request, "s_123456"))
    assert saved is not None
    assert saved.notebook == notebook.resolve()
    assert saved.routing_query == (("file", str(notebook)),)
    reopened = _location(gateway, _request(state, str(notebook)))
    assert reopened is not None
    assert reopened.notebook == saved.notebook
    assert reopened.routing_query == saved.routing_query
    assert request.app.state.config_manager is config_manager
