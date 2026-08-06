from __future__ import annotations

import asyncio
import json
import os
import shutil
from collections.abc import MutableMapping
from html.parser import HTMLParser
from importlib.metadata import entry_points
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock
from urllib.parse import parse_qs, quote, urlencode, urlsplit

import marimo
import pytest
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.routing import Mount
from starlette.testclient import TestClient

import marimo_studio._compat.server.replay as replay_compat
from marimo_studio import create_asgi_app
from marimo_studio._compat.notebook import load_static_notebook
from marimo_studio._compat.server.programmatic import programmatic_middleware
from marimo_studio._server import dev
from marimo_studio._workspace import load_studio
from marimo_studio._workspace.metadata import update_notebook_config
from marimo_studio._workspace.models import StudioConfig
from marimo_studio.workspace import bind_cell, ensure_view

from .helpers import empty_notebook_source, notebook_source, replace_app_shell


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


def _set_shell(studio: StudioConfig, view_name: str, content: str) -> None:
    template = studio.views[view_name].template
    template.write_text(
        replace_app_shell(template.read_text(encoding="utf-8"), content),
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
    skew_protection: bool = False,
) -> Any:
    return (
        marimo.create_asgi_app(
            quiet=True,
            token=token,
            skew_protection=skew_protection,
        )
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
        named = client.get("/executive/")
        explicit_index = client.get("/executive/index.html")

    assert default.status_code == 200
    assert default.text.count('id="marimo-runtime-root"') == 1
    assert '"/_marimo-studio/views/dashboard"' in default.text
    assert default.text.index("runtime.css") < default.text.index("app.css")
    assert named.status_code == 200
    assert '"/_marimo-studio/views/executive"' in named.text
    assert explicit_index.url.path == "/executive/"
    assert explicit_index.text.count('id="marimo-runtime-root"') == 1


def test_view_directory_serves_native_module_graphs(notebook_path: Path) -> None:
    studio = _configured(notebook_path)
    view = studio.views["dashboard"]
    scripts = view.root / "scripts"
    scripts.mkdir()
    module = scripts / "app.js"
    dependency = scripts / "message.js"
    module.write_text(
        'import { message } from "./message.js";\nwindow.message = message;\n',
        encoding="utf-8",
    )
    dependency.write_text('export const message = "ready";\n', encoding="utf-8")
    view.template.write_text(
        view.template.read_text(encoding="utf-8").replace(
            "</head>",
            '<script type="module" src="scripts/app.js"></script>\n  </head>',
        ),
        encoding="utf-8",
    )

    with TestClient(create_asgi_app(studio.notebook)) as client:
        before = client.get("/")
        source = client.get("/dashboard/scripts/app.js")
        imported = client.get("/dashboard/scripts/message.js")
        dependency.write_text('export const message = "fresh";\n', encoding="utf-8")
        after = client.get("/")

    assert '<base href="/dashboard/">' in before.text
    assert '<script type="module" src="scripts/app.js"></script>' in before.text
    assert source.status_code == 200
    assert source.headers["content-type"].startswith("text/javascript")
    assert 'from "./message.js"' in source.text
    assert imported.text == 'export const message = "ready";\n'
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
    assert dashboard["runtime"]["data"]["preserveSession"] is True
    assert dashboard["showCellLogs"] is False


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


def test_edit_workspace_queues_public_query_state(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    studio = _configured(notebook_path)
    app = _marimo_app(studio.notebook)
    _edit_mode(app)
    received: list[dict[str, str | list[str]]] = []
    monkeypatch.setattr(
        "marimo_studio._server.support.queue_query_sync",
        lambda _context, query: received.append(query),
    )
    headers = {"Marimo-Server-Token": str(_session_manager(app).skew_protection_token)}

    with TestClient(app) as client:
        response = client.post(
            "/_marimo-studio/query",
            headers=headers,
            json={"query": "?region=emea&region=apac&empty="},
        )

    assert response.status_code == 202
    assert received == [{"region": ["emea", "apac"], "empty": ""}]


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


def test_view_document_and_runtime_config_publish_one_revision(
    notebook_path: Path,
) -> None:
    studio = _configured(notebook_path)

    with TestClient(create_asgi_app(studio.notebook)) as client:
        first_page = client.get("/")
        first_config = client.get("/_marimo-studio/views/dashboard/config").json()
        template = studio.views["dashboard"].template
        template.write_text(
            template.read_text(encoding="utf-8") + "\n<!-- changed -->\n",
            encoding="utf-8",
        )
        interleaved_config = client.get("/_marimo-studio/views/dashboard/config").json()
        second_page = client.get("/")
        second_config = client.get("/_marimo-studio/views/dashboard/config").json()

    first_revision = first_page.headers["Marimo-Studio-Revision"]
    second_revision = second_page.headers["Marimo-Studio-Revision"]
    assert first_config["revision"] == first_revision
    assert interleaved_config["revision"] != first_revision
    assert second_config["revision"] == second_revision
    assert second_revision != first_revision


def test_root_document_tracks_a_changed_default_view(notebook_path: Path) -> None:
    studio = _configured(notebook_path)

    with TestClient(create_asgi_app(studio.notebook)) as client:
        dashboard = client.get("/")

        def select_executive(config: MutableMapping[str, object]) -> None:
            config["default"] = "executive"

        update_notebook_config(studio.notebook, select_executive)
        executive = client.get("/")
        config = client.get("/_marimo-studio/views/executive/config").json()

    assert dashboard.headers["Marimo-Studio-Support-Url"].endswith("/views/dashboard")
    assert executive.headers["Marimo-Studio-Support-Url"].endswith("/views/executive")
    assert executive.headers["Marimo-Studio-Revision"] == config["revision"]
    assert (
        executive.headers["Marimo-Studio-Revision"]
        != dashboard.headers["Marimo-Studio-Revision"]
    )


def test_view_identity_is_part_of_the_presentation_revision(
    notebook_path: Path,
) -> None:
    studio = _configured(notebook_path)
    shared = "<html><head></head><body><main id='app-shell'></main></body></html>"
    for view in studio.views.values():
        view.template.write_text(shared, encoding="utf-8")
    timestamp = studio.views["dashboard"].template.stat().st_mtime_ns
    for view in studio.views.values():
        os.utime(view.template, ns=(timestamp, timestamp))

    with TestClient(create_asgi_app(studio.notebook)) as client:
        dashboard = client.get("/")
        executive = client.get("/executive/")

    assert (
        dashboard.headers["Marimo-Studio-Revision"]
        != executive.headers["Marimo-Studio-Revision"]
    )


def test_presentation_revision_tracks_same_size_edits(
    notebook_path: Path,
) -> None:
    studio = _configured(notebook_path)
    template = studio.views["dashboard"].template

    with TestClient(create_asgi_app(studio.notebook)) as client:
        before = client.get("/")
        source = template.read_text(encoding="utf-8")
        stat = template.stat()
        template.write_text(
            source.replace("app.css", "alt.css"),
            encoding="utf-8",
        )
        os.utime(template, ns=(stat.st_atime_ns, stat.st_mtime_ns))
        after = client.get("/")

    assert (
        before.headers["Marimo-Studio-Revision"]
        != after.headers["Marimo-Studio-Revision"]
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
    static_indexes = {cell.runtime_id: index for index, cell in enumerate(static.cells)}
    for identity, runtime_id in initial["runtime"]["controls"]["cells"].items():
        index = static_indexes[runtime_id]
        assert first["runtime"]["controls"]["cells"][identity] == f"first-{index}"
        assert second["runtime"]["controls"]["cells"][identity] == f"second-{index}"


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

    assert messages[0] == b"event: ready\ndata: {}\n\n"
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


def test_document_replay_requires_an_opted_in_manager_and_query() -> None:
    class Manager:
        pass

    manager = Manager()
    other_manager = Manager()
    session = SimpleNamespace(disconnect_main_consumer=Mock())
    handler = SimpleNamespace(_reconnect_session=Mock())
    reconnect = Mock(return_value=("fallback", "new"))

    replay_compat._DOCUMENT_REPLAY_MANAGERS.add(manager)

    def connector(active_manager: Manager, requested: bool) -> SimpleNamespace:
        query = {replay_compat.DOCUMENT_REPLAY_QUERY_PARAM: "1"} if requested else {}
        return SimpleNamespace(
            manager=active_manager,
            connection=SimpleNamespace(query_params=query),
            handler=handler,
        )

    replayed = replay_compat._reconnect_with_document_replay(
        connector(manager, True),
        session,
        reconnect,
        "reconnect",
    )
    unmarked = replay_compat._reconnect_with_document_replay(
        connector(manager, False),
        session,
        reconnect,
        "reconnect",
    )
    unregistered = replay_compat._reconnect_with_document_replay(
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


def test_document_replay_follows_the_verified_presentation(
    notebook_path: Path,
) -> None:
    studio = _configured(notebook_path)

    def preserve(config: MutableMapping[str, object]) -> None:
        config["preserve_session"] = True

    update_notebook_config(studio.notebook, preserve)
    app = create_asgi_app(studio.notebook)
    manager = _session_manager(app)

    with TestClient(app) as client:
        assert client.get("/").status_code == 200
        assert manager in replay_compat._DOCUMENT_REPLAY_MANAGERS

        def reset(config: MutableMapping[str, object]) -> None:
            config["preserve_session"] = False

        update_notebook_config(studio.notebook, reset)
        assert client.get("/").status_code == 200

    assert manager not in replay_compat._DOCUMENT_REPLAY_MANAGERS


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
    assert config["runtime"]["data"]["url"] == "/parent/base/"
    assert config["supportUrl"] == "/parent/base/_marimo-studio/views/dashboard"
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
    expected_editor = "/parent/base/?" + urlencode({"file": str(studio.notebook)})
    bootstrap = _studio_bootstrap(workspace.text)
    assert bootstrap["urls"]["editor"] == expected_editor
    assert bootstrap["urls"]["viewPrefix"] == "/parent/base/"
    assert bootstrap["urls"]["studioPrefix"] == "/parent/base/studio/"
    assert config["rootUrl"] == "/parent/base/"
    assert config["runtime"]["data"]["url"] == "/parent/base/"
    assert all(response.status_code == 404 for response in outside)


def test_edit_mode_enters_studio_and_embeds_the_native_editor(
    notebook_path: Path,
) -> None:
    studio = _configured(notebook_path)
    app = _marimo_app(studio.notebook)
    _edit_mode(app)
    expected_editor = "/?" + urlencode({"file": str(studio.notebook)})

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
    landing_editor = "/?" + urlencode(
        [
            ("region", "emea"),
            ("region", "apac"),
            ("empty", ""),
            ("file", str(studio.notebook)),
        ]
    )
    assert _studio_bootstrap(landing_workspace.text)["urls"]["editor"] == (
        landing_editor
    )
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

    assert missing.status_code == 401
    assert missing.json()["error"] == "missing-server-token"
    assert invalid.status_code == 401
    assert invalid.json()["error"] == "invalid-server-token"
    assert valid.status_code == 204
    assert missing_delete.status_code == 401
    assert missing_delete.json()["error"] == "missing-server-token"
    assert invalid_delete.status_code == 401
    assert invalid_delete.json()["error"] == "invalid-server-token"


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

    assert loaded.status_code == 200
    assert write.status_code == 403
    assert write.json()["error"] == "edit-access-required"
    assert create.status_code == 403
    assert create.json()["error"] == "edit-access-required"
    assert delete.status_code == 403
    assert delete.json()["error"] == "edit-access-required"


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
