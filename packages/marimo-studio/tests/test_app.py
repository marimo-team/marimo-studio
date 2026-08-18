from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import threading
from collections.abc import AsyncGenerator, MutableMapping
from html.parser import HTMLParser
from importlib.metadata import entry_points
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import Mock
from urllib.parse import parse_qs, quote, urlencode, urlsplit

import marimo
import pytest
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.routing import Mount
from starlette.testclient import TestClient

from marimo_studio import create_asgi_app
from marimo_studio._compat.notebook import load_static_notebook
from marimo_studio._compat.server.existing_session import (
    PrivateExistingSessionAttachment,
)
from marimo_studio._compat.server.session_replay import PrivateSessionReplay
from marimo_studio._compat.server.session_state import PrivateSessionState
from marimo_studio._server import dev
from marimo_studio._server.live_clients import StudioClientRegistry
from marimo_studio._server.presentation import NotebookPresentation
from marimo_studio._server.server_instance import server_instance_id
from marimo_studio._urls import SERVER_INSTANCE_QUERY_PARAM, authored_view_root_url
from marimo_studio._workspace import load_studio
from marimo_studio._workspace.config import load_studio_definition
from marimo_studio._workspace.metadata import update_notebook_config
from marimo_studio.workspace import bind_cell, ensure_view

from .app_helpers import configured as _configured
from .app_helpers import edit_mode as _edit_mode
from .app_helpers import marimo_app as _marimo_app
from .app_helpers import session_manager as _session_manager
from .app_helpers import set_shell as _set_shell
from .helpers import empty_notebook_source, notebook_source


class _BootstrapParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._reading = False
        self.parts: list[str] = []

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        self._reading = tag == "script" and dict(attrs).get("id") == (
            "marimo-studio-bootstrap"
        )

    def handle_endtag(self, tag: str) -> None:
        if tag == "script":
            self._reading = False

    def handle_data(self, data: str) -> None:
        if self._reading:
            self.parts.append(data)


def _studio_bootstrap(document: str) -> dict[str, Any]:
    parser = _BootstrapParser()
    parser.feed(document)
    return json.loads("".join(parser.parts))


def _assert_server_runtime(data: dict[str, Any], url: str) -> None:
    assert data["url"] == url
    assert data["serverInstance"] == server_instance_id(data["serverToken"])


def test_package_registers_marimo_extension_points() -> None:
    server = {
        point.name: point.load()
        for point in entry_points(group="marimo.server.asgi.middleware")
    }
    kernel = {
        point.name: point.load()
        for point in entry_points(group="marimo.kernel.lifespan")
    }

    assert isinstance(server["marimo-studio"], Middleware)
    assert callable(kernel["marimo-studio"])


def test_session_id_validation_tracks_marimos_server_boundary() -> None:
    sessions = PrivateSessionState()
    assert sessions.is_session_id("s_abc123")
    assert not sessions.is_session_id("s_ABC123")
    assert not sessions.is_session_id("s_short")
    assert not sessions.is_session_id(None)


def test_stale_studio_preview_receives_terminal_session_close(
    notebook_path: Path,
) -> None:
    studio = _configured(notebook_path)
    app = _marimo_app(studio.notebook)
    _edit_mode(app)
    manager = _session_manager(app)
    query = urlencode(
        {
            "session_id": "s_stale1",
            "kiosk": "true",
            "marimo_studio_client": "browser-client-1234",
            SERVER_INSTANCE_QUERY_PARAM: server_instance_id(
                str(manager.skew_protection_token)
            ),
        }
    )

    attachment = PrivateExistingSessionAttachment()
    handle = attachment.open()
    try:
        with (
            TestClient(app) as client,
            client.websocket_connect(f"/ws?{query}") as websocket,
        ):
            close = websocket.receive()
    finally:
        handle.close()

    assert close == {
        "type": "websocket.close",
        "code": 1000,
        "reason": "MARIMO_NO_SESSION",
    }


def test_stale_studio_editor_does_not_create_a_session(
    notebook_path: Path,
) -> None:
    studio = _configured(notebook_path)
    app = _marimo_app(studio.notebook)
    _edit_mode(app)
    manager = _session_manager(app)
    query = urlencode(
        {
            "session_id": "s_stale1",
            "marimo_studio_client": "browser-client-1234",
            SERVER_INSTANCE_QUERY_PARAM: "stale-server",
        }
    )

    attachment = PrivateExistingSessionAttachment()
    handle = attachment.open()
    try:
        with (
            TestClient(app) as client,
            client.websocket_connect(f"/ws?{query}") as websocket,
        ):
            close = websocket.receive()
    finally:
        handle.close()

    assert close == {
        "type": "websocket.close",
        "code": 1000,
        "reason": "MARIMO_NO_SESSION",
    }
    assert manager.get_session("s_stale1") is None


def test_stale_development_stream_stops_reconnecting(
    notebook_path: Path,
) -> None:
    studio = _configured(notebook_path)
    app = _marimo_app(studio.notebook)
    _edit_mode(app)

    with TestClient(app) as client:
        response = client.get(
            "/_marimo-studio/views/dashboard/dev/events",
            params={SERVER_INSTANCE_QUERY_PARAM: "stale-server"},
        )

    assert response.status_code == 204


def test_run_mode_serves_default_and_named_view_documents(
    notebook_path: Path,
) -> None:
    studio = _configured(notebook_path)

    with TestClient(create_asgi_app(studio.notebook)) as client:
        default = client.get("/")
        named = client.get("/executive/")
        explicit_index = client.get("/executive/index.html")
        native_editor = client.get("/_marimo-studio/editor/")

    assert default.status_code == 200
    assert default.text.count('id="marimo-runtime-root"') == 1
    assert '"/_marimo-studio/views/dashboard?marimo_studio_server=' in default.text
    assert default.text.index("runtime.css") < default.text.index("app.css")
    assert named.status_code == 200
    assert '"/_marimo-studio/views/executive?marimo_studio_server=' in named.text
    assert explicit_index.url.path == "/executive/"
    assert explicit_index.text.count('id="marimo-runtime-root"') == 1
    assert native_editor.status_code == 404


def test_view_asset_changes_refresh_the_presentation(notebook_path: Path) -> None:
    studio = _configured(notebook_path)
    view = studio.views["dashboard"]
    scripts = view.root / "scripts"
    scripts.mkdir()
    asset = scripts / "app.js"
    asset.write_text('export const message = "ready";\n', encoding="utf-8")

    with TestClient(create_asgi_app(studio.notebook)) as client:
        before = client.get("/")
        source = client.get("/dashboard/scripts/app.js")
        asset.write_text('export const message = "fresh";\n', encoding="utf-8")
        after = client.get("/")

    assert source.status_code == 200
    assert source.headers["content-type"].startswith("text/javascript")
    assert (
        before.headers["Marimo-Studio-Revision"]
        != after.headers["Marimo-Studio-Revision"]
    )


def test_view_relative_routes_keep_marimo_and_studio_ownership(
    notebook_path: Path,
) -> None:
    studio = _configured(notebook_path)
    public = studio.notebook.parent / "public"
    public.mkdir()
    public.joinpath("sample.txt").write_text("notebook asset", encoding="utf-8")

    with TestClient(create_asgi_app(studio.notebook)) as client:
        cell = client.get("/dashboard/_marimo-studio/views/dashboard/cells/result")
        case_equivalent_cell = client.get(
            "/dashboard/_MARIMO-STUDIO/views/dashboard/cells/result"
        )
        asset = client.get(
            "/dashboard/public/sample.txt",
            headers={"X-Notebook-Id": quote(str(studio.notebook), safe="")},
        )
        service_worker = client.get("/dashboard/public-files-sw.js")

    assert cell.status_code == 200
    assert cell.text == '<marimo-cell name="result"></marimo-cell>'
    assert case_equivalent_cell.text == '<marimo-cell name="result"></marimo-cell>'
    assert asset.status_code == 200
    assert asset.text == "notebook asset"
    assert service_worker.status_code == 200


def test_empty_notebook_serves_a_ready_starter_view(tmp_path: Path) -> None:
    notebook = tmp_path / "analysis.py"
    notebook.write_text(empty_notebook_source(), encoding="utf-8")
    ensure_view(notebook)

    with TestClient(create_asgi_app(notebook)) as client:
        page = client.get("/")
        config = client.get("/_marimo-studio/views/dashboard/config")

    assert page.status_code == 200
    assert config.status_code == 200
    assert config.json()["cellBindings"] == {}
    assert config.json()["valueBindings"] == {}
    assert config.json()["diagnostics"] == []
    assert config.json()["showCellLogs"] is True


def test_runtime_injection_uses_structural_html_tags(
    notebook_path: Path,
) -> None:
    studio = _configured(notebook_path)
    studio.views["dashboard"].template.write_text(
        """\
<!doctype html>
<html>
  <head>
    <script>const headMarker = "</head>";</script>
  </head>
  <body>
    <main id="app-shell"></main>
    <script>const bodyMarker = "</body>";</script>
  </body>
</html>
""",
        encoding="utf-8",
    )

    with TestClient(create_asgi_app(studio.notebook)) as client:
        response = client.get("/")

    assert response.status_code == 200
    assert '<script>const headMarker = "</head>";</script>' in response.text
    assert '<script>const bodyMarker = "</body>";</script>' in response.text
    assert response.text.index("runtime.css") < response.text.index("const headMarker")
    assert response.text.index('id="marimo-runtime-root"') > response.text.index(
        "const bodyMarker"
    )


def test_each_view_has_scoped_runtime_routes(notebook_path: Path) -> None:
    studio = _configured(notebook_path)

    def configure(config: MutableMapping[str, object]) -> None:
        config["preserve_session"] = True
        config["show_cell_logs"] = False

    update_notebook_config(studio.notebook, configure)

    with TestClient(create_asgi_app(studio.notebook)) as client:
        dashboard = client.get("/_marimo-studio/views/dashboard/config").json()
        executive = client.get("/_marimo-studio/views/executive/config").json()
        cell = client.get("/_marimo-studio/views/executive/cells/result")
        stylesheet = client.get("/executive/app.css")
        views = client.get("/_marimo-studio/views").json()

    assert dashboard["view"] == "dashboard"
    assert dashboard["views"] == ["dashboard", "executive"]
    dashboard_support = urlsplit(dashboard["supportUrl"])
    executive_support = urlsplit(executive["supportUrl"])
    assert dashboard_support.path == "/_marimo-studio/views/dashboard"
    assert set(dashboard["valueBindings"]) == {"doubled"}
    assert set(dashboard["outputBindings"]) == {"doubled"}
    assert executive_support.path == "/_marimo-studio/views/executive"
    assert set(executive["valueBindings"]) == {"x"}
    assert set(executive["outputBindings"]) == {"x"}
    assert dashboard["cellBindings"]["result"] == executive["cellBindings"]["result"]
    assert cell.text == '<marimo-cell name="result"></marimo-cell>'
    assert stylesheet.status_code == 200
    assert views == {
        "schema": 1,
        "default_view": "dashboard",
        "views": ["dashboard", "executive"],
    }
    assert dashboard["runtime"]["data"]["preserveSession"] is True
    assert dashboard["showCellLogs"] is False
    expected_instance = server_instance_id(dashboard["runtime"]["data"]["serverToken"])
    assert parse_qs(dashboard_support.query)[SERVER_INSTANCE_QUERY_PARAM] == [
        expected_instance
    ]
    assert parse_qs(executive_support.query)[SERVER_INSTANCE_QUERY_PARAM] == [
        expected_instance
    ]


