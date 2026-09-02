from __future__ import annotations

import asyncio
from collections.abc import MutableMapping
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from urllib.parse import parse_qs, urlencode, urlsplit

import pytest
from starlette.requests import Request
from starlette.testclient import TestClient

from marimo_studio import create_asgi_app
from marimo_studio._delivery.urls import (
    ACTIVE_VIEW_QUERY_PARAM,
    SERVER_INSTANCE_QUERY_PARAM,
    STUDIO_CLIENT_QUERY_PARAM,
    WORKSPACE_EVENTS_CAPABILITY_QUERY_PARAM,
    WORKSPACE_STREAM_QUERY_PARAM,
)
from marimo_studio._server.notebook_scope import NotebookScope
from marimo_studio._server.records import ServerContext
from marimo_studio._server.server_instance import server_instance_id
from marimo_studio._server.studio.event_capability import (
    workspace_events_capability,
)
from marimo_studio._server.support import events_response
from marimo_studio._views.build import build_view_project_sync
from marimo_studio._workspace.metadata import update_notebook_config

from ..app_helpers import configured as _configured
from ..app_helpers import edit_mode as _edit_mode
from ..app_helpers import marimo_app as _marimo_app
from ..app_helpers import session_manager as _session_manager
from ..helpers import notebook_source
from .app_test_support import _studio_host


def test_edit_workspace_mutations_require_the_current_server_token(
    notebook_path: Path,
) -> None:
    studio = _configured(notebook_path)
    app = _marimo_app(studio.notebook, skew_protection=True)
    _edit_mode(app)
    token = str(_session_manager(app).skew_protection_token)

    with TestClient(app) as client:
        loaded = client.get("/_marimo-studio/views/dashboard/source/index.html")
        project = client.get("/_marimo-studio/views/dashboard/project").json()
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
            headers={
                **source_headers,
                "Marimo-Server-Token": token,
                "Marimo-Studio-Catalog-Generation": project["catalog_generation"],
                "Marimo-Studio-View-Generation": project["view_generation"],
            },
        )
        missing_delete = client.delete("/_marimo-studio/views/executive")
        invalid_delete = client.delete(
            "/_marimo-studio/views/executive",
            headers={"Marimo-Server-Token": "stale-token"},
        )
        missing_analysis = client.post(
            "/_marimo-studio/validate",
            json={"schema": 1, "view": "dashboard"},
        )
        invalid_activation = client.patch(
            "/_marimo-studio/views/dashboard/show",
            headers={"Marimo-Server-Token": "stale-token"},
            json={"schema": 1, "browser_client": None},
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
    assert invalid_delete.status_code == 401
    assert missing_analysis.status_code == 401
    assert invalid_activation.status_code == 401
    assert missing_observation.status_code == 401


def test_run_mode_keeps_studio_source_mutations_read_only(
    notebook_path: Path,
) -> None:
    studio = _configured(notebook_path)

    with TestClient(create_asgi_app(studio.notebook)) as client:
        loaded = client.get("/_marimo-studio/views/dashboard/source/index.html")
        project = client.get("/_marimo-studio/views/dashboard/project")
        config = client.get("/_marimo-studio/views/dashboard/config").json()
        headers = {"Marimo-Server-Token": config["runtime"]["data"]["capabilityToken"]}
        write = client.put(
            "/_marimo-studio/views/dashboard/source/index.html",
            content="<!doctype html>",
            headers={"If-Match": "sha256:stale", **headers},
        )
        create = client.post(
            "/_marimo-studio/views",
            json={
                "name": "operations",
                "starter": "marimo-studio/vanilla:default",
            },
            headers=headers,
        )
        delete = client.delete(
            "/_marimo-studio/views/executive",
            headers=headers,
        )
        analysis = client.post(
            "/_marimo-studio/validate",
            json={"schema": 1, "view": "dashboard"},
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
            "/_marimo-studio/views/dashboard/show",
            headers=headers,
            json={"schema": 1, "browser_client": None},
        )
        observation = client.put(
            "/_marimo-studio/views/dashboard/observation",
            json={},
            headers=headers,
        )

    for response in (loaded, project, write, delete, activation, observation):
        assert response.status_code == 403
    for response in (create, analysis, observations):
        assert response.status_code == 401
    assert loaded.json()["error"] == "edit-access-required"


def test_read_only_workspace_stream_cannot_register_a_browser(
    notebook_path: Path,
) -> None:
    studio = _configured(notebook_path)
    token = "server-token"
    client_id = "browser-client-1234"
    query = urlencode(
        {
            "marimo_studio_client": client_id,
            "marimo_studio_server": server_instance_id(token),
            "marimo_studio_view": "dashboard",
        }
    )
    request = Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": "/_marimo-studio/dev/events",
            "raw_path": b"/_marimo-studio/dev/events",
            "query_string": query.encode(),
            "headers": [],
            "client": ("test", 123),
            "server": ("test", 80),
            "auth": SimpleNamespace(scopes=("read",)),
        }
    )
    scope = NotebookScope.create(studio.notebook)
    context = cast(
        ServerContext,
        SimpleNamespace(server_token=token, dev=True),
    )
    response = events_response(
        request,
        studio,
        context,
        scope,
        server=cast(Any, SimpleNamespace(shutdown_requested=lambda _context: False)),
    )

    assert response.status_code == 403
    assert asyncio.run(scope.clients.target_for_client(client_id)) is None


