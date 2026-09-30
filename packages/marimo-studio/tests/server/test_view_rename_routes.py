from __future__ import annotations

import asyncio
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from starlette.testclient import TestClient

import marimo_studio.agent as agent
import marimo_studio.authoring as authoring
from marimo_studio._browser_client.transport import (
    StudioServerConnection,
    _raise_response_error,
)
from marimo_studio._server.notebook_scope import NotebookScope
from marimo_studio._workspace import load_studio
from marimo_studio.errors import AgentRequestError, ViewInUseError

from ..app_helpers import configured as _configured
from ..app_helpers import edit_mode as _edit_mode
from ..app_helpers import marimo_app as _marimo_app
from ..app_helpers import session_manager as _session_manager
from ._view_mutation_test_support import _view_owner


def _capture_scopes(monkeypatch: pytest.MonkeyPatch) -> list[NotebookScope]:
    scopes: list[NotebookScope] = []
    create_scope = NotebookScope.create

    def capture_scope(
        path: Path,
        watcher: Any = None,
        session_ids: Any = None,
    ) -> NotebookScope:
        scope = create_scope(path, watcher, session_ids)
        scopes.append(scope)
        return scope

    monkeypatch.setattr(NotebookScope, "create", staticmethod(capture_scope))
    return scopes


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


def test_view_rename_releases_served_artifacts_and_reports_the_catalog(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    studio = _configured(notebook_path)
    scopes = _capture_scopes(monkeypatch)
    app = _marimo_app(studio.notebook)
    _edit_mode(app)
    headers = {"Marimo-Server-Token": str(_session_manager(app).skew_protection_token)}

    with TestClient(app) as client:
        _view_owner(client, "executive")
        scopes[0].presentation.snapshot("executive")
        served = tuple((studio.view_root / "executive").glob(".artifacts/.pins/*/*"))
        renamed = _rename(client, "executive", "operations", headers)

    assert served
    assert renamed.status_code == 200, renamed.text
    payload = renamed.json()
    assert payload["name"] == "operations"
    assert payload["default_view"] == "dashboard"
    assert [item["name"] for item in payload["views"]] == ["dashboard", "operations"]
    assert payload["generation"] == load_studio(studio.notebook).catalog_generation
    assert (studio.view_root / "operations" / "view.toml").is_file()
    assert not (studio.view_root / "executive").exists()


@pytest.mark.parametrize(
    ("body", "status", "error"),
    [
        ({"new_name": "operations"}, 400, "invalid-view-rename-request"),
        (None, 400, "invalid-view-name"),
    ],
)
def test_view_rename_rejects_invalid_requests(
    notebook_path: Path,
    body: dict[str, str] | None,
    status: int,
    error: str,
) -> None:
    studio = _configured(notebook_path)
    app = _marimo_app(studio.notebook)
    _edit_mode(app)
    headers = {"Marimo-Server-Token": str(_session_manager(app).skew_protection_token)}

    with TestClient(app) as client:
        if body is None:
            response = _rename(client, "executive", "Operations", headers)
        else:
            response = client.post(
                "/_marimo-studio/views/executive/rename",
                headers=headers,
                json=body,
            )

    assert response.status_code == status
    assert response.json()["error"] == error
    assert set(load_studio(studio.notebook).views) == {"dashboard", "executive"}


def test_code_mode_rename_goes_through_the_server_that_serves_the_view(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    studio = _configured(notebook_path)
    scopes = _capture_scopes(monkeypatch)
    app = _marimo_app(studio.notebook)
    _edit_mode(app)
    connection = StudioServerConnection(
        "http://testserver",
        server_token=str(_session_manager(app).skew_protection_token),
        session_id="s_123456",
    )
    monkeypatch.setattr(
        "marimo_studio._composition.create_code_mode_bridge",
        lambda: SimpleNamespace(
            active_notebook=lambda: studio.notebook.resolve(),
            connection=lambda: connection,
        ),
    )

    with TestClient(app) as client:
        # Code mode reaches its server over HTTP. Route those requests into the
        # in-process app so this server's retained pins are the ones at stake.
        async def request_json(
            actual: StudioServerConnection,
            path: str,
            *,
            method: str = "GET",
            body: dict[str, object] | None = None,
            **_options: object,
        ) -> dict[str, Any]:
            response = client.request(
                method,
                path,
                headers={"Marimo-Server-Token": actual.server_token},
                json=body,
            )
            if response.is_error:
                _raise_response_error(response.status_code, response.content)
            return response.json()

        monkeypatch.setattr(
            "marimo_studio._browser_client.client.request_json",
            request_json,
        )
        _view_owner(client, "dashboard")
        scopes[0].presentation.snapshot("dashboard")
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


@pytest.mark.parametrize(
    ("new_name", "held", "error"),
    [
        ("executive", False, None),
        ("dashboard", False, "view-exists"),
        ("operations", True, "publication-held"),
    ],
    ids=["same-name", "taken-name", "held-publication"],
)
def test_a_rename_that_cannot_move_keeps_the_served_view(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    new_name: str,
    held: bool,
    error: str | None,
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
        before = _view_owner(client, "executive")
        scopes[0].presentation.snapshot("executive")
        response = _rename(client, "executive", new_name, headers)
        served = tuple((studio.view_root / "executive").glob(".artifacts/.pins/*/*"))
        after = _view_owner(client, "executive")

    if error is None:
        assert response.status_code == 200, response.text
    else:
        assert response.status_code == 409, response.text
        assert response.json()["error"] == error
    assert served
    assert after == before


def test_a_renamed_view_serves_at_its_new_url(notebook_path: Path) -> None:
    studio = _configured(notebook_path)
    app = _marimo_app(studio.notebook)
    _edit_mode(app)
    headers = {"Marimo-Server-Token": str(_session_manager(app).skew_protection_token)}

    with TestClient(app) as client:
        renamed = _rename(client, "executive", "operations", headers)
        new_page = client.get("/operations/")
        old_page = client.get("/executive/")

    assert renamed.status_code == 200, renamed.text
    assert new_page.status_code == 202, new_page.text
    assert old_page.status_code == 404
