from __future__ import annotations

import asyncio
from collections.abc import MutableMapping
from importlib.metadata import entry_points
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock
from urllib.parse import parse_qs, urlsplit

import marimo
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.routing import Mount
from starlette.testclient import TestClient

from marimo_studio import create_asgi_app
from marimo_studio._compat import server as server_compat
from marimo_studio._compat.notebook import load_static_notebook
from marimo_studio._compat.server import programmatic_middleware
from marimo_studio._server import dev
from marimo_studio._server.dev import _event_kind
from marimo_studio._workspace import (
    bind_cell,
    ensure_view,
    load_studio,
)
from marimo_studio._workspace.metadata import update_notebook_config
from marimo_studio._workspace.models import StudioConfig

from .helpers import notebook_source


def _set_shell(studio: StudioConfig, view_name: str, content: str) -> None:
    template = studio.views[view_name].template
    template.write_text(
        template.read_text(encoding="utf-8").replace(
            '<main id="app-shell"></main>',
            f'<main id="app-shell">{content}</main>',
        ),
        encoding="utf-8",
    )


def _configured(notebook: Path) -> StudioConfig:
    ensure_view(notebook)
    studio = load_studio(notebook)
    bind_cell(studio, "result", 1)
    ensure_view(notebook, "executive")
    studio = load_studio(notebook)
    _set_shell(
        studio,
        "dashboard",
        '<span mo-value="doubled"></span><marimo-cell name="result"></marimo-cell>',
    )
    _set_shell(studio, "executive", '<span mo-value="x"></span>')
    return load_studio(notebook)


def _marimo_app(
    notebook: Path,
    *,
    path: str = "/",
    token: str = "",
    programmatic: bool = False,
) -> Any:
    return (
        marimo.create_asgi_app(quiet=True, token=token)
        .with_app(
            path=path,
            root=str(notebook),
            middleware=([programmatic_middleware(notebook)] if programmatic else None),
        )
        .build()
    )


def _session_manager(app: Any) -> Any:
    mounted: Any = next(route.app for route in app.routes if isinstance(route, Mount))
    return mounted.state.session_manager


def _edit_mode(app: Any) -> None:
    from marimo._session.model import SessionMode

    _session_manager(app).mode = SessionMode.EDIT


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


def test_run_mode_serves_default_and_named_view_documents(
    notebook_path: Path,
) -> None:
    studio = _configured(notebook_path)

    with TestClient(create_asgi_app(studio.notebook)) as client:
        default = client.get("/")
        named_redirect = client.get(
            "/executive?region=emea&view=compact",
            follow_redirects=False,
        )
        named = client.get("/executive/")
        health = client.get("/health")

    assert default.status_code == 200
    assert default.text.count('id="marimo-runtime-root"') == 1
    assert '"/_marimo-studio/views/dashboard"' in default.text
    assert default.text.index("runtime.css") < default.text.index("app.css")
    assert named_redirect.status_code == 307
    assert named_redirect.headers["location"] == (
        "/executive/?region=emea&view=compact"
    )
    assert named.status_code == 200
    assert '"/_marimo-studio/views/executive"' in named.text
    assert health.status_code == 200


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

    def preserve(config: MutableMapping[str, object]) -> None:
        config["preserve_session"] = True

    update_notebook_config(studio.notebook, preserve)

    with TestClient(create_asgi_app(studio.notebook)) as client:
        dashboard = client.get("/_marimo-studio/views/dashboard/config").json()
        executive = client.get("/_marimo-studio/views/executive/config").json()
        cell = client.get("/_marimo-studio/views/executive/cells/result")
        stylesheet = client.get("/_marimo-studio/views/executive/static/app.css")
        views = client.get("/_marimo-studio/views").json()

    assert dashboard["view"] == "dashboard"
    assert dashboard["views"] == ["dashboard", "executive"]
    assert dashboard["supportUrl"] == "/_marimo-studio/views/dashboard"
    assert set(dashboard["valueBindings"]) == {"doubled"}
    assert executive["supportUrl"] == "/_marimo-studio/views/executive"
    assert set(executive["valueBindings"]) == {"x"}
    assert dashboard["cellBindings"]["result"] == executive["cellBindings"]["result"]
    assert cell.text == '<marimo-cell name="result"></marimo-cell>'
    assert stylesheet.status_code == 200
    assert views == {
        "schema": 1,
        "default_view": "dashboard",
        "views": ["dashboard", "executive"],
    }
    assert dashboard["preserveSession"] is True


