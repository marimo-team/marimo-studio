from __future__ import annotations

import shutil
from collections.abc import MutableMapping
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from urllib.parse import parse_qs, quote, urlsplit

from marimo._server.workspace._directory import DirectoryWorkspace
from starlette.applications import Starlette
from starlette.routing import Mount
from starlette.testclient import TestClient

from marimo_studio import create_asgi_app
from marimo_studio._delivery.urls import (
    EDITOR_BINDING_CAPABILITY_QUERY_PARAM,
    SERVER_INSTANCE_QUERY_PARAM,
    authored_view_root_url,
)
from marimo_studio._server.studio.event_capability import (
    workspace_events_capability,
)
from marimo_studio._workspace.metadata import update_notebook_config

from ..app_helpers import configured as _configured
from ..app_helpers import edit_mode as _edit_mode
from ..app_helpers import marimo_app as _marimo_app
from ..app_helpers import session_manager as _session_manager
from ..helpers import notebook_source
from .app_test_support import (
    _assert_server_runtime,
    _projection_request,
    _projection_targets,
    _studio_host,
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

    assert cell.status_code == 404
    assert case_equivalent_cell.status_code == 404
    assert asset.status_code == 200
    assert asset.text == "notebook asset"
    assert service_worker.status_code == 200


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
        views = client.get("/_marimo-studio/views").json()

    assert dashboard["view"] == "dashboard"
    assert dashboard["views"] == ["dashboard", "executive"]
    dashboard_support = urlsplit(dashboard["supportUrl"])
    executive_support = urlsplit(executive["supportUrl"])
    assert dashboard_support.path.endswith("/_marimo-studio/views/dashboard")
    assert _projection_targets(dashboard, "value") == {"doubled"}
    assert _projection_targets(dashboard, "output") == {"doubled"}
    assert executive_support.path.endswith("/_marimo-studio/views/executive")
    assert _projection_targets(executive, "value") == {"x"}
    assert _projection_targets(executive, "output") == {"x"}
    assert dashboard["runtimeBindings"] == executive["runtimeBindings"]
    assert cell.status_code == 404
    assert views["schema"] == 1
    assert views["default_view"] == "dashboard"
    assert views["default_starter"] == "marimo-studio/vanilla:default"
    assert [item["name"] for item in views["views"]] == [
        "dashboard",
        "executive",
    ]
    starter_ids = [item["id"] for item in views["starters"]]
    assert views["default_starter"] in starter_ids
    assert len(starter_ids) == len(set(starter_ids))
    assert {
        "marimo-studio/react:default",
        "marimo-studio/svelte:default",
        "marimo-studio/vanilla:default",
    }.issubset(starter_ids)
    assert dashboard["runtime"]["data"]["preserveSession"] is True
    assert dashboard["showCellLogs"] is False
    expected_instance = dashboard["runtime"]["data"]["serverInstance"]
    assert parse_qs(dashboard_support.query)[SERVER_INSTANCE_QUERY_PARAM] == [
        expected_instance
    ]
    assert parse_qs(executive_support.query)[SERVER_INSTANCE_QUERY_PARAM] == [
        expected_instance
    ]


def test_directory_support_routes_keep_notebook_identity(tmp_path: Path) -> None:

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
    foreign_session = SimpleNamespace(
        initialization_id="second.py",
        app_file_manager=SimpleNamespace(path=str(second)),
    )
    manager.get_session = Mock(
        side_effect=lambda session_id: (
            foreign_session if str(session_id) == "second-session" else None
        )
    )
    server_token = str(manager.skew_protection_token)
    authored_root = authored_view_root_url("", "first.py")

    with TestClient(app) as client:
        config = client.get(
            "/_marimo-studio/views/dashboard/config?file=first.py"
        ).json()
        projection = _projection_request(config, "value", "doubled")
        cross_notebook_value = client.post(
            "/_marimo-studio/views/dashboard/values?file=first.py",
            headers={"Marimo-Session-Id": "second-session"},
            json={
                "revision": config["revision"],
                "projections": [projection],
            },
        )
        output_projection = _projection_request(config, "output", "doubled")
        cross_notebook_output = client.post(
            "/_marimo-studio/views/dashboard/outputs?file=first.py",
            headers={"Marimo-Session-Id": "second-session"},
            json={
                "revision": config["revision"],
                "projections": [output_projection],
                "activeProjections": [output_projection],
            },
        )
        created = client.post(
            "/_marimo-studio/views?file=first.py",
            headers={"Marimo-Server-Token": server_token},
            json={"name": "detail", "starter": "marimo-studio/vanilla:default"},
        )
        marimo_resource = client.get(f"{authored_root}dashboard/public-files-sw.js")
        authored_document = client.get(
            f"{authored_root}dashboard/?region=us",
            follow_redirects=False,
        )

    for response in (cross_notebook_value, cross_notebook_output):
        assert response.status_code == 409
        assert response.json()["error"] == "unknown-session"
    assert config["rootUrl"] == "/"
    assert config["publicRootUrl"] == "/?file=first.py"
    assert config["documentRootUrl"] == authored_root
    _assert_server_runtime(config["runtime"]["data"], "/")
    assert config["runtime"]["data"]["file"] == "first.py"
    assert created.status_code == 201
    assert created.json() == {"schema": 2, "name": "detail"}
    assert marimo_resource.status_code == 200
    assert authored_document.status_code == 307
    assert authored_document.headers["location"] == (
        "/dashboard/?file=first.py&region=us"
    )


def test_mounted_directory_routes_preserve_notebook_identity(tmp_path: Path) -> None:

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


def test_mounted_directory_host_promotes_with_canonical_urls(tmp_path: Path) -> None:

    notebook = tmp_path / "nested" / "analysis.py"
    notebook.parent.mkdir()
    notebook.write_text(notebook_source(tmp_path / "output"), encoding="utf-8")
    studio = _configured(notebook)
    shutil.rmtree(studio.view_root)
    child = _marimo_app(notebook, path="/base", programmatic=True)
    _edit_mode(child)
    _session_manager(child).workspace = DirectoryWorkspace(
        str(tmp_path),
        include_markdown=False,
    )
    parent = Starlette(routes=[Mount("/parent", app=child)])
    file_key = "nested/analysis.py"

    with TestClient(parent) as client:
        document = client.get(f"/parent/base/?file={file_key}&region=eu")
        host = _studio_host(document.text)
        created = client.post(
            host["urls"]["views"],
            headers={"Marimo-Server-Token": host["serverToken"]},
            json={
                "name": "dashboard",
                "starter": "marimo-studio/vanilla:default",
            },
        )
        ready = client.get(f"{host['urls']['bootstrap']}&marimo_studio_view=dashboard")
        stale = client.get(
            host["urls"]["bootstrap"].replace(host["serverInstance"], "stale")
        )

    assert host["state"] == "needs-view"
    assert created.status_code == 201
    assert ready.status_code == 200
    assert stale.status_code == 204
    bootstrap = ready.json()
    assert bootstrap["clientId"] == host["clientId"]
    assert bootstrap["selectedView"] == "dashboard"
    workspace_query = {
        "file": [file_key],
        "marimo_studio_client": [host["clientId"]],
        "marimo_studio_server": [host["serverInstance"]],
    }
    expected_query = {
        **workspace_query,
        "region": ["eu"],
        "session_id": parse_qs(urlsplit(host["urls"]["bootstrap"]).query)["session_id"],
        EDITOR_BINDING_CAPABILITY_QUERY_PARAM: parse_qs(
            urlsplit(host["urls"]["bootstrap"]).query
        )[EDITOR_BINDING_CAPABILITY_QUERY_PARAM],
    }
    editor = urlsplit(bootstrap["urls"]["editor"])
    assert editor.path == "/parent/base/_marimo-studio/editor/"
    assert parse_qs(editor.query) == expected_query
    assert parse_qs(urlsplit(host["urls"]["bootstrap"]).query)["region"] == ["eu"]
    events = urlsplit(bootstrap["urls"]["events"])
    assert events.path == "/parent/base/_marimo-studio/dev/events"
    assert parse_qs(events.query) == {
        **workspace_query,
        "marimo_studio_events": [
            workspace_events_capability(
                host["serverToken"],
                file_key,
                "/parent/base",
                host["clientId"],
            )
        ],
        "marimo_studio_view": ["dashboard"],
    }
    studio_prefix = urlsplit(bootstrap["urls"]["studioPrefix"])
    assert studio_prefix.path == "/parent/base/studio/"
    assert parse_qs(studio_prefix.query) == {"file": [file_key]}
    view_prefix = urlsplit(bootstrap["urls"]["viewPrefix"])
    assert view_prefix.path == "/parent/base/"
    assert parse_qs(view_prefix.query) == {"file": [file_key]}


def test_directory_auth_precedes_notebook_configuration(tmp_path: Path) -> None:

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
