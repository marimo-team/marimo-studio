from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest
from starlette.testclient import TestClient

import marimo_studio.agent as agent
import marimo_studio.authoring as authoring
from marimo_studio._workspace import load_studio
from marimo_studio.errors import AgentRequestError, ViewInUseError

from ..app_helpers import configured as _configured
from ..app_helpers import edit_mode as _edit_mode
from ..app_helpers import marimo_app as _marimo_app
from ..app_helpers import session_manager as _session_manager
from ._view_mutation_test_support import (
    _capture_scopes,
    _code_mode_client,
    _serve,
    _view_owner,
)


def _rename(
    client: TestClient,
    name: str,
    new_name: str,
    headers: dict[str, str],
):
    catalog_generation, view_generation = _view_owner(client, name)
    return client.post(
        f"/_marimo-studio/views/{name}/rename",
        headers=headers,
        json={
            "catalog_generation": catalog_generation,
            "new_name": new_name,
            "view_generation": view_generation,
        },
    )


def test_view_rename_releases_served_artifacts_and_serves_the_new_url(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    studio = _configured(notebook_path)
    scopes = _capture_scopes(monkeypatch)
    app = _marimo_app(studio.notebook)
    _edit_mode(app)
    headers = {"Marimo-Server-Token": str(_session_manager(app).skew_protection_token)}

    with TestClient(app) as client:
        _serve(client, scopes, "executive")
        served = tuple((studio.view_root / "executive").glob(".artifacts/.pins/*/*"))
        renamed = _rename(client, "executive", "operations", headers)
        new_page = client.get("/operations/")
        old_page = client.get("/executive/")

    assert served
    assert renamed.status_code == 200, renamed.text
    payload = renamed.json()
    assert payload["name"] == "operations"
    assert payload["default_view"] == "dashboard"
    assert [item["name"] for item in payload["views"]] == ["dashboard", "operations"]
    assert payload["generation"] == load_studio(studio.notebook).catalog_generation
    assert new_page.status_code == 202, new_page.text
    assert old_page.status_code == 404
    assert not (studio.view_root / "executive").exists()


@pytest.mark.parametrize(
    ("new_name", "include_owner", "error"),
    [
        ("operations", False, "invalid-view-rename-request"),
        ("Operations", True, "invalid-view-name"),
    ],
    ids=["missing-owner", "invalid-name"],
)
def test_view_rename_rejects_invalid_requests(
    notebook_path: Path,
    new_name: str,
    include_owner: bool,
    error: str,
) -> None:
    studio = _configured(notebook_path)
    app = _marimo_app(studio.notebook)
    _edit_mode(app)
    headers = {"Marimo-Server-Token": str(_session_manager(app).skew_protection_token)}

    with TestClient(app) as client:
        body = {"new_name": new_name}
        if include_owner:
            catalog_generation, view_generation = _view_owner(client, "executive")
            body |= {
                "catalog_generation": catalog_generation,
                "view_generation": view_generation,
            }
        response = client.post(
            "/_marimo-studio/views/executive/rename",
            headers=headers,
            json=body,
        )

    assert response.status_code == 400
    assert response.json()["error"] == error
    assert set(load_studio(studio.notebook).views) == {"dashboard", "executive"}


@pytest.mark.parametrize(
    ("new_name", "held", "error"),
    [
        ("executive", False, "view-exists"),
        ("dashboard", False, "view-exists"),
        ("operations", True, "publication-held"),
    ],
    ids=["current-name", "taken-name", "held-publication"],
)
def test_a_rejected_rename_keeps_the_served_view(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    new_name: str,
    held: bool,
    error: str,
) -> None:
    studio = _configured(notebook_path)
    if held:
        view = authoring.open_workspace(studio.notebook).view("executive")
        asyncio.run(view.hold_publication(owner="multi-file edit"))
    scopes = _capture_scopes(monkeypatch)
    app = _marimo_app(studio.notebook)
    _edit_mode(app)
    headers = {"Marimo-Server-Token": str(_session_manager(app).skew_protection_token)}

    with TestClient(app) as client:
        _serve(client, scopes, "executive")
        before = _view_owner(client, "executive")
        response = _rename(client, "executive", new_name, headers)
        served = tuple((studio.view_root / "executive").glob(".artifacts/.pins/*/*"))
        after = _view_owner(client, "executive")

    assert response.status_code == 409, response.text
    assert response.json()["error"] == error
    assert served
    assert after == before


def test_code_mode_rename_goes_through_the_server_that_serves_the_view(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    studio = _configured(notebook_path)
    scopes = _capture_scopes(monkeypatch)
    app = _marimo_app(studio.notebook)
    _edit_mode(app)

    with _code_mode_client(app, studio.notebook, monkeypatch) as client:
        _serve(client, scopes, "dashboard")
        saved = authoring.open_workspace(studio.notebook).view("dashboard")
        with pytest.raises(ViewInUseError) as in_use:
            asyncio.run(saved.rename("overview"))
        with pytest.raises(AgentRequestError) as taken:
            asyncio.run(agent.current_workspace().view("dashboard").rename("executive"))
        overview = asyncio.run(
            agent.current_workspace().view("dashboard").rename("overview")
        )

    assert in_use.value.processes == (os.getpid(),)
    assert taken.value.code == "view-exists"
    assert overview.name == "overview"
    current = load_studio(studio.notebook)
    assert current.default_view == "overview"
    assert overview.generation == current.view_generations["overview"]
    assert not (studio.view_root / "dashboard").exists()
