from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlencode

from marimo._config.manager import get_default_config_manager
from marimo._server.workspace._directory import DirectoryWorkspace
from marimo._session.model import SessionMode
from starlette.requests import Request

from marimo_studio._compat.server.gateway import PrivateServerGateway

from .helpers import notebook_source


def _server(directory: Path) -> tuple[SimpleNamespace, object]:
    config_manager = get_default_config_manager(current_path=str(directory))
    manager = SimpleNamespace(
        workspace=DirectoryWorkspace(str(directory), include_markdown=False),
        mode=SessionMode.EDIT,
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


def test_directory_request_resolves_notebook_without_mutating_server_config(
    tmp_path: Path,
) -> None:
    first = tmp_path / "first.py"
    second = tmp_path / "nested" / "second.py"
    second.parent.mkdir()
    first.write_text(notebook_source(tmp_path / "first-output"), encoding="utf-8")
    second.write_text(notebook_source(tmp_path / "second-output"), encoding="utf-8")
    state, config_manager = _server(tmp_path)
    first_request = _request(state, "first.py")
    second_request = _request(state, "nested/second.py")

    gateway = PrivateServerGateway()
    first_location = gateway.location(first_request)
    second_location = gateway.location(second_request)

    assert first_location is not None
    assert first_location.notebook == first.resolve()
    assert first_location.routing_query == (("file", "first.py"),)
    assert first_request.app.state.config_manager is config_manager
    assert second_location is not None
    assert second_location.notebook == second.resolve()
    assert second_location.routing_query == (("file", "nested/second.py"),)


def test_single_notebook_ignores_directory_file_selectors(tmp_path: Path) -> None:
    notebook = tmp_path / "only.py"
    notebook.write_text(notebook_source(tmp_path / "output"), encoding="utf-8")
    state, _ = _server(tmp_path)
    state.session_manager.workspace = SimpleNamespace(
        get_unique_file_key=lambda: "only.py",
        resolve=lambda key: str(notebook) if key == "only.py" else None,
    )

    location = PrivateServerGateway().location(_request(state, "other.py"))

    assert location is not None
    assert location.file_key == "only.py"
    assert location.notebook == notebook.resolve()
    assert location.routing_query == ()
