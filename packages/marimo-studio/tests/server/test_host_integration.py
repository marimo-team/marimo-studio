from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from urllib.parse import parse_qs, urlsplit

import pytest
from starlette.testclient import TestClient
from starlette.types import Message, Receive, Scope, Send

from marimo_studio._entrypoints import EDIT_ROOT_ENV, route_policy_from_environment
from marimo_studio._server.editor_bridge import delegate_editor_request
from marimo_studio._server.notebook_scope import NotebookScopeRegistry
from marimo_studio._server.route_policy import StudioRoutePolicy
from marimo_studio._server.security import Origin, SecurityPolicy
from marimo_studio._server.studio.session_handoff import (
    host_session_handoff_capability_matches,
)
from marimo_studio._workspace import load_studio
from marimo_studio._workspace.generation import unconfigured_catalog_generation
from marimo_studio.errors import WorkspaceGenerationConflictError

from ..app_helpers import configured as _configured
from ..app_helpers import edit_mode as _edit_mode
from ..app_helpers import marimo_app as _marimo_app
from .app_test_support import _studio_bootstrap, _studio_host

_EXPLICIT_HOST = StudioRoutePolicy(edit_root="marimo")


def test_route_policy_environment_selects_the_edit_root() -> None:
    assert route_policy_from_environment({}).edit_root == "studio"
    assert route_policy_from_environment({EDIT_ROOT_ENV: "marimo"}) == _EXPLICIT_HOST
    with pytest.raises(RuntimeError, match=EDIT_ROOT_ENV):
        route_policy_from_environment({EDIT_ROOT_ENV: "host-name"})


