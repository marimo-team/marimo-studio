from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from starlette.testclient import TestClient

from marimo_studio._browser_client.transport import (
    StudioServerConnection,
    _raise_response_error,
)
from marimo_studio._server.notebook_scope import NotebookScope

from ..app_helpers import session_manager


def _create_owned_view(
    client: TestClient,
    name: str,
    headers: dict[str, str],
    generation: str | None = None,
):
    owner = generation or cast(
        str, client.get("/_marimo-studio/views").json()["generation"]
    )
    return client.post(
        "/_marimo-studio/views",
        headers=headers,
        json={
            "catalog_generation": owner,
            "name": name,
            "starter": "marimo-studio/vanilla:default",
        },
    )


def _view_owner(client: TestClient, name: str) -> tuple[str, str]:
    inventory = client.get("/_marimo-studio/views").json()
    view = next(item for item in inventory["views"] if item["name"] == name)
    return cast(str, inventory["generation"]), cast(str, view["generation"])


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


def _serve(client: TestClient, scopes: list[NotebookScope], name: str) -> None:
    # The first request creates the notebook scope, and a presentation snapshot
    # pins the view's artifacts the way an open page does.
    _view_owner(client, name)
    scopes[0].presentation.snapshot(name)


@contextmanager
def _code_mode_client(
    app: Any,
    notebook: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[TestClient]:
    connection = StudioServerConnection(
        "http://testserver",
        server_token=str(session_manager(app).skew_protection_token),
        session_id="s_123456",
    )
    monkeypatch.setattr(
        "marimo_studio._composition.create_code_mode_bridge",
        lambda: SimpleNamespace(
            active_notebook=lambda: notebook.resolve(),
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
        yield client
