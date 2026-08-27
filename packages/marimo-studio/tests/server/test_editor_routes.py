from __future__ import annotations

import re
from pathlib import Path
from typing import Any
from unittest.mock import Mock
from urllib.parse import parse_qs, quote, urlencode, urlsplit

import pytest
from starlette.applications import Starlette
from starlette.routing import Mount
from starlette.testclient import TestClient

from marimo_studio._delivery.urls import (
    EDITOR_BINDING_CAPABILITY_QUERY_PARAM,
    SERVER_INSTANCE_QUERY_PARAM,
)

from ..app_helpers import configured as _configured
from ..app_helpers import edit_mode as _edit_mode
from ..app_helpers import marimo_app as _marimo_app
from ..app_helpers import session_manager as _session_manager
from .app_test_support import (
    _artifact_base,
    _assert_server_runtime,
    _presentation_fallback_url,
    _studio_bootstrap,
)


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
        child = client.get(_presentation_fallback_url(page.text))

    assert page.status_code == 200
    assert named.status_code == 200
    assert child.status_code == 200
    assert re.fullmatch(
        r"/parent/base/_marimo-studio/presentation/[^/]+/dashboard/"
        r"_marimo-studio/artifacts/[0-9a-f]{64}/",
        _artifact_base(child.text),
    )
    assert "/parent/base/_marimo-studio/presentation/" in page.text
    assert "/_marimo-studio/assets/runtime.js" in child.text
    assert config["rootUrl"] == "/parent/base/"
    _assert_server_runtime(config["runtime"]["data"], "/parent/base/")
    support_url = urlsplit(config["supportUrl"])
    assert support_url.path.endswith("/_marimo-studio/views/dashboard")
    assert parse_qs(support_url.query)[SERVER_INSTANCE_QUERY_PARAM] == [
        config["runtime"]["data"]["serverInstance"]
    ]
    assert studio_asset.status_code == 200
    assert relative_cell.status_code == 404
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
    app = _marimo_app(studio.notebook, programmatic=True)
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
        landing_bootstrap = _studio_bootstrap(landing_workspace.text)
        editor = client.get(landing_bootstrap["urls"]["editor"])
        forged_editor = client.get(expected_editor)

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
    actual_editor = urlsplit(landing_bootstrap["urls"]["editor"])
    expected_parts = urlsplit(landing_editor)
    actual_query = parse_qs(actual_editor.query, keep_blank_values=True)
    expected_query = parse_qs(expected_parts.query, keep_blank_values=True)
    assert actual_editor.path == expected_parts.path
    assert actual_query["region"] == expected_query["region"]
    assert actual_query["empty"] == [""]
    assert actual_query["file"] == [str(studio.notebook)]
    assert actual_query["marimo_studio_client"] == [landing_bootstrap["clientId"]]
    assert re.fullmatch(r"s_[a-z0-9]{6}", actual_query["session_id"][0])
    assert re.fullmatch(
        r"[0-9a-f]{64}",
        actual_query[EDITOR_BINDING_CAPABILITY_QUERY_PARAM][0],
    )
    assert head.status_code == 307
    assert head.headers["location"] == "/studio/dashboard/"
    assert post.status_code == 405
    assert editor.status_code == 200
    assert forged_editor.status_code == 403
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
    workspace_sessions = {
        parse_qs(urlsplit(_studio_bootstrap(response.text)["urls"]["editor"]).query)[
            "session_id"
        ][0]
        for response in (landing_workspace, default_workspace, workspace)
    }
    assert len(workspace_sessions) == 3


def test_direct_native_editor_enables_cell_alias_sync(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    studio = _configured(notebook_path)
    app = _marimo_app(studio.notebook, programmatic=True)
    _edit_mode(app)
    locations: list[Any] = []
    monkeypatch.setattr(
        "marimo_studio._compat.server.notebook_save.PrivateNotebookSaveTransform.enable",
        lambda _persistence, location: locations.append(location),
    )
    forged_editor = "/_marimo-studio/editor/?" + urlencode(
        {"file": str(studio.notebook)}
    )

    with TestClient(app) as client:
        workspace = client.get("/studio/")
        response = client.get(_studio_bootstrap(workspace.text)["urls"]["editor"])
        forged = client.get(forged_editor)

    assert response.status_code == 200
    assert forged.status_code == 403
    assert {location.notebook for location in locations} == {studio.notebook}


def test_native_editor_health_keeps_marimo_session_routing(notebook_path: Path) -> None:
    studio = _configured(notebook_path)
    app = _marimo_app(studio.notebook, programmatic=True)
    _edit_mode(app)

    with TestClient(app) as client:
        response = client.get(
            "/_marimo-studio/editor/health",
            params={"file": str(studio.notebook), "session_id": "s_123456"},
        )

    assert response.status_code == 200


def test_editor_reload_restores_its_server_assigned_session(
    notebook_path: Path,
) -> None:
    studio = _configured(notebook_path)
    app = _marimo_app(studio.notebook, programmatic=True)
    _edit_mode(app)

    with TestClient(app) as client:
        workspace = client.get("/studio/")
        editor_url = _studio_bootstrap(workspace.text)["urls"]["editor"]
        opened = client.get(editor_url)
        parts = urlsplit(editor_url)
        query = parse_qs(parts.query)
        session_id = query.pop("session_id")[0]
        reload_query = urlencode({key: values[0] for key, values in query.items()})
        reload_url = f"{parts.path}?{reload_query}"
        restored = client.get(reload_url, follow_redirects=False)
        reloaded = client.get(restored.headers["location"])

    restored_query = parse_qs(urlsplit(restored.headers["location"]).query)
    assert opened.status_code == 200
    assert restored.status_code == 307
    assert restored.headers["cache-control"] == "no-store"
    assert restored_query["session_id"] == [session_id]
    assert reloaded.status_code == 200
