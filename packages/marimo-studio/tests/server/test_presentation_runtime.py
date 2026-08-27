from __future__ import annotations

import threading
import time
from collections.abc import MutableMapping
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock
from urllib.parse import parse_qs, urlsplit

import marimo
import pytest
from starlette.testclient import TestClient

import marimo_studio._views.presentation_publication as presentation_module
from marimo_studio import create_asgi_app
from marimo_studio._compat.notebook import load_static_notebook
from marimo_studio._compat.server.session_replay import PrivateSessionReplay
from marimo_studio._delivery.urls import (
    SERVER_INSTANCE_QUERY_PARAM,
)
from marimo_studio._server.presentation.capability import (
    parse_presentation_capability,
)
from marimo_studio._views.api import bind_cell, prepare_view
from marimo_studio._views.build import build_view_project_sync
from marimo_studio._workspace import load_studio
from marimo_studio._workspace.metadata import update_notebook_config
from marimo_studio._workspace.models import StudioWorkspace

from ..app_helpers import configured as _configured
from ..app_helpers import edit_mode as _edit_mode
from ..app_helpers import marimo_app as _marimo_app
from ..app_helpers import session_manager as _session_manager
from ..app_helpers import set_shell as _set_shell
from ..helpers import notebook_source
from .app_test_support import (
    _live_test_session,
    _presentation_fallback_url,
    _presentation_frame_url,
)


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
    prepare_view(notebook)
    studio = load_studio(notebook)
    _set_shell(studio, "dashboard", '<marimo-cell name="imports"></marimo-cell>')
    configured_source = notebook.read_text(encoding="utf-8")

    with TestClient(create_asgi_app(notebook)) as client:
        notebook.write_text(
            configured_source.replace("def imports():", "def _():", 1),
            encoding="utf-8",
        )
        page = client.get("/")
        presentation = client.get(_presentation_fallback_url(page.text))
        broken = client.get("/_marimo-studio/views/dashboard/config").json()
        fragment = client.get("/_marimo-studio/views/dashboard/cells/imports")

        notebook.write_text(configured_source, encoding="utf-8")
        repaired = client.get("/_marimo-studio/views/dashboard/config").json()

    assert page.status_code == 200
    assert presentation.status_code == 200
    assert '<marimo-cell name="imports"' in presentation.text
    assert "imports" not in broken["projectionTargets"]["cells"]
    assert len(broken["diagnostics"]) == 1
    diagnostic = broken["diagnostics"][0]
    assert diagnostic["code"] == "projection-cell-not-found"
    assert diagnostic["severity"] == "error"
    assert diagnostic["view"] == "dashboard"
    assert diagnostic["projection"] == "cell"
    assert diagnostic["target"] == "imports"
    assert diagnostic["source"]["path"] == str(
        (studio.views["dashboard"].root / "index.html").relative_to(notebook.parent)
    )
    assert diagnostic["source"]["line"] > 0
    assert diagnostic["hint"] == ""
    assert fragment.status_code == 404
    assert repaired["diagnostics"] == []
    producer = repaired["projectionTargets"]["cells"]["imports"]["producer"]
    assert repaired["runtimeBindings"]["cellRefs"][producer]


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


def test_view_project_error_has_a_repair_diagnostic(notebook_path: Path) -> None:
    studio = _configured(notebook_path)
    with build_view_project_sync(
        studio.views["dashboard"],
        profile="production",
    ):
        pass
    template = studio.views["dashboard"].root / "index.html"
    template.write_text(
        template.read_text(encoding="utf-8").replace(
            'id="app-shell"',
            'id="application"',
        ),
        encoding="utf-8",
    )

    edit_app = _marimo_app(studio.notebook)
    _edit_mode(edit_app)
    with TestClient(create_asgi_app(studio.notebook)) as client:
        config = client.get("/_marimo-studio/views/dashboard/config")
        page = client.get("/")
        presentation = client.get(_presentation_fallback_url(page.text))
    with TestClient(edit_app) as client:
        project = client.get("/_marimo-studio/views/dashboard/project").json()

    assert config.status_code == 200
    assert page.status_code == 200
    assert presentation.status_code == 200
    assert 'id="app-shell"' in presentation.text
    assert project["build"]["phase"] == "stale"
    assert project["build"]["diagnostics"][0]["code"] == "entry-document-invalid"
    assert (
        "expected one element with id" in project["build"]["diagnostics"][0]["message"]
    )


