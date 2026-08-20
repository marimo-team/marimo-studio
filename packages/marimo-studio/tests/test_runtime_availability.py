from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock
from urllib.parse import parse_qs, urlsplit

from starlette.testclient import TestClient

from marimo_studio import create_asgi_app

from .app_helpers import (
    configured,
    edit_mode,
    marimo_app,
    session_manager,
    set_shell,
    studio_bootstrap,
)


def test_runtime_availability_rejects_a_newer_source_revision(
    notebook_path: Path,
) -> None:
    studio = configured(notebook_path)
    app = marimo_app(studio.notebook)
    edit_mode(app)

    with TestClient(app) as client:
        index_revision = (
            client.get("/_marimo-studio/views/dashboard/source/index.html")
            .headers["etag"]
            .strip('"')
        )
        style_revision = (
            client.get("/_marimo-studio/views/dashboard/source/app.css")
            .headers["etag"]
            .strip('"')
        )
        set_shell(studio, "dashboard", "<p>New source</p>")
        response = client.get(
            "/_marimo-studio/views/dashboard/runtimes",
            params={
                "source_index": index_revision,
                "source_style": style_revision,
            },
        )

    assert response.status_code == 409
    assert response.json()["error"] == "runtime-sync-pending"


def test_run_mode_ignores_a_studio_revision_pin(notebook_path: Path) -> None:
    studio = configured(notebook_path)

    with TestClient(create_asgi_app(studio.notebook)) as client:
        first = client.get("/dashboard/")
        first_revision = first.headers["Marimo-Studio-Revision"]
        set_shell(studio, "dashboard", "<p>Current source</p>")
        current = client.get("/dashboard/")
        historical = client.get(
            "/dashboard/",
            params={
                "marimo_studio_client": "browser-client-1234",
                "marimo_studio_revision": first_revision,
            },
        )

    assert current.headers["Marimo-Studio-Revision"] != first_revision
    assert (
        historical.headers["Marimo-Studio-Revision"]
        == current.headers["Marimo-Studio-Revision"]
    )
    assert "Current source" in historical.text


def test_edit_mode_recovers_an_evicted_revision_pin(notebook_path: Path) -> None:
    studio = configured(notebook_path)
    app = marimo_app(studio.notebook)
    edit_mode(app)
    session_manager(app).get_session_by_file_key = Mock(return_value=object())

    with TestClient(app) as client:
        workspace = client.get("/studio/dashboard/")
        bootstrap = studio_bootstrap(workspace.text)
        pinned = client.get(
            "/dashboard/",
            params={
                "runtime": "server",
                "region": "emea",
                "marimo_studio_client": bootstrap["clientId"],
                "marimo_studio_revision": "missing-revision",
            },
            follow_redirects=False,
        )
        recovered = client.get(pinned.headers["location"])

    assert pinned.status_code == 307
    query = parse_qs(urlsplit(pinned.headers["location"]).query)
    assert query["runtime"] == ["server"]
    assert query["region"] == ["emea"]
    assert query["marimo_studio_client"] == [bootstrap["clientId"]]
    assert "marimo_studio_revision" not in query
    assert recovered.status_code == 200


def test_runtime_config_reports_an_evicted_startup_revision(
    notebook_path: Path,
) -> None:
    studio = configured(notebook_path)

    with TestClient(create_asgi_app(studio.notebook)) as client:
        first_revision = client.get("/dashboard/").headers["Marimo-Studio-Revision"]
        for version in range(9):
            set_shell(studio, "dashboard", f"<p>Revision {version}</p>")
            client.get("/dashboard/")
        stale = client.get(
            "/_marimo-studio/views/dashboard/config",
            params={"runtime": "server", "revision": first_revision},
        )

    assert stale.status_code == 409
    assert stale.json()["error"] == "presentation-revision-unavailable"