def test_directory_support_routes_keep_notebook_identity(tmp_path: Path) -> None:
    from marimo._server.workspace._directory import DirectoryWorkspace

    first = tmp_path / "first.py"
    second = tmp_path / "second.py"
    first.write_text(notebook_source(tmp_path / "first-output"), encoding="utf-8")
    second.write_text(notebook_source(tmp_path / "second-output"), encoding="utf-8")
    _configured(first)
    _configured(second)
    app = _marimo_app(first)
    _edit_mode(app)
    manager = _session_manager(app)
    manager.workspace = DirectoryWorkspace(str(tmp_path), include_markdown=False)
    manager.get_session = Mock(
        return_value=SimpleNamespace(
            initialization_id="second.py",
            app_file_manager=SimpleNamespace(path=str(second)),
        )
    )
    authored_root = authored_view_root_url("", "first.py")

    with TestClient(app) as client:
        config = client.get(
            "/_marimo-studio/views/dashboard/config?file=first.py"
        ).json()
        cross_notebook = client.post(
            "/_marimo-studio/views/dashboard/values?file=first.py",
            headers={"Marimo-Session-Id": "second-session"},
            json={"revision": config["revision"], "selectors": ["doubled"]},
        )
        created = client.post(
            "/_marimo-studio/views?file=first.py",
            headers={"Marimo-Server-Token": config["runtime"]["data"]["serverToken"]},
            json={"name": "detail"},
        )
        marimo_resource = client.get(f"{authored_root}dashboard/public-files-sw.js")
        authored_document = client.get(
            f"{authored_root}dashboard/?region=us",
            follow_redirects=False,
        )

    assert cross_notebook.status_code == 409
    assert cross_notebook.json()["error"] == "unknown-session"
    assert config["rootUrl"] == "/"
    assert config["publicRootUrl"] == "/?file=first.py"
    assert config["documentRootUrl"] == authored_root
    _assert_server_runtime(config["runtime"]["data"], "/")
    assert config["runtime"]["data"]["file"] == "first.py"
    assert created.status_code == 201
    assert created.json()["studio_url"] == "/studio/detail/?file=first.py"
    assert created.json()["view_url"] == "/detail/?file=first.py"
    assert marimo_resource.status_code == 200
    assert authored_document.status_code == 307
    assert authored_document.headers["location"] == (
        "/dashboard/?file=first.py&region=us"
    )


def test_mounted_directory_routes_preserve_notebook_identity(tmp_path: Path) -> None:
    from marimo._server.workspace._directory import DirectoryWorkspace

    notebook = tmp_path / "nested" / "analysis.py"
    notebook.parent.mkdir()
    notebook.write_text(notebook_source(tmp_path / "output"), encoding="utf-8")
    _configured(notebook)
    child = _marimo_app(notebook, path="/base", programmatic=True)
    _edit_mode(child)
    _session_manager(child).workspace = DirectoryWorkspace(
        str(tmp_path),
        include_markdown=False,
    )
    parent = Starlette(routes=[Mount("/parent", app=child)])
    file_key = "nested/analysis.py"
    authored_root = authored_view_root_url("/parent/base", file_key)

    with TestClient(parent) as client:
        config = client.get(
            f"/parent/base/_marimo-studio/views/dashboard/config?file={file_key}"
        ).json()
        authored_document = client.get(
            f"{authored_root}dashboard/?region=us",
            follow_redirects=False,
        )

    assert config["rootUrl"] == "/parent/base/"
    assert config["publicRootUrl"] == ("/parent/base/?file=nested%2Fanalysis.py")
    _assert_server_runtime(config["runtime"]["data"], "/parent/base/")
    assert config["runtime"]["data"]["file"] == file_key
    assert authored_document.headers["location"] == (
        "/parent/base/dashboard/?file=nested%2Fanalysis.py&region=us"
    )


def test_directory_auth_precedes_notebook_configuration(tmp_path: Path) -> None:
    from marimo._server.workspace._directory import DirectoryWorkspace

    configured = tmp_path / "configured.py"
    plain = tmp_path / "plain.py"
    configured.write_text(
        notebook_source(tmp_path / "configured-output"),
        encoding="utf-8",
    )
    plain.write_text(notebook_source(tmp_path / "plain-output"), encoding="utf-8")
    _configured(configured)
    app = _marimo_app(configured, token="test-token")
    _edit_mode(app)
    _session_manager(app).workspace = DirectoryWorkspace(
        str(tmp_path),
        include_markdown=False,
    )

    with TestClient(app) as client:
        responses = [
            client.get(
                f"{route}?file={notebook}",
                follow_redirects=False,
            )
            for notebook in ("configured.py", "plain.py")
            for route in ("/_marimo-studio/status", "/dashboard/")
        ]
        json_responses = [
            client.get(
                f"/_marimo-studio/status?file={notebook}",
                headers={
                    "Accept": "application/json",
                    **({"Authorization": "Bearer invalid-token"} if invalid else {}),
                },
                follow_redirects=False,
            )
            for notebook in ("configured.py", "plain.py")
            for invalid in (False, True)
        ]
        lookalike = client.get(
            "/_marimo-studio-tools?file=configured.py",
            headers={"Accept": "application/json"},
            follow_redirects=False,
        )

    assert all(response.status_code == 303 for response in responses)
    assert all(
        response.headers["location"].startswith("/auth/login?")
        for response in responses
    )
    assert all(response.status_code == 401 for response in json_responses)
    assert all(
        response.json()["error"] == "authentication-required"
        for response in json_responses
    )
    assert lookalike.status_code == 404


def test_run_mode_serves_the_configured_wasm_runtime_and_source(
    notebook_path: Path,
) -> None:
    studio = _configured(notebook_path)

    with TestClient(create_asgi_app(studio.notebook)) as client:
        unavailable = client.get("/_marimo-studio/views/dashboard/config?runtime=wasm")

    source = studio.notebook.read_text(encoding="utf-8")
    studio.notebook.write_text(
        source.replace(
            "# [tool.marimo-studio]",
            '# [tool.uv]\n# prerelease = "allow"\n#\n# [tool.marimo-studio]',
            1,
        ),
        encoding="utf-8",
    )

    def enable_wasm(config: MutableMapping[str, object]) -> None:
        config["runtime"] = "wasm"
        config["runtimes"] = ["server", "wasm"]

    update_notebook_config(studio.notebook, enable_wasm)
    configured = studio.notebook.read_bytes()
    with TestClient(create_asgi_app(studio.notebook)) as client:
        page = client.get("/")
        dashboard = client.get("/_marimo-studio/views/dashboard/config").json()
        executive = client.get("/_marimo-studio/views/executive/config").json()

    assert unavailable.status_code == 400
    assert unavailable.json()["error"] == "runtime-unavailable"
    assert '"runtime":"wasm"' in page.text
    assert dashboard["runtime"]["id"] == "wasm"
    assert dashboard["runtime"]["available"] == ["server", "wasm"]
    assert dashboard["runtime"]["instance"] == executive["runtime"]["instance"]
    code = dashboard["runtime"]["data"]["code"]
    compile(code, "notebook.py", "exec")
    assert "[tool.marimo-studio]" not in code
    assert "[tool.uv]" not in code
    assert '"marimo-studio"' not in code.split("import marimo", 1)[0]
    assert studio.notebook.read_bytes() == configured


def test_edit_mode_offers_both_preview_runtimes(notebook_path: Path) -> None:
    studio = _configured(notebook_path)
    app = _marimo_app(studio.notebook)
    _edit_mode(app)

    with TestClient(app) as client:
        config = client.get(
            "/_marimo-studio/views/dashboard/config?runtime=wasm"
        ).json()
        workspace = client.get("/studio/dashboard/")

    assert config["runtime"]["id"] == "wasm"
    assert config["runtime"]["available"] == ["server", "wasm"]
    bootstrap = _studio_bootstrap(workspace.text)
    assert bootstrap["schema"] == 1
    assert bootstrap["selectedView"] == "dashboard"
    assert bootstrap["views"] == ["dashboard", "executive"]
    assert bootstrap["runtimes"] == [
        {"id": "server", "label": "Server"},
        {"id": "wasm", "label": "WebAssembly"},
    ]
    assert bootstrap["urls"]["query"] == "/_marimo-studio/query"