def test_edit_view_keeps_last_good_artifact_during_source_repairs(
    notebook_path: Path,
) -> None:
    studio = _configured(notebook_path)
    template = studio.views["dashboard"].root / "index.html"
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
        presentation = client.get(_presentation_frame_url(page.text))
        project = client.get("/_marimo-studio/views/dashboard/project").json()

    assert page.status_code == 200
    assert (
        'sandbox="allow-downloads allow-forms allow-modals allow-pointer-lock '
        in page.text
    )
    assert 'id="app-shell"' in presentation.text
    assert project["build"]["phase"] == "stale"
    assert project["build"]["diagnostics"][0]["code"] == "entry-document-invalid"


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
    prepare_view(notebook)
    studio = load_studio(notebook)
    _set_shell(studio, "dashboard", '<marimo-cell name="imports"></marimo-cell>')
    static = load_static_notebook(notebook)
    app = _marimo_app(notebook)
    _edit_mode(app)
    session = _live_test_session(
        tuple(
            SimpleNamespace(code=cell.code, id=cell.runtime_id, name="_")
            for cell in static.cells
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
        assert pending.status_code == 200
    source_payload = source_pending.json()
    stale_producer = source_payload["projectionTargets"]["cells"]["imports"]["producer"]
    assert stale_producer not in source_payload["runtimeBindings"]["cellRefs"]
    assert (
        static.cells[1].runtime_id
        in source_payload["runtimeBindings"]["cellRefs"].values()
    )
    assert ready.status_code == 200
    payload = ready.json()
    producer = payload["projectionTargets"]["cells"]["imports"]["producer"]
    assert (
        payload["runtimeBindings"]["cellRefs"][producer] == static.cells[0].runtime_id
    )


def test_runtime_config_waits_for_semantic_change_then_accepts_exact_execution(
    notebook_path: Path,
) -> None:
    studio = _configured(notebook_path)
    static = load_static_notebook(studio.notebook)
    rows = tuple(
        SimpleNamespace(code=cell.code, id=cell.runtime_id, name=cell.name)
        for cell in static.cells
    )
    session = _live_test_session(rows)
    app = _marimo_app(studio.notebook)
    _edit_mode(app)
    _session_manager(app).get_session_by_file_key = Mock(return_value=session)
    source = studio.notebook.read_text(encoding="utf-8")
    studio.notebook.write_text(source.replace("x = 2", "x = 3"), encoding="utf-8")
    updated = load_static_notebook(studio.notebook)
    session.document.cells = tuple(
        SimpleNamespace(code=cell.code, id=cell.runtime_id, name=cell.name)
        for cell in updated.cells
    )

    with TestClient(app) as client:
        pending = client.get("/_marimo-studio/views/dashboard/config")
        runtime_id = updated.cells[0].runtime_id
        session.session_view.last_executed_code[runtime_id] = updated.cells[0].code
        ready = client.get("/_marimo-studio/views/dashboard/config")

    assert pending.status_code == 409
    assert pending.json() == {
        "error": "runtime-sync-pending",
        "message": (
            "Studio is waiting for the notebook kernel to apply the saved source."
        ),
        "transient": True,
    }
    assert ready.status_code == 200


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
    prepare_view(notebook)
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
        return_value=_live_test_session(rows)
    )

    with TestClient(app) as client:
        response = client.get("/_marimo-studio/views/dashboard/config")

    assert response.status_code == 200
    payload = response.json()
    producer = payload["projectionTargets"]["cells"]["imports"]["producer"]
    assert (
        payload["runtimeBindings"]["cellRefs"][producer] == static.cells[0].runtime_id
    )


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
    session = _live_test_session(
        (SimpleNamespace(code="unrelated = 1", id="live-unrelated", name="_"),)
    )
    _session_manager(app).get_session_by_file_key = Mock(return_value=session)

    with TestClient(app) as client:
        pending = client.get("/_marimo-studio/views/dashboard/config")
        session.document.cells = rows
        session.session_view.last_executed_code = {row.id: row.code for row in rows}
        dashboard = client.get("/_marimo-studio/views/dashboard/config").json()
        executive = client.get("/_marimo-studio/views/executive/config").json()

    assert pending.status_code == 200
    assert pending.json()["runtimeBindings"]["cellRefs"] == {}
    result_ref = dashboard["projectionTargets"]["cells"]["result"]["producer"]
    x_ref = executive["projectionTargets"]["variables"]["x"]["producer"]
    doubled_ref = dashboard["projectionTargets"]["variables"]["doubled"]["producer"]
    assert dashboard["runtimeBindings"]["cellRefs"][result_ref] == "live-1"
    assert executive["runtimeBindings"]["cellRefs"][x_ref] == "live-0"
    assert dashboard["runtimeBindings"]["cellRefs"][doubled_ref] == "live-1"


def test_presentation_revision_tracks_view_and_entry_identity(
    notebook_path: Path,
) -> None:
    studio = _configured(notebook_path)
    shared = (
        "<html><head><style>body { color: black; }</style></head>"
        "<body><main id='app-shell'></main></body></html>"
    )
    for view in studio.views.values():
        (view.root / "index.html").write_text(shared, encoding="utf-8")
    template = studio.views["dashboard"].root / "index.html"
    adjacent = studio.views["dashboard"].root / "notes.txt"

    with TestClient(create_asgi_app(studio.notebook)) as client:
        dashboard = client.get("/")
        dashboard_config = client.get("/_marimo-studio/views/dashboard/config").json()
        executive = client.get("/executive/")
        template.write_text(
            shared.replace("color: black", "color: navy"),
            encoding="utf-8",
        )
        deadline = time.monotonic() + 2
        while True:
            edited_config = client.get("/_marimo-studio/views/dashboard/config").json()
            if (
                edited_config["revision"] != dashboard_config["revision"]
                or time.monotonic() >= deadline
            ):
                break
            time.sleep(0.05)
        edited = client.get("/")
        adjacent.write_text("not a declared Vanilla input", encoding="utf-8")
        adjacent_config = client.get("/_marimo-studio/views/dashboard/config").json()

    dashboard_revision = dashboard.headers["Marimo-Studio-Revision"]
    edited_revision = edited.headers["Marimo-Studio-Revision"]
    assert dashboard_config["revision"] == dashboard_revision
    assert executive.headers["Marimo-Studio-Revision"] != dashboard_revision
    assert edited_config["revision"] == edited_revision
    assert edited_revision != dashboard_revision
    assert adjacent_config["revision"] == edited_revision


def test_blocked_view_build_keeps_cached_other_view_requests_available(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    studio = _configured(notebook_path)
    capture = presentation_module.capture_presentations
    build_started = threading.Event()
    release_build = threading.Event()
    blocked = False

    def block_dashboard_build(
        workspace: StudioWorkspace,
        view_names: tuple[str, ...] | None = None,
        **options: Any,
    ) -> Any:
        nonlocal blocked
        if view_names == ("dashboard",) and not blocked:
            blocked = True
            build_started.set()
            if not release_build.wait(timeout=2):
                raise RuntimeError("dashboard build was not released")
        return capture(workspace, view_names, **options)

    with TestClient(create_asgi_app(studio.notebook)) as client:
        executive = client.get("/_marimo-studio/views/executive/config")
        monkeypatch.setattr(
            presentation_module,
            "capture_presentations",
            block_dashboard_build,
        )
        with ThreadPoolExecutor(max_workers=2) as executor:
            dashboard_future = executor.submit(
                client.get,
                "/_marimo-studio/views/dashboard/config",
            )
            assert build_started.wait(timeout=2)
            heartbeat = client.get("/_marimo-studio/status")
            executive_future = executor.submit(
                client.get,
                "/_marimo-studio/views/executive/config",
            )
            try:
                cached_executive = executive_future.result(timeout=1)
                assert not dashboard_future.done()
            finally:
                release_build.set()
            dashboard = dashboard_future.result(timeout=2)

    assert heartbeat.status_code == 200
    assert executive.status_code == 200
    assert cached_executive.status_code == 200
    assert dashboard.status_code == 200
    assert cached_executive.json()["revision"] == executive.json()["revision"]


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
    expanded = '''\
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
    prepare_view(notebook)
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
        SimpleNamespace(code=expanded, id="live-report", name="_"),
    )
    session = _live_test_session(rows)
    _session_manager(app).get_session_by_file_key = Mock(return_value=session)

    with TestClient(app) as client:
        response = client.get("/_marimo-studio/views/dashboard/config")

    assert response.status_code == 200
    payload = response.json()
    producer = payload["projectionTargets"]["cells"]["report"]["producer"]
    assert payload["runtimeBindings"]["cellRefs"][producer] == "live-report"


def test_run_runtime_config_rejects_caller_session_authority(
    notebook_path: Path,
) -> None:
    studio = _configured(notebook_path)
    app = _marimo_app(studio.notebook)
    static = load_static_notebook(studio.notebook)

    foreign_session = _live_test_session(
        tuple(
            SimpleNamespace(code=cell.code, id=f"first-{index}", name=cell.name)
            for index, cell in enumerate(static.cells)
        ),
        initialization_id=str(studio.notebook),
        path=str(studio.notebook),
    )
    _session_manager(app).get_session = Mock(
        side_effect=lambda session_id: (
            foreign_session if str(session_id) == "s_first1" else None
        )
    )
    with TestClient(app) as client:
        config = client.get(
            "/_marimo-studio/views/dashboard/config",
            headers={"Marimo-Session-Id": "s_first1"},
        ).json()
    capability = parse_presentation_capability(
        config["runtime"]["data"]["capabilityToken"]
    )
    result_ref = config["projectionTargets"]["cells"]["result"]["producer"]

    assert capability is not None
    assert capability.session_id != "s_first1"
    assert capability.runtime_session_id not in {"s_first1", capability.session_id}
    assert config["runtime"]["data"]["sessionId"] == capability.runtime_session_id
    assert (
        config["runtimeBindings"]["cellRefs"][result_ref] == static.cells[1].runtime_id
    )
    assert set(config["runtimeBindings"]["cellRefs"].values()) == {
        cell.runtime_id for cell in static.cells
    }


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