def test_workspace_stream_capability_precedes_client_state_mutation(
    notebook_path: Path,
) -> None:
    studio = _configured(notebook_path)
    token = "server-token"
    client_id = "browser-client-1234"
    context = cast(
        ServerContext,
        SimpleNamespace(
            base_url="",
            dev=True,
            file_key="notebook.py",
            mode="edit",
            server_token=token,
        ),
    )
    scope = NotebookScope.create(studio.notebook)
    server = cast(Any, SimpleNamespace(shutdown_requested=lambda _context: False))

    def request(capability: str | None) -> Request:
        query = {
            STUDIO_CLIENT_QUERY_PARAM: client_id,
            SERVER_INSTANCE_QUERY_PARAM: server_instance_id(token),
            ACTIVE_VIEW_QUERY_PARAM: "executive",
            WORKSPACE_STREAM_QUERY_PARAM: str(9_007_199_254_740_991),
        }
        if capability is not None:
            query[WORKSPACE_EVENTS_CAPABILITY_QUERY_PARAM] = capability
        return Request(
            {
                "type": "http",
                "http_version": "1.1",
                "method": "GET",
                "scheme": "http",
                "path": "/_marimo-studio/dev/events",
                "raw_path": b"/_marimo-studio/dev/events",
                "query_string": urlencode(query).encode(),
                "headers": [],
                "client": ("test", 123),
                "server": ("test", 80),
                "auth": SimpleNamespace(scopes=("edit",)),
            }
        )

    async def exercise() -> tuple[list[int], int]:
        initial = await scope.clients.connect_stream(client_id, 1, "dashboard")
        assert initial is not None
        assert await scope.clients.begin_active_view_handoff(
            client_id,
            "activation-1",
            "dashboard",
            "executive",
        )
        stale = workspace_events_capability(
            "stale-token",
            context.file_key,
            context.base_url,
            client_id,
        )
        statuses = [
            events_response(
                request(capability),
                studio,
                context,
                scope,
                server=server,
            ).status_code
            for capability in (None, "0" * 64, stale)
        ]
        assert await scope.clients.rollback_active_view_handoff(
            client_id,
            "activation-1",
        )
        replacement = await scope.clients.connect_stream(client_id, 2, "dashboard")
        assert replacement is not None
        authorized = events_response(
            request(
                workspace_events_capability(
                    token,
                    context.file_key,
                    context.base_url,
                    client_id,
                )
            ),
            studio,
            context,
            scope,
            server=server,
        ).status_code
        await scope.clients.release_stream(replacement)
        await scope.clients.release_stream(initial)
        await scope.close()
        return statuses, authorized

    statuses, authorized = asyncio.run(exercise())
    assert statuses == [403, 403, 403]
    assert authorized == 200


def test_view_project_errors_stay_scoped_to_the_selected_view(
    notebook_path: Path,
) -> None:
    studio = _configured(notebook_path)
    with build_view_project_sync(
        studio.views["executive"],
        profile="production",
    ):
        pass
    (studio.views["executive"].root / "index.html").write_text(
        "<html><head></head><body><main id='broken'></main></body></html>",
        encoding="utf-8",
    )
    edit_app = _marimo_app(studio.notebook)
    _edit_mode(edit_app)

    with TestClient(create_asgi_app(studio.notebook)) as client:
        dashboard = client.get("/")
        executive = client.get("/executive/")
        views = client.get("/_marimo-studio/views")
    with TestClient(edit_app) as client:
        studio = client.get("/studio/executive/")
        project = client.get("/_marimo-studio/views/executive/project").json()

    assert dashboard.status_code == 200
    assert executive.status_code == 200
    assert project["build"]["phase"] == "stale"
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


@pytest.mark.parametrize(
    ("allowed_origins", "expected_policy"),
    (
        (None, "frame-ancestors 'self'"),
        (
            "http://localhost:55021,https://notebooks.example.com",
            "frame-ancestors 'self' http://localhost:55021 "
            "https://notebooks.example.com",
        ),
    ),
)
def test_invalid_studio_config_keeps_edit_error_documents_framed(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    allowed_origins: str | None,
    expected_policy: str,
) -> None:
    studio = _configured(notebook_path)

    def invalidate(config: MutableMapping[str, object]) -> None:
        del config["default"]

    update_notebook_config(studio.notebook, invalidate)
    if allowed_origins is None:
        monkeypatch.delenv("MARIMO_STUDIO_ALLOWED_EMBED_ORIGINS", raising=False)
    else:
        monkeypatch.setenv("MARIMO_STUDIO_ALLOWED_EMBED_ORIGINS", allowed_origins)
    app = _marimo_app(studio.notebook, programmatic=True)
    _edit_mode(app)

    with TestClient(app) as client:
        document = client.get("/studio/dashboard/")
        structured = client.get(
            "/studio/dashboard/",
            headers={"Accept": "application/json"},
        )
        presentation = client.get("/dashboard/")
        presentation_structured = client.get(
            "/dashboard/",
            headers={"Accept": "application/json"},
        )
        support = client.get("/_marimo-studio/views")
    with TestClient(_marimo_app(studio.notebook, programmatic=True)) as client:
        run_document = client.get("/dashboard/")

    for response in (
        document,
        structured,
        presentation,
        presentation_structured,
    ):
        assert response.status_code == 500
        assert response.headers["content-security-policy"] == expected_policy
    assert support.status_code == 500
    assert "content-security-policy" not in support.headers
    assert run_document.status_code == 500
    assert "content-security-policy" not in run_document.headers


def test_edit_mode_hosts_an_unconfigured_notebook_without_intercepting_run_mode(
    tmp_path: Path,
) -> None:
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
    assert "marimo-studio-host" not in page.text
    assert _studio_host(editor.text)["state"] == "unconfigured"
    assert 'id="marimo-studio-editor"' in editor.text
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