def test_named_cells_resolve_against_the_live_notebook_name(tmp_path: Path) -> None:
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

    with TestClient(create_asgi_app(notebook)) as client:
        config = client.get("/_marimo-studio/views/dashboard/config").json()

    assert config["schema"] == 1
    assert config["cellBindings"]["imports"] == {
        "kind": "name",
        "value": "imports",
    }


def test_edit_runtime_uses_live_ids_for_anonymous_bindings(
    notebook_path: Path,
) -> None:
    studio = _configured(notebook_path)
    app = _marimo_app(studio.notebook)
    _edit_mode(app)
    static = load_static_notebook(studio.notebook)
    rows = tuple(
        SimpleNamespace(code=cell.code, id=f"live-{index}")
        for index, cell in enumerate(static.cells)
    )
    session = SimpleNamespace(document=SimpleNamespace(cells=rows))
    _session_manager(app).get_session_by_file_key = Mock(return_value=session)

    with TestClient(app) as client:
        dashboard = client.get("/_marimo-studio/views/dashboard/config").json()
        executive = client.get("/_marimo-studio/views/executive/config").json()

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
        SimpleNamespace(code='inserted = "before"', id="live-inserted"),
        SimpleNamespace(code=static.cells[0].code, id="live-import"),
        SimpleNamespace(code=legacy, id="live-report"),
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


def test_edit_runtime_rejects_an_unmatched_static_cell(
    notebook_path: Path,
) -> None:
    studio = _configured(notebook_path)
    app = _marimo_app(studio.notebook)
    _edit_mode(app)
    session = SimpleNamespace(
        document=SimpleNamespace(
            cells=(SimpleNamespace(code="unrelated = 1", id="live-unrelated"),)
        )
    )
    _session_manager(app).get_session_by_file_key = Mock(return_value=session)

    with TestClient(app) as client:
        response = client.get("/_marimo-studio/views/dashboard/config")

    assert response.status_code == 409
    assert response.json()["error"] == "runtime-sync-pending"
    assert response.json()["transient"] is True


def test_run_runtime_refreshes_bindings_for_each_browser_session(
    notebook_path: Path,
) -> None:
    studio = _configured(notebook_path)
    app = _marimo_app(studio.notebook)
    static = load_static_notebook(studio.notebook)

    def session(prefix: str, *, inserted: bool) -> SimpleNamespace:
        rows = tuple(
            SimpleNamespace(code=cell.code, id=f"{prefix}-{index}")
            for index, cell in enumerate(static.cells)
        )
        if inserted:
            rows = (
                SimpleNamespace(code='inserted = "before"', id=f"{prefix}-inserted"),
                *rows,
            )
        return SimpleNamespace(document=SimpleNamespace(cells=rows))

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


def test_notebook_saves_refresh_bindings_and_mixed_saves_refresh_shell(
    notebook_path: Path,
) -> None:
    studio = _configured(notebook_path)
    stylesheet = studio.views["dashboard"].root / "app.css"
    other_template = studio.views["executive"].template

    assert (
        _event_kind(
            studio,
            {("notebook", studio.notebook)},
            "dashboard",
        )
        == "runtime"
    )
    assert (
        _event_kind(
            studio,
            {("notebook", studio.notebook), ("view", stylesheet)},
            "dashboard",
        )
        == "html"
    )
    assert (
        _event_kind(
            studio,
            {("view", other_template)},
            "dashboard",
        )
        == "views"
    )


def test_change_stream_detects_edits_after_its_ready_event(
    notebook_path: Path,
) -> None:
    studio = _configured(notebook_path)

    async def events() -> tuple[bytes, bytes]:
        stream = dev.change_events(studio, "dashboard")
        ready = await anext(stream)
        studio.views["dashboard"].template.write_text(
            "<html><head></head><body><main id='app-shell'></main></body></html>",
            encoding="utf-8",
        )
        changed = await asyncio.wait_for(anext(stream), timeout=1)
        return ready, changed

    ready, changed = asyncio.run(events())

    assert ready == b"event: ready\ndata: {}\n\n"
    assert changed == b'event: change\ndata: {"kind":"html"}\n\n'