def test_studio_runtime_config_targets_its_editor_session(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    studio = _configured(notebook_path)
    app = _marimo_app(studio.notebook)
    _edit_mode(app)
    captured: dict[str, object] = {}

    async def session_for_client(
        _clients: StudioClientRegistry,
        client_id: str,
    ) -> str | None:
        captured["client_id"] = client_id
        return "s_123456"

    def runtime_config(
        _snapshot: object,
        _context: object,
        _runtimes: object,
        runtime_id: str | None,
        session_id: str | None,
        binding_id: str | None,
    ) -> dict[str, object]:
        captured["runtime_id"] = runtime_id
        captured["session_id"] = session_id
        captured["binding_id"] = binding_id
        return {"runtime": {"id": "server"}}

    def attach_session(
        _attachment: object,
        _context: object,
        consumer_id: str,
        session_id: str,
    ) -> bool:
        captured["consumer_id"] = consumer_id
        captured["editor_session_id"] = session_id
        return True

    monkeypatch.setattr(
        StudioClientRegistry,
        "session_for_client",
        session_for_client,
    )
    monkeypatch.setattr(
        "marimo_studio._server.runtime_config_api.build_runtime_config",
        runtime_config,
    )
    monkeypatch.setattr(
        "marimo_studio._compat.server.session_state.PrivateSessionState.exists",
        lambda _sessions, _context, _session_id: True,
    )
    monkeypatch.setattr(
        "marimo_studio._compat.server.existing_session.PrivateExistingSessionAttachment.attach",
        attach_session,
    )

    with TestClient(app) as client:
        response = client.get(
            "/_marimo-studio/views/dashboard/config",
            params={
                "runtime": "server",
                "marimo_studio_client": "browser-client-1234",
            },
            headers={"Marimo-Studio-Preview-Session-Id": "s_view01"},
        )
        invalid = client.get(
            "/_marimo-studio/views/dashboard/config",
            params={"marimo_studio_client": "browser-client-1234"},
        )

    assert response.status_code == 200
    assert response.json()["editorSessionId"] == "s_123456"
    assert captured == {
        "client_id": "browser-client-1234",
        "runtime_id": "server",
        "session_id": "s_123456",
        "binding_id": "s_123456",
        "consumer_id": "s_view01",
        "editor_session_id": "s_123456",
    }
    assert invalid.status_code == 400
    assert invalid.json()["error"] == "invalid-studio-session"


def test_studio_runtime_config_resolves_session_after_snapshot(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    studio = _configured(notebook_path)
    app = _marimo_app(studio.notebook)
    _edit_mode(app)
    active = {"session_id": "s_123456"}
    sessions = {"s_123456": object(), "s_654321": object()}
    captured: dict[str, object] = {}

    async def snapshot_async(
        _presentation: NotebookPresentation,
        _view_name: str,
    ) -> object:
        active["session_id"] = "s_654321"
        return object()

    async def session_for_client(
        _clients: StudioClientRegistry,
        _client_id: str,
    ) -> str:
        return active["session_id"]

    def runtime_config(
        _snapshot: object,
        _context: object,
        _runtimes: object,
        _runtime_id: str | None,
        session_id: str | None,
        binding_id: str | None,
    ) -> dict[str, object]:
        captured["session_id"] = session_id
        captured["binding_id"] = binding_id
        return {"runtime": {"id": "server"}}

    def attach_session(
        _attachment: object,
        _context: object,
        _consumer_id: str,
        session_id: str,
    ) -> bool:
        captured["editor_session"] = sessions[session_id]
        return True

    monkeypatch.setattr(NotebookPresentation, "snapshot_async", snapshot_async)
    monkeypatch.setattr(
        StudioClientRegistry,
        "session_for_client",
        session_for_client,
    )
    monkeypatch.setattr(
        "marimo_studio._server.runtime_config_api.build_runtime_config",
        runtime_config,
    )
    monkeypatch.setattr(
        "marimo_studio._compat.server.session_state.PrivateSessionState.exists",
        lambda _sessions, _context, session_id: session_id in sessions,
    )
    monkeypatch.setattr(
        "marimo_studio._compat.server.existing_session.PrivateExistingSessionAttachment.attach",
        attach_session,
    )

    with TestClient(app) as client:
        response = client.get(
            "/_marimo-studio/views/dashboard/config",
            params={
                "runtime": "server",
                "marimo_studio_client": "browser-client-1234",
            },
            headers={"Marimo-Studio-Preview-Session-Id": "s_view01"},
        )

    assert response.status_code == 200
    assert response.json()["editorSessionId"] == "s_654321"
    assert captured == {
        "session_id": "s_654321",
        "binding_id": "s_654321",
        "editor_session": sessions["s_654321"],
    }


def test_runtime_config_keeps_parallel_preview_bootstraps(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    studio = _configured(notebook_path)
    app = _marimo_app(studio.notebook)
    _edit_mode(app)

    async def session_for_client(
        _clients: StudioClientRegistry,
        _client_id: str,
    ) -> str:
        return "s_123456"

    monkeypatch.setattr(
        StudioClientRegistry,
        "session_for_client",
        session_for_client,
    )
    monkeypatch.setattr(
        "marimo_studio._server.runtime_config_api.build_runtime_config",
        lambda *_args, **_kwargs: {"runtime": {"id": "server"}},
    )
    monkeypatch.setattr(
        "marimo_studio._compat.server.session_state.PrivateSessionState.exists",
        lambda _sessions, _context, _session_id: True,
    )
    monkeypatch.setattr(
        "marimo_studio._compat.server.existing_session.PrivateExistingSessionAttachment.attach",
        lambda _attachment, _context, _consumer_id, _session_id: True,
    )

    with TestClient(app) as client:
        statuses = [
            client.get(
                "/_marimo-studio/views/dashboard/config",
                params={
                    "runtime": "server",
                    "marimo_studio_client": "browser-client-1234",
                },
                headers={
                    "Marimo-Studio-Preview-Session-Id": f"s_v{index:05d}",
                },
            ).status_code
            for index in range(2)
        ]

    assert statuses == [200, 200]


def test_wasm_runtime_updates_projection_specs_without_restarting_notebook(
    notebook_path: Path,
) -> None:
    studio = _configured(notebook_path)

    def enable_wasm(config: MutableMapping[str, object]) -> None:
        config["runtime"] = "wasm"
        config["runtimes"] = ["server", "wasm"]

    update_notebook_config(studio.notebook, enable_wasm)
    template = studio.views["dashboard"].template
    with TestClient(create_asgi_app(studio.notebook)) as client:
        first = client.get("/_marimo-studio/views/dashboard/config").json()
        template.write_text(
            template.read_text(encoding="utf-8").replace(
                '<marimo-output value="doubled"',
                '<marimo-output value="doubled.real"',
                1,
            ),
            encoding="utf-8",
        )
        second = client.get("/_marimo-studio/views/dashboard/config").json()
        studio.notebook.write_text(
            studio.notebook.read_text(encoding="utf-8").replace(
                "doubled = x * 2",
                "doubled = x * 3",
                1,
            ),
            encoding="utf-8",
        )
        third = client.get("/_marimo-studio/views/dashboard/config").json()

    assert first["runtime"]["instance"] == second["runtime"]["instance"]
    assert first["runtime"]["data"]["code"] != second["runtime"]["data"]["code"]
    assert "doubled" in first["runtime"]["data"]["outputSpecs"]
    assert "doubled.real" in second["runtime"]["data"]["outputSpecs"]
    assert second["runtime"]["instance"] != third["runtime"]["instance"]


def test_edit_workspace_queues_public_query_state(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    studio = _configured(notebook_path)
    app = _marimo_app(studio.notebook)
    _edit_mode(app)
    received: list[dict[str, str | list[str]]] = []
    sessions = {
        "browser-client-1234": "s_123456",
        "browser-client-5678": "s_654321",
    }
    claimed_operations: set[tuple[str, str]] = set()

    async def claim_query_operation(
        _self: StudioClientRegistry,
        client_id: str,
        operation_id: str,
        expected_session_id: str,
    ) -> bool:
        if sessions.get(client_id) != expected_session_id:
            return False
        operation = (client_id, operation_id)
        if operation in claimed_operations:
            return False
        claimed_operations.add(operation)
        return True

    monkeypatch.setattr(
        StudioClientRegistry,
        "session_for_client",
        lambda _self, client_id: asyncio.sleep(0, result=sessions.get(client_id)),
    )
    monkeypatch.setattr(
        StudioClientRegistry,
        "claim_query_operation",
        claim_query_operation,
    )
    monkeypatch.setattr(
        "marimo_studio._compat.server.session_state.PrivateSessionState.exists",
        lambda _sessions, _context, session_id: session_id in sessions.values(),
    )
    monkeypatch.setattr(
        "marimo_studio._compat.kernel_values.host.PrivateKernelProjectionHost.sync_query",
        lambda _host, _context, session_id, query, operation_id: received.append(
            {"session": session_id, "operation": operation_id, **query}
        ),
    )
    headers = {"Marimo-Server-Token": str(_session_manager(app).skew_protection_token)}

    with TestClient(app) as client:
        response = client.post(
            "/_marimo-studio/query",
            headers=headers,
            json={
                "clientId": "browser-client-1234",
                "operationId": "query-1",
                "query": "?region=emea&region=apac&empty=",
            },
        )
        duplicate = client.post(
            "/_marimo-studio/query",
            headers=headers,
            json={
                "clientId": "browser-client-1234",
                "operationId": "query-1",
                "query": "?region=emea&region=apac&empty=",
            },
        )
        second = client.post(
            "/_marimo-studio/query",
            headers=headers,
            json={
                "clientId": "browser-client-5678",
                "operationId": "query-2",
                "query": "?region=apac",
            },
        )
        private = client.post(
            "/_marimo-studio/query",
            headers=headers,
            json={
                "clientId": "browser-client-1234",
                "operationId": "query-3",
                "query": (
                    "?region=public&session_id=s_private&runtime=wasm"
                    "&marimo_studio_query_operation=query_injected"
                ),
            },
        )
        monkeypatch.setattr(
            "marimo_studio._server.query_api.has_edit_access",
            lambda _scope: False,
        )
        denied = client.post(
            "/_marimo-studio/query",
            headers=headers,
            json={
                "clientId": "browser-client-1234",
                "operationId": "query-4",
                "query": "?region=private",
            },
        )

    assert response.status_code == 202
    assert duplicate.status_code == 202
    assert second.status_code == 202
    assert private.status_code == 400
    assert private.json()["error"] == "invalid-query"
    assert denied.status_code == 403
    assert denied.json()["error"] == "edit-access-required"
    assert received == [
        {
            "session": "s_123456",
            "operation": "query-1",
            "region": ["emea", "apac"],
            "empty": "",
        },
        {"session": "s_654321", "operation": "query-2", "region": "apac"},
    ]


def test_edit_workspace_retries_query_after_an_editor_session_rebind(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    studio = _configured(notebook_path)
    app = _marimo_app(studio.notebook)
    _edit_mode(app)
    queued: list[object] = []

    monkeypatch.setattr(
        StudioClientRegistry,
        "session_for_client",
        lambda _self, _client_id: asyncio.sleep(0, result="s_123456"),
    )

    async def reject_stale_claim(
        _self: StudioClientRegistry,
        _client_id: str,
        _operation_id: str,
        expected_session_id: str,
    ) -> None:
        assert expected_session_id == "s_123456"
        return None

    monkeypatch.setattr(
        StudioClientRegistry,
        "claim_query_operation",
        reject_stale_claim,
    )
    monkeypatch.setattr(
        "marimo_studio._compat.server.session_state.PrivateSessionState.exists",
        lambda _sessions, _context, session_id: session_id == "s_123456",
    )
    monkeypatch.setattr(
        "marimo_studio._compat.kernel_values.host.PrivateKernelProjectionHost.sync_query",
        lambda *_args: queued.append(object()),
    )
    headers = {"Marimo-Server-Token": str(_session_manager(app).skew_protection_token)}

    with TestClient(app) as client:
        response = client.post(
            "/_marimo-studio/query",
            headers=headers,
            json={
                "clientId": "browser-client-1234",
                "operationId": "query-1",
                "query": "?region=emea",
            },
        )

    assert response.status_code == 409
    assert response.json()["error"] == "query-session-unavailable"
    assert response.json()["transient"] is True
    assert queued == []


def test_server_runtime_instance_changes_with_transport_token(
    notebook_path: Path,
) -> None:
    from marimo._server.tokens import SkewProtectionToken

    studio = _configured(notebook_path)
    app = _marimo_app(studio.notebook)
    manager = _session_manager(app)

    with TestClient(app) as client:
        first = client.get("/_marimo-studio/views/dashboard/config").json()
        manager._token_manager.skew_protection_token = SkewProtectionToken.random()
        second = client.get("/_marimo-studio/views/dashboard/config").json()

    assert (
        first["runtime"]["data"]["serverToken"]
        != second["runtime"]["data"]["serverToken"]
    )
    assert first["runtime"]["instance"] != second["runtime"]["instance"]


def test_server_runtime_instance_stays_stable_when_lookup_session_connects(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    studio = _configured(notebook_path)
    app = _marimo_app(studio.notebook)
    _edit_mode(app)
    monkeypatch.setattr(
        "marimo_studio._compat.server.session_state.PrivateSessionState.live_cells",
        lambda _sessions, _context, _session_id: None,
    )

    with TestClient(app) as client:
        initial = client.get("/_marimo-studio/views/dashboard/config").json()
        connected = client.get(
            "/_marimo-studio/views/dashboard/config",
            headers={"Marimo-Session-Id": "s_123456"},
        ).json()

    assert initial["runtime"]["instance"] == connected["runtime"]["instance"]


def test_deleted_named_cell_keeps_the_view_live_until_repaired(
    tmp_path: Path,
) -> None:
    notebook = tmp_path / "named.py"
    source = notebook_source(tmp_path / "executed").replace(
        "@app.cell\ndef _():",
        "@app.cell\ndef imports():",
        1,
    )
    notebook.write_text(source, encoding="utf-8")
    ensure_view(notebook)
    studio = load_studio(notebook)
    _set_shell(studio, "dashboard", '<marimo-cell name="imports"></marimo-cell>')
    configured_source = notebook.read_text(encoding="utf-8")

    with TestClient(create_asgi_app(notebook)) as client:
        notebook.write_text(
            configured_source.replace("def imports():", "def _():", 1),
            encoding="utf-8",
        )
        page = client.get("/")
        broken = client.get("/_marimo-studio/views/dashboard/config").json()
        fragment = client.get("/_marimo-studio/views/dashboard/cells/imports")

        notebook.write_text(configured_source, encoding="utf-8")
        repaired = client.get("/_marimo-studio/views/dashboard/config").json()

    assert page.status_code == 200
    assert '<marimo-cell name="imports"></marimo-cell>' in page.text
    assert "imports" not in broken["cellBindings"]
    assert len(broken["diagnostics"]) == 1
    diagnostic = broken["diagnostics"][0]
    assert diagnostic["code"] == "cell-not-found"
    assert diagnostic["severity"] == "error"
    assert diagnostic["view"] == "dashboard"
    assert diagnostic["projection"] == "cell"
    assert diagnostic["target"] == "imports"
    assert diagnostic["source"]["path"] == str(
        studio.views["dashboard"].template.relative_to(notebook.parent)
    )
    assert diagnostic["source"]["line"] > 0
    assert diagnostic["hint"] == ""
    assert fragment.text == '<marimo-cell name="imports"></marimo-cell>'
    assert repaired["diagnostics"] == []
    assert repaired["cellBindings"]["imports"] == {
        "kind": "name",
        "value": "imports",
    }


def test_notebook_syntax_error_has_a_browser_safe_repair_diagnostic(
    notebook_path: Path,
) -> None:
    studio = _configured(notebook_path)

    with TestClient(create_asgi_app(studio.notebook)) as client:
        source = studio.notebook.read_text(encoding="utf-8")
        studio.notebook.write_text(
            source.replace("    doubled = x * 2", "    42doubled = x * 2"),
            encoding="utf-8",
        )
        config = client.get("/_marimo-studio/views/dashboard/config")
        page = client.get("/")

    expected_message = (
        "Marimo cannot inspect the notebook while a cell contains invalid code."
    )
    expected_hint = "Fix the highlighted cell in Marimo, then save it again."
    assert config.status_code == 500
    assert config.json() == {
        "error": "notebook-source-error",
        "message": expected_message,
        "hint": expected_hint,
    }
    assert page.status_code == 500
    assert page.headers["Marimo-Studio-Error"] == "notebook-source-error"
    assert page.headers["Marimo-Studio-Hint"] == expected_hint
    assert expected_message in page.text
    assert str(notebook_path.parent) not in config.text
    assert str(notebook_path.parent) not in page.text


def test_template_error_has_a_repair_diagnostic(notebook_path: Path) -> None:
    studio = _configured(notebook_path)
    template = studio.views["dashboard"].template
    template.write_text(
        template.read_text(encoding="utf-8").replace(
            'id="app-shell"',
            'id="application"',
        ),
        encoding="utf-8",
    )

    with TestClient(create_asgi_app(studio.notebook)) as client:
        config = client.get("/_marimo-studio/views/dashboard/config")
        page = client.get("/")

    expected_hint = "Fix the view template, then save it again."
    assert config.status_code == 500
    assert config.json()["error"] == "template-error"
    assert config.json()["hint"] == expected_hint
    assert page.status_code == 500
    assert page.headers["Marimo-Studio-Error"] == "template-error"
    assert page.headers["Marimo-Studio-Hint"] == expected_hint
    assert "expected one element with id" in page.text


def test_edit_view_error_document_watches_for_source_repairs(
    notebook_path: Path,
) -> None:
    studio = _configured(notebook_path)
    template = studio.views["dashboard"].template
    template.write_text(
        template.read_text(encoding="utf-8").replace(
            'id="app-shell"',
            'id="application"',
        ),
        encoding="utf-8",
    )
    app = _marimo_app(studio.notebook)
    _edit_mode(app)
    _session_manager(app).get_session_by_file_key = Mock(return_value=object())

    with TestClient(app) as client:
        page = client.get("/dashboard/")

    assert page.status_code == 500
    assert page.headers["Marimo-Studio-Error"] == "template-error"
    assert "View needs repair" in page.text
    assert "/_marimo-studio/dev/events" in page.text


def test_named_cell_binding_waits_for_active_name_and_source_sync(
    tmp_path: Path,
) -> None:
    notebook = tmp_path / "named.py"
    notebook.write_text(
        notebook_source(tmp_path / "executed").replace(
            "@app.cell\ndef _():",
            "@app.cell\ndef imports():",
            1,
        ),
        encoding="utf-8",
    )
    ensure_view(notebook)
    studio = load_studio(notebook)
    _set_shell(studio, "dashboard", '<marimo-cell name="imports"></marimo-cell>')
    static = load_static_notebook(notebook)
    app = _marimo_app(notebook)
    _edit_mode(app)
    session = SimpleNamespace(
        document=SimpleNamespace(
            cells=tuple(
                SimpleNamespace(code=cell.code, id=cell.runtime_id, name="_")
                for cell in static.cells
            )
        )
    )
    _session_manager(app).get_session_by_file_key = Mock(return_value=session)

    with TestClient(app) as client:
        name_pending = client.get("/_marimo-studio/views/dashboard/config")
        named_rows = tuple(
            SimpleNamespace(
                code=cell.code,
                id=cell.runtime_id,
                name=cell.name,
            )
            for cell in static.cells
        )
        stale_rows = list(named_rows)
        stale_rows[0] = SimpleNamespace(
            code=stale_rows[0].code.replace("x = 2", "x = 1"),
            id=stale_rows[0].id,
            name=stale_rows[0].name,
        )
        session.document.cells = tuple(stale_rows)
        source_pending = client.get("/_marimo-studio/views/dashboard/config")
        session.document.cells = named_rows
        ready = client.get("/_marimo-studio/views/dashboard/config")

    for pending in (name_pending, source_pending):
        assert pending.status_code == 409
        assert pending.json()["error"] == "runtime-sync-pending"
        assert pending.json()["transient"] is True
    assert ready.status_code == 200
    assert ready.json()["cellBindings"]["imports"] == {
        "kind": "name",
        "value": "imports",
    }


def test_unrelated_named_cell_does_not_block_the_selected_view(
    tmp_path: Path,
) -> None:
    notebook = tmp_path / "named.py"
    source = notebook_source(tmp_path / "executed").replace(
        "@app.cell\ndef _():",
        "@app.cell\ndef imports():",
        1,
    )
    source = source.replace(
        "@app.cell\ndef _(x):",
        "@app.cell\ndef result(x):",
        1,
    )
    notebook.write_text(source, encoding="utf-8")
    ensure_view(notebook)
    studio = load_studio(notebook)
    _set_shell(studio, "dashboard", '<marimo-cell name="imports"></marimo-cell>')
    static = load_static_notebook(notebook)
    rows = (
        SimpleNamespace(
            code=static.cells[0].code,
            id=static.cells[0].runtime_id,
            name="imports",
        ),
        SimpleNamespace(
            code=static.cells[1].code,
            id=static.cells[1].runtime_id,
            name="_",
        ),
    )
    app = _marimo_app(notebook)
    _edit_mode(app)
    _session_manager(app).get_session_by_file_key = Mock(
        return_value=SimpleNamespace(document=SimpleNamespace(cells=rows))
    )

    with TestClient(app) as client:
        response = client.get("/_marimo-studio/views/dashboard/config")

    assert response.status_code == 200
    assert response.json()["cellBindings"] == {
        "imports": {"kind": "name", "value": "imports"}
    }


def test_anonymous_bindings_wait_for_live_cell_identities(
    notebook_path: Path,
) -> None:
    studio = _configured(notebook_path)
    app = _marimo_app(studio.notebook)
    _edit_mode(app)
    static = load_static_notebook(studio.notebook)
    rows = tuple(
        SimpleNamespace(code=cell.code, id=f"live-{index}", name=cell.name)
        for index, cell in enumerate(static.cells)
    )
    session = SimpleNamespace(
        document=SimpleNamespace(
            cells=(
                SimpleNamespace(code="unrelated = 1", id="live-unrelated", name="_"),
            )
        )
    )
    _session_manager(app).get_session_by_file_key = Mock(return_value=session)

    with TestClient(app) as client:
        pending = client.get("/_marimo-studio/views/dashboard/config")
        session.document.cells = rows
        dashboard = client.get("/_marimo-studio/views/dashboard/config").json()
        executive = client.get("/_marimo-studio/views/executive/config").json()

    assert pending.status_code == 409
    assert pending.json()["error"] == "runtime-sync-pending"
    assert pending.json()["transient"] is True
    assert dashboard["cellBindings"]["result"] == {
        "kind": "id",
        "value": "live-1",
    }
    assert executive["valueBindings"]["x"]["cell"] == {
        "kind": "id",
        "value": "live-0",
    }
    assert dashboard["valueBindings"]["doubled"]["cell"] == {
        "kind": "id",
        "value": "live-1",
    }


def test_presentation_revision_tracks_view_and_source_identity(
    notebook_path: Path,
) -> None:
    studio = _configured(notebook_path)
    shared = (
        "<html><head><link rel='stylesheet' href='app.css'></head>"
        "<body><main id='app-shell'></main></body></html>"
    )
    for view in studio.views.values():
        view.template.write_text(shared, encoding="utf-8")
    timestamp = studio.views["dashboard"].template.stat().st_mtime_ns
    for view in studio.views.values():
        os.utime(view.template, ns=(timestamp, timestamp))
    template = studio.views["dashboard"].template
    stylesheet = studio.views["dashboard"].root / "app.css"

    with TestClient(create_asgi_app(studio.notebook)) as client:
        dashboard = client.get("/")
        dashboard_config = client.get("/_marimo-studio/views/dashboard/config").json()
        executive = client.get("/executive/")
        stat = template.stat()
        template.write_text(
            shared.replace("app.css", "alt.css"),
            encoding="utf-8",
        )
        os.utime(template, ns=(stat.st_atime_ns, stat.st_mtime_ns))
        edited_config = client.get("/_marimo-studio/views/dashboard/config").json()
        edited = client.get("/")
        stylesheet.write_text("body { color: red; }", encoding="utf-8")
        styled_config = client.get("/_marimo-studio/views/dashboard/config").json()

    dashboard_revision = dashboard.headers["Marimo-Studio-Revision"]
    edited_revision = edited.headers["Marimo-Studio-Revision"]
    assert dashboard_config["revision"] == dashboard_revision
    assert executive.headers["Marimo-Studio-Revision"] != dashboard_revision
    assert edited_config["revision"] == edited_revision
    assert edited_revision != dashboard_revision
    assert styled_config["revision"] != edited_revision


def test_root_document_tracks_a_changed_default_view(notebook_path: Path) -> None:
    studio = _configured(notebook_path)

    with TestClient(create_asgi_app(studio.notebook)) as client:
        dashboard = client.get("/")
        dashboard_config = client.get("/_marimo-studio/views/dashboard/config").json()

        def select_executive(config: MutableMapping[str, object]) -> None:
            config["default"] = "executive"

        update_notebook_config(studio.notebook, select_executive)
        executive = client.get("/")
        config = client.get("/_marimo-studio/views/executive/config").json()

    dashboard_support = urlsplit(dashboard.headers["Marimo-Studio-Support-Url"])
    executive_support = urlsplit(executive.headers["Marimo-Studio-Support-Url"])
    assert dashboard_support.path.endswith("/views/dashboard")
    assert executive_support.path.endswith("/views/executive")
    assert parse_qs(dashboard_support.query)[SERVER_INSTANCE_QUERY_PARAM] == [
        dashboard_config["runtime"]["data"]["serverInstance"]
    ]
    assert parse_qs(executive_support.query)[SERVER_INSTANCE_QUERY_PARAM] == [
        config["runtime"]["data"]["serverInstance"]
    ]
    assert executive.headers["Marimo-Studio-Revision"] == config["revision"]
    assert (
        executive.headers["Marimo-Studio-Revision"]
        != dashboard.headers["Marimo-Studio-Revision"]
    )


def test_edit_runtime_matches_layout_equivalent_live_cells(tmp_path: Path) -> None:
    serialized = '''\
mo.md(f"""
## Report
""")
'''
    legacy = '''\
mo.md(
    f"""
    ## Report
    """
)
'''
    notebook = tmp_path / "markdown.py"
    notebook.write_text(
        f"""\
import marimo

__generated_with = "{marimo.__version__}"
app = marimo.App()


@app.cell
def _():
    import marimo as mo
    return (mo,)


@app.cell
def _(mo):
    {serialized.replace(chr(10), chr(10) + "    ").rstrip()}
    return
""",
        encoding="utf-8",
    )
    ensure_view(notebook)
    studio = load_studio(notebook)
    bind_cell(studio, "report", 1)
    studio = load_studio(notebook)
    _set_shell(studio, "dashboard", '<marimo-cell name="report"></marimo-cell>')
    static = load_static_notebook(notebook)
    app = _marimo_app(notebook)
    _edit_mode(app)
    rows = (
        SimpleNamespace(code='inserted = "before"', id="live-inserted", name="_"),
        SimpleNamespace(code=static.cells[0].code, id="live-import", name="_"),
        SimpleNamespace(code=legacy, id="live-report", name="_"),
    )
    session = SimpleNamespace(document=SimpleNamespace(cells=rows))
    _session_manager(app).get_session_by_file_key = Mock(return_value=session)

    with TestClient(app) as client:
        response = client.get("/_marimo-studio/views/dashboard/config")

    assert response.status_code == 200
    assert response.json()["cellBindings"]["report"] == {
        "kind": "id",
        "value": "live-report",
    }


def test_run_runtime_refreshes_bindings_for_each_browser_session(
    notebook_path: Path,
) -> None:
    studio = _configured(notebook_path)
    app = _marimo_app(studio.notebook)
    static = load_static_notebook(studio.notebook)

    def session(prefix: str, *, inserted: bool) -> SimpleNamespace:
        rows = tuple(
            SimpleNamespace(code=cell.code, id=f"{prefix}-{index}", name=cell.name)
            for index, cell in enumerate(static.cells)
        )
        if inserted:
            rows = (
                SimpleNamespace(
                    code='inserted = "before"',
                    id=f"{prefix}-inserted",
                    name="_",
                ),
                *rows,
            )
        return SimpleNamespace(
            initialization_id=str(studio.notebook),
            app_file_manager=SimpleNamespace(path=str(studio.notebook)),
            document=SimpleNamespace(cells=rows),
        )

    sessions = {
        "s_first1": session("first", inserted=False),
        "s_second": session("second", inserted=True),
    }
    _session_manager(app).get_session = Mock(
        side_effect=lambda session_id: sessions.get(str(session_id))
    )

    with TestClient(app) as client:
        initial = client.get("/_marimo-studio/views/dashboard/config").json()
        first = client.get(
            "/_marimo-studio/views/dashboard/config",
            headers={"Marimo-Session-Id": "s_first1"},
        ).json()
        second = client.get(
            "/_marimo-studio/views/dashboard/config",
            headers={"Marimo-Session-Id": "s_second"},
        ).json()
        connecting = client.get(
            "/_marimo-studio/views/dashboard/config",
            headers={"Marimo-Session-Id": "s_newrun"},
        ).json()

    assert initial["cellBindings"]["result"]["value"] == static.cells[1].runtime_id
    assert first["cellBindings"]["result"]["value"] == "first-1"
    assert second["cellBindings"]["result"]["value"] == "second-1"
    assert connecting["cellBindings"]["result"]["value"] == static.cells[1].runtime_id
    static_indexes = {cell.runtime_id: index for index, cell in enumerate(static.cells)}
    for identity, runtime_id in initial["runtime"]["controls"]["cells"].items():
        index = static_indexes[runtime_id]
        assert first["runtime"]["controls"]["cells"][identity] == f"first-{index}"
        assert second["runtime"]["controls"]["cells"][identity] == f"second-{index}"


def test_change_stream_captures_source_baseline_without_blocking_event_loop(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    studio = _configured(notebook_path)
    capture_started = threading.Event()
    release_capture = threading.Event()
    fallback_release = threading.Event()

    def capture_sources(
        _studio: object,
        _views: object,
    ) -> SimpleNamespace:
        capture_started.set()
        assert release_capture.wait(timeout=1)
        return SimpleNamespace(revision=lambda _view: "a" * 64)

    monkeypatch.setattr(dev, "capture_studio_sources", capture_sources)

    async def capture_ready() -> bytes:
        loop = asyncio.get_running_loop()

        def coordinate_release() -> None:
            assert capture_started.wait(timeout=1)
            loop.call_soon_threadsafe(release_capture.set)
            if not release_capture.wait(timeout=0.2):
                fallback_release.set()
                release_capture.set()

        coordinator = threading.Thread(target=coordinate_release)
        coordinator.start()
        stream = cast(
            AsyncGenerator[bytes, None],
            dev.change_events(studio, "dashboard"),
        )
        try:
            ready = await asyncio.wait_for(anext(stream), timeout=1)
        finally:
            release_capture.set()
            await stream.aclose()
            await asyncio.to_thread(coordinator.join, 1)
        return ready

    ready = asyncio.run(capture_ready())

    assert not fallback_release.is_set()
    assert json.loads(ready.split(b"data: ", 1)[1])["revision"] == "a" * 64


def test_change_stream_classifies_live_source_edits(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    studio = _configured(notebook_path)
    template = studio.views["dashboard"].template
    stylesheet = studio.views["dashboard"].root / "app.css"
    sibling = studio.views["executive"].template
    native_sleep = asyncio.sleep

    async def poll_immediately(_delay: float) -> None:
        await native_sleep(0)

    monkeypatch.setattr(dev.asyncio, "sleep", poll_immediately)
    stopping = False

    async def collect_events() -> tuple[bytes, ...]:
        nonlocal stopping
        stream = dev.change_events(
            studio,
            "dashboard",
            stop_requested=lambda: stopping,
        )
        ready = await anext(stream)

        source = template.read_text(encoding="utf-8")
        stat = template.stat()
        template.write_text(
            source.replace("app.css", "alt.css"),
            encoding="utf-8",
        )
        os.utime(template, ns=(stat.st_atime_ns, stat.st_mtime_ns))
        html = await asyncio.wait_for(anext(stream), timeout=1)

        stylesheet.write_text(
            stylesheet.read_text(encoding="utf-8") + "\nbody { line-height: 1.5; }\n",
            encoding="utf-8",
        )
        css = await asyncio.wait_for(anext(stream), timeout=1)

        studio.notebook.write_text(
            studio.notebook.read_text(encoding="utf-8") + "\n",
            encoding="utf-8",
        )
        runtime = await asyncio.wait_for(anext(stream), timeout=1)

        sibling.write_text(
            sibling.read_text(encoding="utf-8") + "\n<!-- changed -->\n",
            encoding="utf-8",
        )
        views = await asyncio.wait_for(anext(stream), timeout=1)

        shutil.rmtree(studio.view_root / "dashboard")
        removed = await asyncio.wait_for(anext(stream), timeout=1)
        stopping = True
        with pytest.raises(StopAsyncIteration):
            await asyncio.wait_for(anext(stream), timeout=0.5)
        return ready, html, css, runtime, views, removed

    messages = asyncio.run(collect_events())

    ready_payload = json.loads(messages[0].split(b"data: ", 1)[1])
    assert ready_payload["schema"] == 1
    assert ready_payload["view"] == "dashboard"
    assert re.fullmatch(r"[0-9a-f]{64}", ready_payload["revision"])
    payloads = [json.loads(message.split(b"data: ", 1)[1]) for message in messages[1:]]
    assert [payload["kind"] for payload in payloads] == [
        "html",
        "css",
        "runtime",
        "views",
        "views",
    ]
    assert payloads[0]["files"][0]["path"] == "index.html"
    assert payloads[0]["files"][0]["revision"].startswith("sha256:")
    assert payloads[1]["files"][0]["path"] == "app.css"
    assert payloads[1]["files"][0]["revision"].startswith("sha256:")
    assert payloads[2]["files"] == []
    assert payloads[3]["files"] == []


def test_document_replay_follows_the_verified_presentation(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    studio = _configured(notebook_path)

    def preserve(config: MutableMapping[str, object]) -> None:
        config["preserve_session"] = True

    update_notebook_config(studio.notebook, preserve)
    app = create_asgi_app(studio.notebook)
    configured: list[bool] = []
    monkeypatch.setattr(
        PrivateSessionReplay,
        "configure",
        lambda _replay, _context, enabled: configured.append(enabled),
    )

    with TestClient(app) as client:
        assert client.get("/").status_code == 200

        def reset(config: MutableMapping[str, object]) -> None:
            config["preserve_session"] = False

        update_notebook_config(studio.notebook, reset)
        assert client.get("/").status_code == 200

    assert configured == [True, False]


def test_value_permissions_are_narrowed_by_view(notebook_path: Path) -> None:
    studio = _configured(notebook_path)

    with TestClient(create_asgi_app(studio.notebook)) as client:
        config = client.get("/_marimo-studio/views/dashboard/config").json()
        headers = {
            "Marimo-Server-Token": config["runtime"]["data"]["serverToken"],
            "Marimo-Session-Id": "s_unknown",
        }
        allowed = client.post(
            "/_marimo-studio/views/dashboard/values",
            headers=headers,
            json={"revision": config["revision"], "selectors": ["doubled"]},
        )
        cross_view = client.post(
            "/_marimo-studio/views/dashboard/values",
            headers=headers,
            json={"revision": config["revision"], "selectors": ["x"]},
        )

    assert allowed.status_code == 409
    assert allowed.json()["error"] == "unknown-session"
    assert cross_view.status_code == 400
    assert cross_view.json()["error"] == "unknown-selector"


def test_output_permissions_are_narrowed_by_view(notebook_path: Path) -> None:
    studio = _configured(notebook_path)

    with TestClient(create_asgi_app(studio.notebook)) as client:
        config = client.get("/_marimo-studio/views/dashboard/config").json()
        headers = {
            "Marimo-Server-Token": config["runtime"]["data"]["serverToken"],
            "Marimo-Session-Id": "s_unknown",
        }
        allowed = client.post(
            "/_marimo-studio/views/dashboard/outputs",
            headers=headers,
            json={
                "revision": config["revision"],
                "selectors": ["doubled"],
                "activeSelectors": ["doubled"],
            },
        )
        cross_view = client.post(
            "/_marimo-studio/views/dashboard/outputs",
            headers=headers,
            json={
                "revision": config["revision"],
                "selectors": ["x"],
                "activeSelectors": ["doubled"],
            },
        )
        inactive = client.post(
            "/_marimo-studio/views/dashboard/outputs",
            headers=headers,
            json={
                "revision": config["revision"],
                "selectors": ["doubled"],
                "activeSelectors": [],
            },
        )

    assert allowed.status_code == 409
    assert allowed.json()["error"] == "unknown-session"
    assert cross_view.status_code == 400
    assert cross_view.json()["error"] == "unknown-selector"
    assert inactive.status_code == 400
    assert inactive.json()["error"] == "invalid-output-request"


@pytest.mark.parametrize(
    ("endpoint", "body", "reader_name"),
    [
        (
            "values",
            {"selectors": ["doubled"]},
            "read_values",
        ),
        (
            "outputs",
            {
                "selectors": ["doubled"],
                "activeSelectors": ["doubled"],
            },
            "render_outputs",
        ),
    ],
)
def test_projection_resolves_session_once(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    endpoint: str,
    body: dict[str, list[str]],
    reader_name: str,
) -> None:
    studio = _configured(notebook_path)
    app = create_asgi_app(studio.notebook)
    resolved: list[str] = []

    async def read_projection(
        _host: object,
        _context: object,
        session_id: str,
        *_args: object,
        **_kwargs: object,
    ) -> SimpleNamespace:
        resolved.append(session_id)
        return SimpleNamespace(to_dict=lambda: {"errors": {}})

    monkeypatch.setattr(
        f"marimo_studio._compat.kernel_values.host.PrivateKernelProjectionHost.{reader_name}",
        read_projection,
    )

    with TestClient(app) as client:
        config = client.get("/_marimo-studio/views/dashboard/config").json()
        response = client.post(
            f"/_marimo-studio/views/dashboard/{endpoint}",
            headers={
                "Marimo-Server-Token": config["runtime"]["data"]["serverToken"],
                "Marimo-Session-Id": "s_123456",
            },
            json={"revision": config["revision"], **body},
        )

    assert response.status_code == 200
    assert resolved == ["s_123456"]


def test_value_permissions_follow_the_browser_presentation_revision(
    notebook_path: Path,
) -> None:
    studio = _configured(notebook_path)

    with TestClient(create_asgi_app(studio.notebook)) as client:
        first = client.get("/_marimo-studio/views/dashboard/config").json()
        _set_shell(studio, "dashboard", "<p>Updated dashboard</p>")
        current = client.get("/_marimo-studio/views/dashboard/config").json()
        headers = {
            "Marimo-Server-Token": first["runtime"]["data"]["serverToken"],
            "Marimo-Session-Id": "s_unknown",
        }
        in_flight = client.post(
            "/_marimo-studio/views/dashboard/values",
            headers=headers,
            json={"revision": first["revision"], "selectors": ["doubled"]},
        )
        removed = client.post(
            "/_marimo-studio/views/dashboard/values",
            headers=headers,
            json={"revision": current["revision"], "selectors": ["doubled"]},
        )
        unpublished = client.post(
            "/_marimo-studio/views/dashboard/values",
            headers=headers,
            json={"revision": "unpublished", "selectors": ["doubled"]},
        )

    assert first["revision"] != current["revision"]
    assert in_flight.status_code == 409
    assert in_flight.json()["error"] == "unknown-session"
    assert removed.status_code == 400
    assert removed.json()["error"] == "unknown-selector"
    assert unpublished.status_code == 409
    assert unpublished.json() == {
        "error": "presentation-revision-unavailable",
        "message": "The requested presentation revision is no longer available.",
        "transient": True,
    }


def test_parent_asgi_mount_preserves_public_routes(notebook_path: Path) -> None:
    studio = _configured(notebook_path)
    public = studio.notebook.parent / "public"
    public.mkdir()
    public.joinpath("sample.txt").write_text("notebook asset", encoding="utf-8")
    parent = Starlette(
        routes=[
            Mount(
                "/parent",
                app=_marimo_app(
                    studio.notebook,
                    path="/base",
                    programmatic=True,
                ),
            )
        ]
    )

    with TestClient(parent) as client:
        page = client.get("/parent/base/")
        named = client.get("/parent/base/executive/")
        config = client.get("/parent/base/_marimo-studio/views/dashboard/config").json()
        studio_asset = client.get("/parent/base/_marimo-studio/assets/studio.css")
        relative_cell = client.get(
            "/parent/base/dashboard/_marimo-studio/views/dashboard/cells/result"
        )
        relative_public = client.get(
            "/parent/base/dashboard/public/sample.txt",
            headers={"X-Notebook-Id": quote(str(studio.notebook), safe="")},
        )

    assert page.status_code == 200
    assert named.status_code == 200
    assert '<base href="/parent/base/dashboard/">' in page.text
    assert 'src="/parent/base/_marimo-studio/assets/runtime.js"' in page.text
    assert config["rootUrl"] == "/parent/base/"
    _assert_server_runtime(config["runtime"]["data"], "/parent/base/")
    support_url = urlsplit(config["supportUrl"])
    assert support_url.path == "/parent/base/_marimo-studio/views/dashboard"
    assert parse_qs(support_url.query)[SERVER_INSTANCE_QUERY_PARAM] == [
        server_instance_id(config["runtime"]["data"]["serverToken"])
    ]
    assert studio_asset.status_code == 200
    assert relative_cell.text == '<marimo-cell name="result"></marimo-cell>'
    assert relative_public.text == "notebook asset"


def test_edit_mode_public_routes_honor_parent_mount(notebook_path: Path) -> None:
    studio = _configured(notebook_path)
    child = _marimo_app(
        studio.notebook,
        path="/base",
        programmatic=True,
    )
    _edit_mode(child)
    parent = Starlette(routes=[Mount("/parent", app=child)])

    with TestClient(parent) as client:
        landing = client.get("/parent/base/", follow_redirects=False)
        workspace = client.get("/parent/base/studio/executive/")
        config = client.get("/parent/base/_marimo-studio/views/executive/config").json()
        outside = [
            client.get("/parent/", follow_redirects=False),
            client.get("/parent/studio/dashboard/", follow_redirects=False),
            client.get("/parent/dashboard/", follow_redirects=False),
        ]

    assert landing.status_code == 307
    assert landing.headers["location"] == "/parent/base/studio/dashboard/"
    assert workspace.status_code == 200
    bootstrap = _studio_bootstrap(workspace.text)
    editor_url = urlsplit(bootstrap["urls"]["editor"])
    editor_query = parse_qs(editor_url.query)
    assert 'href="/parent/base/favicon.ico"' in workspace.text
    assert editor_url.path == "/parent/base/_marimo-studio/editor/"
    assert editor_query["file"] == [str(studio.notebook)]
    assert editor_query["marimo_studio_client"] == [bootstrap["clientId"]]
    assert editor_query[SERVER_INSTANCE_QUERY_PARAM] == [bootstrap["serverInstance"]]
    assert re.fullmatch(r"[A-Za-z0-9_-]{16,128}", bootstrap["clientId"])
    assert bootstrap["urls"]["viewPrefix"] == "/parent/base/"
    assert bootstrap["urls"]["studioPrefix"] == "/parent/base/studio/"
    assert config["rootUrl"] == "/parent/base/"
    _assert_server_runtime(config["runtime"]["data"], "/parent/base/")
    assert all(response.status_code == 404 for response in outside)


def test_edit_mode_enters_studio_and_embeds_the_native_editor(
    notebook_path: Path,
) -> None:
    studio = _configured(notebook_path)
    app = _marimo_app(studio.notebook)
    _edit_mode(app)
    expected_editor = "/_marimo-studio/editor/?" + urlencode(
        {"file": str(studio.notebook)}
    )

    with TestClient(app) as client:
        landing = client.get(
            "/?region=emea&region=apac&empty=&session_id=s_123456&kiosk=true",
            follow_redirects=False,
        )
        head = client.head("/", follow_redirects=False)
        post = client.post("/", follow_redirects=False)
        landing_workspace = client.get(landing.headers["location"])
        default_workspace = client.get("/studio/")
        workspace_redirect = client.get(
            "/studio/executive?layout=preview",
            follow_redirects=False,
        )
        workspace = client.get("/studio/executive/")
        view_redirect = client.get(
            "/executive?region=emea",
            follow_redirects=False,
        )
        waiting = client.get("/executive/")
        missing_view = client.get("/studio/missing/")

        editor = client.get(expected_editor)

        _session_manager(app).get_session_by_file_key = Mock(return_value=object())
        view = client.get("/executive/")

    assert landing.status_code == 307
    assert landing.headers["location"] == (
        "/studio/dashboard/?region=emea&region=apac&empty="
    )
    landing_editor = "/_marimo-studio/editor/?" + urlencode(
        [
            ("region", "emea"),
            ("region", "apac"),
            ("empty", ""),
            ("file", str(studio.notebook)),
        ]
    )
    landing_bootstrap = _studio_bootstrap(landing_workspace.text)
    actual_editor = urlsplit(landing_bootstrap["urls"]["editor"])
    expected_parts = urlsplit(landing_editor)
    actual_query = parse_qs(actual_editor.query, keep_blank_values=True)
    expected_query = parse_qs(expected_parts.query, keep_blank_values=True)
    assert actual_editor.path == expected_parts.path
    assert actual_query["region"] == expected_query["region"]
    assert actual_query["empty"] == [""]
    assert actual_query["file"] == [str(studio.notebook)]
    assert actual_query["marimo_studio_client"] == [landing_bootstrap["clientId"]]
    assert head.status_code == 307
    assert head.headers["location"] == "/studio/dashboard/"
    assert post.status_code == 405
    assert editor.status_code == 200
    assert default_workspace.status_code == 200
    assert workspace_redirect.status_code == 307
    assert workspace_redirect.headers["location"] == (
        "/studio/executive/?layout=preview"
    )
    assert workspace.status_code == 200
    assert view_redirect.status_code == 307
    assert view_redirect.headers["location"] == "/executive/?region=emea"
    assert waiting.status_code == 202
    assert waiting.headers["retry-after"] == "1"
    assert 'role="status"' in waiting.text
    assert "Starting notebook" in waiting.text
    assert missing_view.status_code == 404
    assert view.status_code == 200


def test_direct_native_editor_enables_cell_alias_sync(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    studio = _configured(notebook_path)
    app = _marimo_app(studio.notebook)
    _edit_mode(app)
    locations: list[Any] = []
    monkeypatch.setattr(
        "marimo_studio._compat.server.notebook_save.PrivateNotebookSaveTransform.enable",
        lambda _persistence, location: locations.append(location),
    )
    editor = "/_marimo-studio/editor/?" + urlencode({"file": str(studio.notebook)})

    with TestClient(app) as client:
        response = client.get(editor)

    assert response.status_code == 200
    assert {location.notebook for location in locations} == {studio.notebook}


def test_view_list_tracks_new_folders_without_restarting_marimo(
    notebook_path: Path,
) -> None:
    studio = _configured(notebook_path)
    app = create_asgi_app(studio.notebook)

    with TestClient(app) as client:
        before = client.get("/_marimo-studio/views").json()
        ensure_view(studio.notebook, "operations")
        after = client.get("/_marimo-studio/views").json()
        page = client.get("/operations/")

    assert before["views"] == ["dashboard", "executive"]
    assert after["views"] == ["dashboard", "executive", "operations"]
    assert page.status_code == 200


def test_definition_state_initializes_the_first_view_from_edit_mode(
    notebook_path: Path,
) -> None:
    setup = ensure_view(notebook_path)
    assert setup.workspace is not None
    shutil.rmtree(setup.workspace.view_root)
    definition = load_studio_definition(notebook_path)
    app = _marimo_app(notebook_path)
    _edit_mode(app)
    headers = {"Marimo-Server-Token": str(_session_manager(app).skew_protection_token)}

    with TestClient(app) as client:
        status_before = client.get("/_marimo-studio/status")
        views_before = client.get("/_marimo-studio/views")
        initializer = client.get("/")
        created = client.post(
            "/_marimo-studio/views",
            json={"name": definition.default_view},
            headers=headers,
        )
        status_after = client.get("/_marimo-studio/status")
        workspace = client.get("/studio/dashboard/")

    assert status_before.json() == {
        "schema": 1,
        "state": "needs-view",
        "default_view": "dashboard",
        "views": [],
    }
    assert views_before.json() == {
        "schema": 1,
        "default_view": "dashboard",
        "views": [],
    }
    assert initializer.status_code == 200
    assert 'data-marimo-studio-state="needs-view"' in initializer.text
    assert "Create the first view" in initializer.text
    assert created.status_code == 201
    assert created.json()["studio_url"] == "/studio/dashboard/"
    assert status_after.json() == {
        "schema": 1,
        "state": "ready",
        "default_view": "dashboard",
        "views": ["dashboard"],
    }
    assert workspace.status_code == 200
    assert (definition.view_root / "dashboard" / "index.html").is_file()


def test_definition_state_returns_structured_run_repair(
    notebook_path: Path,
) -> None:
    setup = ensure_view(notebook_path)
    assert setup.workspace is not None
    shutil.rmtree(setup.workspace.view_root)

    with TestClient(create_asgi_app(notebook_path)) as client:
        response = client.get("/", headers={"Accept": "application/json"})

    assert response.status_code == 409
    assert response.json() == {
        "error": "workspace-not-initialized",
        "message": "Studio is configured and needs its first view 'dashboard'.",
        "state": "needs-view",
        "default_view": "dashboard",
        "views": [],
        "hint": "Open the notebook in edit mode and create its first view.",
    }


def test_workspace_status_reports_configuration_errors(
    notebook_path: Path,
) -> None:
    studio = _configured(notebook_path)

    def select_missing(config: MutableMapping[str, Any]) -> None:
        config["default"] = "missing"

    update_notebook_config(studio.notebook, select_missing)

    with TestClient(create_asgi_app(studio.notebook)) as client:
        status = client.get("/_marimo-studio/status")

    assert status.status_code == 200
    assert status.json()["schema"] == 1
    assert status.json()["state"] == "error"
    assert status.json()["error"] == "configuration-error"


def test_edit_workspace_creates_views_and_conditionally_updates_source(
    notebook_path: Path,
) -> None:
    studio = _configured(notebook_path)
    app = _marimo_app(studio.notebook)
    _edit_mode(app)
    mutation_headers = {
        "Marimo-Server-Token": str(_session_manager(app).skew_protection_token)
    }

    with TestClient(app) as client:
        loaded = client.get("/_marimo-studio/views/dashboard/source/index.html")
        replacement = loaded.text.replace(
            '<main id="app-shell">',
            '<main id="app-shell"><h1>Updated in Studio</h1>',
        ).replace("\n", "\r\n")
        saved = client.put(
            "/_marimo-studio/views/dashboard/source/index.html",
            content=replacement,
            headers={"If-Match": loaded.headers["etag"], **mutation_headers},
        )
        stale = client.put(
            "/_marimo-studio/views/dashboard/source/index.html",
            content="stale",
            headers={"If-Match": loaded.headers["etag"], **mutation_headers},
        )
        created = client.post(
            "/_marimo-studio/views",
            json={"name": "operations"},
            headers=mutation_headers,
        )
        duplicate = client.post(
            "/_marimo-studio/views",
            json={"name": "operations"},
            headers=mutation_headers,
        )
        invalid = client.post(
            "/_marimo-studio/views",
            json={"name": "Operations Report"},
            headers=mutation_headers,
        )

    assert loaded.status_code == 200
    assert loaded.headers["content-type"].startswith("text/plain")
    assert loaded.headers["etag"].startswith('"sha256:')
    assert saved.status_code == 204
    assert saved.headers["etag"] != loaded.headers["etag"]
    assert studio.views["dashboard"].template.read_bytes() == replacement.encode()
    assert stale.status_code == 412
    assert stale.json()["error"] == "source-conflict"
    assert stale.json()["revision"] == saved.headers["etag"].strip('"')
    assert created.status_code == 201
    assert created.json()["studio_url"] == "/studio/operations/"
    assert created.json()["view_url"] == "/operations/"
    assert (studio.view_root / "operations" / "index.html").is_file()
    assert (studio.view_root / "operations" / "app.css").is_file()
    assert duplicate.status_code == 409
    assert duplicate.json()["error"] == "view-exists"
    assert invalid.status_code == 400
    assert invalid.json()["error"] == "invalid-view-name"


def test_view_deletion_removes_files_promotes_the_default_and_keeps_one_view(
    notebook_path: Path,
) -> None:
    studio = _configured(notebook_path)
    ensure_view(studio.notebook, "operations")
    asset = studio.view_root / "operations" / "assets" / "note.txt"
    asset.parent.mkdir()
    asset.write_text("authored view asset", encoding="utf-8")
    app = _marimo_app(studio.notebook)
    _edit_mode(app)
    headers = {"Marimo-Server-Token": str(_session_manager(app).skew_protection_token)}

    with TestClient(app) as client:
        removed = client.delete(
            "/_marimo-studio/views/operations",
            headers=headers,
        )
        promoted = client.delete(
            "/_marimo-studio/views/dashboard",
            headers=headers,
        )
        last = client.delete(
            "/_marimo-studio/views/executive",
            headers=headers,
        )
        views = client.get("/_marimo-studio/views").json()

    assert removed.status_code == 200
    assert removed.json() == {
        "schema": 1,
        "name": "operations",
        "default_view": "dashboard",
        "views": ["dashboard", "executive"],
    }
    assert not (studio.view_root / "operations").exists()
    assert promoted.status_code == 200
    assert promoted.json()["default_view"] == "executive"
    updated = load_studio(studio.notebook)
    assert views == {
        "schema": 1,
        "default_view": "executive",
        "views": ["executive"],
    }
    assert updated.default_view == "executive"
    assert not (studio.view_root / "dashboard").exists()
    assert last.status_code == 409
    assert last.json() == {
        "error": "last-view",
        "message": "Keep at least one view.",
    }
    assert studio.views["executive"].template.is_file()


def test_edit_workspace_mutations_require_the_current_server_token(
    notebook_path: Path,
) -> None:
    studio = _configured(notebook_path)
    app = _marimo_app(studio.notebook, skew_protection=True)
    _edit_mode(app)
    token = str(_session_manager(app).skew_protection_token)

    with TestClient(app) as client:
        loaded = client.get("/_marimo-studio/views/dashboard/source/index.html")
        source_headers = {"If-Match": loaded.headers["etag"]}
        missing = client.put(
            "/_marimo-studio/views/dashboard/source/index.html",
            content=loaded.text,
            headers=source_headers,
        )
        invalid = client.put(
            "/_marimo-studio/views/dashboard/source/index.html",
            content=loaded.text,
            headers={
                **source_headers,
                "Marimo-Server-Token": "stale-token",
            },
        )
        valid = client.put(
            "/_marimo-studio/views/dashboard/source/index.html",
            content=loaded.text,
            headers={**source_headers, "Marimo-Server-Token": token},
        )
        missing_delete = client.delete("/_marimo-studio/views/executive")
        invalid_delete = client.delete(
            "/_marimo-studio/views/executive",
            headers={"Marimo-Server-Token": "stale-token"},
        )
        missing_analysis = client.post(
            "/_marimo-studio/analyze",
            json={"view": "dashboard"},
        )
        invalid_activation = client.patch(
            "/_marimo-studio/views/dashboard/activate",
            headers={"Marimo-Server-Token": "stale-token"},
        )
        missing_observation = client.put(
            "/_marimo-studio/views/dashboard/observation",
            json={},
        )

    assert missing.status_code == 401
    assert missing.json()["error"] == "missing-server-token"
    assert invalid.status_code == 401
    assert invalid.json()["error"] == "invalid-server-token"
    assert valid.status_code == 204
    assert missing_delete.status_code == 401
    assert missing_delete.json()["error"] == "missing-server-token"
    assert invalid_delete.status_code == 401
    assert invalid_delete.json()["error"] == "invalid-server-token"
    assert missing_analysis.status_code == 401
    assert invalid_activation.status_code == 401
    assert missing_observation.status_code == 401


def test_run_mode_keeps_studio_source_mutations_read_only(
    notebook_path: Path,
) -> None:
    studio = _configured(notebook_path)

    with TestClient(create_asgi_app(studio.notebook)) as client:
        loaded = client.get("/_marimo-studio/views/dashboard/source/index.html")
        config = client.get("/_marimo-studio/views/dashboard/config").json()
        headers = {"Marimo-Server-Token": config["runtime"]["data"]["serverToken"]}
        write = client.put(
            "/_marimo-studio/views/dashboard/source/index.html",
            content=loaded.text,
            headers={"If-Match": loaded.headers["etag"], **headers},
        )
        create = client.post(
            "/_marimo-studio/views",
            json={"name": "operations"},
            headers=headers,
        )
        delete = client.delete(
            "/_marimo-studio/views/executive",
            headers=headers,
        )
        analysis = client.post(
            "/_marimo-studio/analyze",
            json={"view": "dashboard"},
            headers=headers,
        )
        observations = client.post(
            "/_marimo-studio/observations",
            headers=headers,
            json={
                "schema": 1,
                "views": ["dashboard"],
                "revisions": {"dashboard": config["revision"]},
                "runtime": None,
                "timeout": 10,
                "browserClient": None,
            },
        )
        activation = client.patch(
            "/_marimo-studio/views/dashboard/activate",
            headers=headers,
        )
        observation = client.put(
            "/_marimo-studio/views/dashboard/observation",
            json={},
            headers=headers,
        )

    assert loaded.status_code == 200
    assert write.status_code == 403
    assert write.json()["error"] == "edit-access-required"
    assert create.status_code == 403
    assert create.json()["error"] == "edit-access-required"
    assert delete.status_code == 403
    assert delete.json()["error"] == "edit-access-required"
    assert analysis.status_code == 403
    assert analysis.json()["error"] == "edit-access-required"
    assert observations.status_code == 403
    assert observations.json()["error"] == "edit-access-required"
    assert activation.status_code == 403
    assert activation.json()["error"] == "edit-access-required"
    assert observation.status_code == 403
    assert observation.json()["error"] == "edit-access-required"


def test_template_errors_stay_scoped_to_the_selected_view(
    notebook_path: Path,
) -> None:
    studio = _configured(notebook_path)
    studio.views["executive"].template.write_text(
        "<html><head></head><body><main id='broken'></main></body></html>",
        encoding="utf-8",
    )
    edit_app = _marimo_app(studio.notebook)
    _edit_mode(edit_app)

    with TestClient(create_asgi_app(studio.notebook)) as client:
        dashboard = client.get("/")
        executive = client.get("/executive/")
        stylesheet = client.get("/executive/app.css")
        views = client.get("/_marimo-studio/views")
    with TestClient(edit_app) as client:
        studio = client.get("/studio/executive/")

    assert dashboard.status_code == 200
    assert executive.status_code == 500
    assert stylesheet.status_code == 200
    assert views.status_code == 200
    assert studio.status_code == 200


def test_marimo_authentication_owns_document_login(
    notebook_path: Path,
) -> None:
    studio = _configured(notebook_path)

    with TestClient(_marimo_app(studio.notebook, token="test-token")) as client:
        named = client.get(
            "/executive/?region=emea",
            follow_redirects=False,
        )
        establish = client.get(
            "/executive/?access_token=test-token&region=emea",
            follow_redirects=False,
        )
        page = client.get(establish.headers["location"])
        protected = client.get("/_marimo-studio/views/executive/config")

    assert named.status_code == 303
    assert named.headers["location"].startswith("/auth/login")
    login_query = parse_qs(urlsplit(named.headers["location"]).query)
    assert login_query["next"] == ["/executive/?region=emea"]
    assert establish.status_code == 303
    assert establish.headers["location"] == "/executive/?region=emea"
    assert "session=" in establish.headers["set-cookie"]
    assert page.status_code == 200
    assert protected.status_code == 200
    assert "test-token" not in page.text


def test_edit_mode_public_pages_use_marimo_authentication(
    notebook_path: Path,
) -> None:
    studio = _configured(notebook_path)
    app = _marimo_app(studio.notebook, token="test-token")
    _edit_mode(app)

    with TestClient(app) as client:
        workspace = client.get("/studio/executive/", follow_redirects=False)
        view = client.get("/executive/", follow_redirects=False)
        establish = client.get(
            "/?access_token=test-token",
            follow_redirects=False,
        )
        landing = client.get(establish.headers["location"], follow_redirects=False)
        page = client.get(landing.headers["location"])

    workspace_login = parse_qs(urlsplit(workspace.headers["location"]).query)
    view_login = parse_qs(urlsplit(view.headers["location"]).query)
    assert workspace.status_code == 303
    assert workspace_login["next"] == ["/studio/executive/"]
    assert view.status_code == 303
    assert view_login["next"] == ["/executive/"]
    assert establish.status_code == 303
    assert establish.headers["location"] == "/"
    assert "session=" in establish.headers["set-cookie"]
    assert landing.status_code == 307
    assert landing.headers["location"] == "/studio/dashboard/"
    assert page.status_code == 200


def test_authentication_precedes_project_diagnostics(
    notebook_path: Path,
) -> None:
    studio = _configured(notebook_path)

    def invalidate(config: MutableMapping[str, object]) -> None:
        del config["default"]

    update_notebook_config(studio.notebook, invalidate)

    with TestClient(_marimo_app(studio.notebook, token="test-token")) as client:
        root = client.get("/", follow_redirects=False)
        support = client.get("/_marimo-studio/views", follow_redirects=False)

    assert root.status_code == 303
    assert support.status_code == 303
    assert all(
        response.headers["location"].startswith("/auth/login")
        for response in (root, support)
    )


def test_invalid_studio_config_does_not_intercept_marimo_routes(
    notebook_path: Path,
) -> None:
    studio = _configured(notebook_path)

    def invalidate(config: MutableMapping[str, object]) -> None:
        del config["default"]

    update_notebook_config(studio.notebook, invalidate)
    app = _marimo_app(studio.notebook)
    _edit_mode(app)

    with TestClient(app) as client:
        editor = client.get("/")
        native = [
            client.get("/health"),
            client.get("/public-files-sw.js"),
        ]
        presentation = client.get("/dashboard/")
        refresh = client.get(
            "/dashboard/",
            headers={"Accept": "application/json"},
        )

    assert editor.status_code == 200
    assert all(response.status_code == 200 for response in native)
    assert presentation.status_code == 500
    assert presentation.headers["Marimo-Studio-Error"] == "configuration-error"
    assert refresh.status_code == 500
    assert refresh.headers["content-type"].startswith("application/json")
    assert refresh.json()["error"] == "configuration-error"


def test_middleware_is_inert_for_an_unconfigured_notebook(tmp_path: Path) -> None:
    notebook = tmp_path / "plain.py"
    notebook.write_text(
        notebook_source(tmp_path / "executed"),
        encoding="utf-8",
    )

    edit_app = _marimo_app(notebook)
    _edit_mode(edit_app)

    with TestClient(_marimo_app(notebook)) as client:
        page = client.get("/")
        support = client.get("/_marimo-studio/views")
    with TestClient(edit_app) as client:
        editor = client.get("/")
    with TestClient(_marimo_app(notebook, token="test-token")) as client:
        missing = client.get("/definitely-missing/", follow_redirects=False)

    assert page.status_code == 200
    assert editor.status_code == 200
    assert support.status_code == 404
    assert missing.status_code == 404


def test_view_asset_route_rejects_parent_paths(notebook_path: Path) -> None:
    studio = _configured(notebook_path)
    target = studio.views["dashboard"].root / "target.js"
    target.write_text("export {};\n", encoding="utf-8")
    target.with_name("alias.js").symlink_to(target.name)

    with TestClient(create_asgi_app(studio.notebook)) as client:
        traversal = client.get("/dashboard/%2e%2e/%2e%2e/analysis.py")
        symlink = client.get("/dashboard/alias.js")

    assert traversal.status_code == 404
    assert symlink.status_code == 404