def test_explicit_host_delegates_edit_root_before_allocating_a_notebook_scope(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _marimo_app(
        notebook_path,
        programmatic=True,
        route_policy=_EXPLICIT_HOST,
    )
    _edit_mode(app)

    def reject_scope(_registry: NotebookScopeRegistry, _notebook: Path) -> Any:
        raise AssertionError("Native edit root allocated a Studio notebook scope")

    monkeypatch.setattr(NotebookScopeRegistry, "get", reject_scope)
    with TestClient(app) as client:
        preflight = client.get("/")
        root = client.get("/?session_id=s_123456")

    assert preflight.status_code == 200
    assert root.status_code == 200


def test_explicit_host_enters_a_ready_workspace_through_studio(
    notebook_path: Path,
) -> None:
    studio = _configured(notebook_path)
    app = _marimo_app(
        studio.notebook,
        programmatic=True,
        route_policy=_EXPLICIT_HOST,
    )
    _edit_mode(app)

    with TestClient(app) as client:
        workspace = client.get("/studio/?session_id=s_studio")

    assert workspace.status_code == 200
    assert _studio_bootstrap(workspace.text)["selectedView"] == studio.default_view


def test_explicit_host_handoff_uses_the_embedding_security_policy(
    notebook_path: Path,
) -> None:
    app = _marimo_app(
        notebook_path,
        programmatic=True,
        route_policy=_EXPLICIT_HOST,
        security_policy=SecurityPolicy((Origin("https://host.example"),)),
    )
    _edit_mode(app)

    with TestClient(app) as client:
        handoff = client.get("/studio/")
        native = client.get("/?session_id=s_123456")

    assert handoff.status_code == 200
    for response in (handoff, native):
        assert response.headers["content-security-policy"] == (
            "frame-ancestors 'self' https://host.example"
        )


def test_studio_route_initializes_an_unconfigured_notebook(
    notebook_path: Path,
) -> None:
    app = _marimo_app(
        notebook_path,
        programmatic=True,
        route_policy=_EXPLICIT_HOST,
    )
    _edit_mode(app)

    with TestClient(app) as client:
        page = client.get("/studio/?session_id=s_studio")
        host = _studio_host(page.text)
        inventory = client.get("/_marimo-studio/views").json()
        created = client.post(
            "/_marimo-studio/views",
            headers={"Marimo-Server-Token": host["serverToken"]},
            json={
                "catalog_generation": inventory["generation"],
                "name": inventory["default_view"],
                "starter": inventory["default_starter"],
            },
        )
        workspace = client.get("/studio/dashboard/?session_id=s_ready1")

    assert page.status_code == 200
    assert host["state"] == "needs-view"
    assert inventory["views"] == []
    assert created.status_code == 201
    assert created.json() == {"schema": 1, "name": "dashboard"}
    assert _studio_bootstrap(workspace.text)["selectedView"] == "dashboard"
    assert tuple(load_studio(notebook_path).views) == ("dashboard",)


def test_unconfigured_creation_rechecks_state_under_the_catalog_lock(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from marimo_studio._views import create as create_module
    from marimo_studio._views.api import create_view, prepare_view

    prepare_view(notebook_path, "dashboard")
    monkeypatch.setattr(create_module, "_studio_snapshot", lambda _notebook: None)

    with pytest.raises(WorkspaceGenerationConflictError):
        create_view(
            notebook_path,
            "report",
            expected_catalog_generation=unconfigured_catalog_generation(notebook_path),
        )


def test_explicit_host_preserves_run_root_and_studio_authentication(
    notebook_path: Path,
) -> None:
    studio = _configured(notebook_path)
    run_app = _marimo_app(
        studio.notebook,
        programmatic=True,
        route_policy=_EXPLICIT_HOST,
    )
    edit_app = _marimo_app(
        studio.notebook,
        token="test-token",
        programmatic=True,
        route_policy=_EXPLICIT_HOST,
    )
    _edit_mode(edit_app)

    with TestClient(run_app) as client:
        presentation = client.get("/")
    with TestClient(edit_app) as client:
        native_login = client.get("/", follow_redirects=False)
        studio_login = client.get("/studio/", follow_redirects=False)

    assert presentation.status_code == 200
    assert native_login.status_code == 303
    assert native_login.headers["location"].startswith("/auth/login")
    assert studio_login.status_code == 303
    login_query = parse_qs(urlsplit(studio_login.headers["location"]).query)
    assert login_query["next"] == ["/studio/"]


@pytest.mark.parametrize("renamed_before_save", [False, True])
def test_native_save_hands_off_a_newly_named_notebook(
    notebook_path: Path,
    renamed_before_save: bool,
) -> None:
    reloads: list[str] = []
    handoffs: list[str] = []
    named = renamed_before_save

    async def downstream(scope: Scope, receive: Receive, send: Send) -> None:
        nonlocal named
        del scope, receive
        named = True
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    async def receive() -> Message:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(_message: Message) -> None:
        return None

    location_value = SimpleNamespace(notebook=notebook_path)
    context_value = SimpleNamespace(
        base_url="/api/kernel",
        file_key=str(notebook_path),
        mode="edit",
        notebook=notebook_path,
        server_token="server-token",
    )

    async def location(_request: object) -> object:
        return location_value

    async def session_location(_request: object, _session_id: str) -> object:
        return location_value if named else None

    handled = asyncio.run(
        delegate_editor_request(
            downstream,
            NotebookScopeRegistry(),
            cast(
                Scope,
                {
                    "type": "http",
                    "method": "POST",
                    "scheme": "http",
                    "path": "/api/kernel/save",
                    "raw_path": b"/api/kernel/save",
                    "root_path": "",
                    "query_string": b"",
                    "headers": [(b"marimo-session-id", b"s_123456")],
                    "server": ("testserver", 80),
                    "client": ("testclient", 1),
                },
            ),
            receive,
            send,
            server=cast(
                Any,
                SimpleNamespace(
                    context=lambda _location: context_value,
                    base_url=lambda _scope: "",
                    location=location,
                    session_location=session_location,
                ),
            ),
            sessions=cast(
                Any,
                SimpleNamespace(
                    request_studio_reload=lambda _context, session, **kwargs: (
                        reloads.append(session),
                        handoffs.append(kwargs["host_handoff"]),
                    )
                ),
            ),
            attachment=cast(Any, SimpleNamespace()),
            persistence=cast(Any, SimpleNamespace()),
            code_mode=cast(Any, SimpleNamespace()),
            editor_runtime=cast(Any, SimpleNamespace()),
            document_transactions=cast(Any, SimpleNamespace()),
            relative="/api/kernel/save",
            mode="edit",
        )
    )

    assert handled is True
    assert reloads == ["s_123456"]
    assert host_session_handoff_capability_matches(
        handoffs[0],
        cast(Any, SimpleNamespace(**{**context_value.__dict__, "base_url": ""})),
        "s_123456",
        (),
    )