def test_document_replay_requires_an_opted_in_manager_and_query() -> None:
    class Manager:
        pass

    manager = Manager()
    other_manager = Manager()
    session = SimpleNamespace(disconnect_main_consumer=Mock())
    handler = SimpleNamespace(_reconnect_session=Mock())
    reconnect = Mock(return_value=("fallback", "new"))

    server_compat._DOCUMENT_REPLAY_MANAGERS.add(manager)

    def connector(active_manager: Manager, requested: bool) -> SimpleNamespace:
        query = {server_compat.DOCUMENT_REPLAY_QUERY_PARAM: "1"} if requested else {}
        return SimpleNamespace(
            manager=active_manager,
            connection=SimpleNamespace(query_params=query),
            handler=handler,
        )

    replayed = server_compat._reconnect_with_document_replay(
        connector(manager, True),
        session,
        reconnect,
        "reconnect",
    )
    unmarked = server_compat._reconnect_with_document_replay(
        connector(manager, False),
        session,
        reconnect,
        "reconnect",
    )
    unregistered = server_compat._reconnect_with_document_replay(
        connector(other_manager, True),
        session,
        reconnect,
        "reconnect",
    )

    assert replayed == (session, "reconnect")
    assert unmarked == ("fallback", "new")
    assert unregistered == ("fallback", "new")
    session.disconnect_main_consumer.assert_called_once_with()
    handler._reconnect_session.assert_called_once_with(session, replay=True)


def test_value_permissions_are_narrowed_by_view(notebook_path: Path) -> None:
    studio = _configured(notebook_path)

    with TestClient(create_asgi_app(studio.notebook)) as client:
        config = client.get("/_marimo-studio/views/dashboard/config").json()
        headers = {
            "Marimo-Server-Token": config["serverToken"],
            "Marimo-Session-Id": "s_unknown",
        }
        allowed = client.post(
            "/_marimo-studio/views/dashboard/values",
            headers=headers,
            json={"selectors": ["doubled"]},
        )
        cross_view = client.post(
            "/_marimo-studio/views/dashboard/values",
            headers=headers,
            json={"selectors": ["x"]},
        )

    assert allowed.status_code == 409
    assert allowed.json()["error"] == "unknown-session"
    assert cross_view.status_code == 400
    assert cross_view.json()["error"] == "unknown-selector"


def test_parent_asgi_mount_preserves_public_routes(notebook_path: Path) -> None:
    studio = _configured(notebook_path)
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

    assert page.status_code == 200
    assert named.status_code == 200
    assert '<base href="/parent/base/">' in page.text
    assert 'src="/parent/base/_marimo-studio/assets/runtime.js"' in page.text
    assert config["runtimeUrl"] == "/parent/base/"
    assert config["supportUrl"] == "/parent/base/_marimo-studio/views/dashboard"
    assert studio_asset.status_code == 200


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
        workspace = client.get("/parent/base/studio/executive/")
        config = client.get("/parent/base/_marimo-studio/views/executive/config").json()

    assert workspace.status_code == 200
    assert 'data-editor-frame src="/parent/base/"' in workspace.text
    assert 'href="/parent/base/executive/"' in workspace.text
    assert 'data-view-prefix="/parent/base/"' in workspace.text
    assert 'data-studio-prefix="/parent/base/studio/"' in workspace.text
    assert config["runtimeUrl"] == "/parent/base/"


def test_edit_mode_keeps_the_editor_at_root_and_adds_studio(
    notebook_path: Path,
) -> None:
    studio = _configured(notebook_path)
    app = _marimo_app(studio.notebook)
    _edit_mode(app)

    with TestClient(app) as client:
        editor = client.get("/")
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
        config = client.get("/_marimo-studio/views/executive/config").json()

        _session_manager(app).get_session_by_file_key = Mock(return_value=object())
        view = client.get("/executive/")

    assert editor.status_code == 200
    assert "data-marimo-studio-runtime" not in editor.text
    assert default_workspace.status_code == 200
    assert '<option value="dashboard" selected>' in default_workspace.text
    assert workspace_redirect.status_code == 307
    assert workspace_redirect.headers["location"] == (
        "/studio/executive/?layout=preview"
    )
    assert workspace.status_code == 200
    assert "data-view-select" in workspace.text
    assert '<option value="executive" selected>' in workspace.text
    assert 'data-editor-frame src="/"' in workspace.text
    assert 'data-preview-frame src="about:blank"' in workspace.text
    assert 'href="/executive/"' in workspace.text
    assert 'data-view-prefix="/"' in workspace.text
    assert 'data-studio-prefix="/studio/"' in workspace.text
    assert view_redirect.status_code == 307
    assert view_redirect.headers["location"] == "/executive/?region=emea"
    assert waiting.status_code == 503
    assert waiting.headers["retry-after"] == "1"
    assert missing_view.status_code == 404
    assert view.status_code == 200
    assert config["runtimeUrl"] == "/"


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
        stylesheet = client.get("/_marimo-studio/views/executive/static/app.css")
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
        root = client.get("/", follow_redirects=False)
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
        missing = client.get("/definitely-missing/", follow_redirects=False)
        missing_studio = client.get(
            "/studio/definitely-missing/",
            follow_redirects=False,
        )

    assert root.status_code == 303
    assert root.headers["location"].startswith("/auth/login")
    assert named.status_code == 303
    assert named.headers["location"].startswith("/auth/login")
    login_query = parse_qs(urlsplit(named.headers["location"]).query)
    assert login_query["next"] == ["/executive/?region=emea"]
    assert establish.status_code == 303
    assert establish.headers["location"] == "/executive/?region=emea"
    assert "session=" in establish.headers["set-cookie"]
    assert page.status_code == 200
    assert protected.status_code == 200
    assert missing.status_code == 404
    assert missing_studio.status_code == 404
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
            "/studio/executive/?access_token=test-token",
            follow_redirects=False,
        )
        page = client.get(establish.headers["location"])

    workspace_login = parse_qs(urlsplit(workspace.headers["location"]).query)
    view_login = parse_qs(urlsplit(view.headers["location"]).query)
    assert workspace.status_code == 303
    assert workspace_login["next"] == ["/studio/executive/"]
    assert view.status_code == 303
    assert view_login["next"] == ["/executive/"]
    assert establish.status_code == 303
    assert establish.headers["location"] == "/studio/executive/"
    assert "session=" in establish.headers["set-cookie"]
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
        named = client.get("/executive/", follow_redirects=False)
        support = client.get("/_marimo-studio/views", follow_redirects=False)

    assert root.status_code == 303
    assert named.status_code == 303
    assert support.status_code == 303
    assert all(
        response.headers["location"].startswith("/auth/login")
        for response in (root, named, support)
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
        native = [
            client.get("/health"),
            client.get("/sse"),
            client.get("/favicon.ico"),
            client.get("/public-files-sw.js"),
        ]
        presentation = client.get("/dashboard/")

    assert all(response.status_code == 200 for response in native)
    assert presentation.status_code == 500
    assert presentation.text.startswith("Marimo Studio configuration error")


def test_middleware_is_inert_for_an_unconfigured_notebook(tmp_path: Path) -> None:
    notebook = tmp_path / "plain.py"
    notebook.write_text(
        notebook_source(tmp_path / "executed"),
        encoding="utf-8",
    )

    with TestClient(_marimo_app(notebook)) as client:
        page = client.get("/")
        support = client.get("/_marimo-studio/views")
    with TestClient(_marimo_app(notebook, token="test-token")) as client:
        missing = client.get("/definitely-missing/", follow_redirects=False)

    assert page.status_code == 200
    assert "data-marimo-studio-runtime" not in page.text
    assert support.status_code == 404
    assert missing.status_code == 404


def test_static_route_rejects_parent_paths(notebook_path: Path) -> None:
    studio = _configured(notebook_path)

    with TestClient(create_asgi_app(studio.notebook)) as client:
        traversal = client.get(
            "/_marimo-studio/views/dashboard/static/%2e%2e/%2e%2e/analysis.py"
        )

    assert traversal.status_code == 404
