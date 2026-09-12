from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
from starlette.requests import Request
from starlette.responses import Response
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from marimo_studio import create_asgi_app
from marimo_studio._delivery.urls import WORKSPACE_EVENTS_CAPABILITY_QUERY_PARAM
from marimo_studio._server.agent.clients import ClientBinding, StudioClientRegistry
from marimo_studio._server.ports import SessionOwner
from marimo_studio._server.presentation import access as presentation_access
from marimo_studio._server.presentation.session_ids import SessionIdAllocator
from marimo_studio._server.records import ServerContext
from marimo_studio._server.server_instance import server_instance_id

from ..app_helpers import configured as _configured
from ..app_helpers import edit_mode as _edit_mode
from ..app_helpers import marimo_app as _marimo_app
from ..app_helpers import session_manager as _session_manager
from .app_test_support import (
    _editor_mount_value,
    _live_test_session,
    _presentation_fallback_url,
    _presentation_frame_url,
    _view_support_url,
)


def test_presentation_capability_grants_runtime_reads_and_rejects_editor_routes(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    studio = _configured(notebook_path)
    app = _marimo_app(studio.notebook, skew_protection=True)
    _edit_mode(app)
    manager = _session_manager(app)
    session = _live_test_session(
        (),
        initialization_id=str(studio.notebook),
        path=str(studio.notebook),
    )
    manager.get_session_by_file_key = lambda _file_key: session
    claimed: dict[str, object] = {"s_nativ1": session}
    manager.get_session = lambda session_id: claimed.get(str(session_id))
    server_token = str(manager.skew_protection_token)
    events_scope: dict[str, object] = {}
    projected_sessions: list[str | None] = []
    stdin_values: list[str] = []
    session_with_input: Any = session
    session_with_input.put_input = stdin_values.append
    authorize = SessionIdAllocator.authorize
    admit_next_native_post = False

    def admit_runtime(
        allocator: SessionIdAllocator,
        context: ServerContext,
        sessions: Any,
        view_name: str,
        presentation_session_id: str,
        runtime_session_id: str,
        **options: Any,
    ) -> bool:
        nonlocal admit_next_native_post
        authorized = authorize(
            allocator,
            context,
            sessions,
            view_name,
            presentation_session_id,
            runtime_session_id,
            **options,
        )
        if authorized and admit_next_native_post:
            claimed[runtime_session_id] = session
            admit_next_native_post = False
        return authorized

    async def scoped_events(
        _studio: object,
        view_name: str | None = None,
        **options: object,
    ) -> Any:
        events_scope.update(view=view_name, client_id=options.get("client_id"))
        yield b"event: ready\ndata: {}\n\n"

    async def binding_for_session(
        _registry: StudioClientRegistry,
        session_id: str,
    ) -> ClientBinding | None:
        return (
            ClientBinding(
                client_id="studio-client",
                session_id=session_id,
                connected=True,
            )
            if session_id == "s_editor"
            else None
        )

    async def capture_outputs(request: Request, *_args: object, **_kwargs: object):
        projected_sessions.append(request.headers.get("Marimo-Session-Id"))
        return Response(status_code=204)

    monkeypatch.setattr(
        StudioClientRegistry,
        "binding_for_session",
        binding_for_session,
    )
    monkeypatch.setattr(
        "marimo_studio._server.support.change_events",
        scoped_events,
    )
    monkeypatch.setattr(
        "marimo_studio._server.support.outputs_response",
        capture_outputs,
    )
    monkeypatch.setattr(SessionIdAllocator, "authorize", admit_runtime)
    monkeypatch.setattr(presentation_access, "_NATIVE_POST_MAX_BYTES", 16)

    with TestClient(app) as client:
        initial = client.get(
            "/dashboard/",
            params={WORKSPACE_EVENTS_CAPABILITY_QUERY_PARAM: "untrusted"},
            follow_redirects=False,
        )
        assert initial.status_code == 307
        assert WORKSPACE_EVENTS_CAPABILITY_QUERY_PARAM not in parse_qs(
            urlsplit(initial.headers["location"]).query
        )
        shell = client.get(initial.headers["location"])
        frame_url = _presentation_frame_url(shell.text)
        assert WORKSPACE_EVENTS_CAPABILITY_QUERY_PARAM not in parse_qs(
            urlsplit(frame_url).query
        )
        runtime_session_id = parse_qs(urlsplit(frame_url).query)["session_id"][0]
        presentation = client.get(frame_url)
        session_id = _editor_mount_value(presentation.text, "sessionId")
        support_url = _editor_mount_value(presentation.text, "supportUrl")
        runtime_config = client.get(
            _view_support_url({"supportUrl": support_url}, "config"),
            headers={
                "Marimo-Session-Id": runtime_session_id,
                "Marimo-Studio-Preview-Session-Id": session_id,
            },
        )
        payload = runtime_config.json()
        capability = payload["runtime"]["data"]["capabilityToken"]
        capability_root = payload["runtime"]["data"]["url"]
        outputs = client.post(
            _view_support_url(payload, "outputs"),
            headers={"Marimo-Session-Id": session_id},
            json={},
        )
        native_session_outputs = client.post(
            _view_support_url(payload, "outputs"),
            headers={"Marimo-Session-Id": runtime_session_id},
            json={},
        )
        events = client.get(
            f"{capability_root}_marimo-studio/dev/events",
            params={
                "marimo_studio_server": server_instance_id(server_token),
                "marimo_studio_client": "browser-client-1234",
                "marimo_studio_connection": "1",
            },
        )
        source = client.get(
            f"{capability_root}_marimo-studio/views/dashboard/source/index.html"
        )
        cross_view = client.get(
            f"{capability_root}_marimo-studio/views/executive/config"
        )
        create = client.post(
            f"{capability_root}_marimo-studio/views",
            headers={"Marimo-Server-Token": capability},
            json={"name": "forged", "starter": "marimo-studio/vanilla:default"},
        )
        delete = client.delete(f"{capability_root}_marimo-studio/views/executive")
        execute = client.post(
            f"{capability_root}api/kernel/run",
            headers={"Marimo-Server-Token": capability},
            json={},
        )
        editor_session_mutation = client.post(
            f"{capability_root}api/kernel/function_call",
            headers={"Marimo-Session-Id": "s_editor"},
            json={},
        )
        native_session_preflight = client.options(
            f"{capability_root}api/kernel/function_call",
            headers={
                "Access-Control-Request-Headers": "Marimo-Session-Id",
                "Access-Control-Request-Method": "POST",
                "Origin": "null",
            },
        )
        cross_session_config = client.get(
            _view_support_url(payload, "config"),
            headers={"Marimo-Studio-Preview-Session-Id": "s_other1"},
        )
        unlimited_session = client.post(
            f"{capability_root}api/kernel/function_call",
            headers={"Marimo-Session-Id": "s_other2"},
            json={},
        )
        oversized_native_request = client.post(
            f"{capability_root}api/kernel/function_call",
            headers={"Marimo-Session-Id": session_id},
            content=b"x" * 17,
        )
        admit_next_native_post = True
        native_request = client.post(
            f"{capability_root}api/kernel/stdin",
            headers={"Marimo-Session-Id": session_id},
            json={"text": "ok"},
        )

    assert shell.status_code == 200
    assert presentation.status_code == 200
    assert "allow-same-origin" not in shell.text
    assert server_token not in shell.text
    assert server_token not in presentation.text
    assert server_token not in runtime_config.text
    assert capability != server_token
    assert runtime_config.status_code == 200
    assert outputs.status_code == 204
    assert projected_sessions == [runtime_session_id]
    assert native_session_outputs.status_code == 403
    assert native_session_preflight.status_code == 204
    assert oversized_native_request.status_code == 413
    assert oversized_native_request.headers["access-control-allow-origin"] == "null"
    assert oversized_native_request.json()["error"] == "request-body-too-large"
    assert native_request.status_code == 200
    assert native_request.headers["access-control-allow-origin"] == "null"
    assert stdin_values == ["ok"]
    assert events.status_code == 200
    assert events_scope == {"view": "dashboard", "client_id": None}
    assert runtime_config.headers["access-control-allow-origin"] == "null"
    assert "serverToken" not in payload["runtime"]["data"]
    for response in (
        source,
        cross_view,
        create,
        delete,
        execute,
        editor_session_mutation,
        cross_session_config,
        unlimited_session,
    ):
        assert response.status_code == 403
        assert response.json()["error"] == "presentation-capability-forbidden"


def test_stale_native_capability_does_not_begin_admission(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    studio = _configured(notebook_path)
    document = studio.views["dashboard"].root / "index.html"
    admissions: list[str] = []
    authorize = SessionIdAllocator.authorize

    def track_authorize(
        allocator: SessionIdAllocator,
        context: ServerContext,
        sessions: Any,
        view_name: str,
        presentation_session_id: str,
        runtime_session_id: str,
        *,
        native_admission: bool,
        expected_owner: SessionOwner | None = None,
    ) -> bool:
        if native_admission:
            admissions.append(runtime_session_id)
        return authorize(
            allocator,
            context,
            sessions,
            view_name,
            presentation_session_id,
            runtime_session_id,
            native_admission=native_admission,
            expected_owner=expected_owner,
        )

    monkeypatch.setattr(SessionIdAllocator, "authorize", track_authorize)
    with TestClient(create_asgi_app(studio.notebook)) as client:
        stale = client.get("/_marimo-studio/views/dashboard/config").json()
        document.write_text(
            document.read_text(encoding="utf-8").replace(
                "</body>",
                "<p>Current revision</p></body>",
                1,
            ),
            encoding="utf-8",
        )
        current = client.get("/_marimo-studio/views/dashboard/config").json()
        root = urlsplit(stale["runtime"]["data"]["url"])
        websocket_url = (
            f"{root.path.rstrip('/')}/ws?session_id={stale['presentationSessionId']}"
        )
        with (
            pytest.raises(WebSocketDisconnect),
            client.websocket_connect(websocket_url),
        ):
            pass

    assert stale["revision"] != current["revision"]
    assert admissions == []


@pytest.mark.parametrize(
    ("endpoint", "kiosk"),
    (
        pytest.param("ws", None, id="websocket-missing"),
        pytest.param("sse", "false", id="sse-false"),
    ),
)
def test_edit_capability_native_transport_requires_kiosk_mode(
    notebook_path: Path,
    endpoint: str,
    kiosk: str | None,
) -> None:
    studio = _configured(notebook_path)
    app = _marimo_app(studio.notebook)
    _edit_mode(app)

    with TestClient(app) as client:
        config = client.get("/_marimo-studio/views/dashboard/config").json()
        root = urlsplit(config["runtime"]["data"]["url"])
        query = f"session_id={config['presentationSessionId']}"
        if kiosk is not None:
            query += f"&kiosk={kiosk}"
        native_url = f"{root.path.rstrip('/')}/{endpoint}?{query}"
        if endpoint == "ws":
            with (
                pytest.raises(WebSocketDisconnect),
                client.websocket_connect(native_url),
            ):
                pass
        else:
            response = client.get(native_url)
            assert response.status_code == 403


@pytest.mark.parametrize(
    "same_notebook",
    (
        pytest.param(False, id="foreign-notebook"),
        pytest.param(True, id="same-notebook-preclaim"),
    ),
)
def test_capability_rejects_a_preclaimed_runtime(
    notebook_path: Path,
    same_notebook: bool,
) -> None:
    studio = _configured(notebook_path)
    foreign_notebook = notebook_path.with_name("foreign.py")
    foreign_notebook.write_text(
        notebook_path.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    app = _marimo_app(studio.notebook)
    manager = _session_manager(app)

    with TestClient(app) as client:
        wrapper = client.get("/dashboard/")
        document = client.get(_presentation_fallback_url(wrapper.text))
        runtime_session_id = _editor_mount_value(document.text, "runtimeSessionId")
        presentation_session_id = _editor_mount_value(document.text, "sessionId")
        support_url = _view_support_url(
            {"supportUrl": _editor_mount_value(document.text, "supportUrl")},
            "config",
        )
        foreign_session = _live_test_session(
            (),
            initialization_id=str(notebook_path if same_notebook else foreign_notebook),
            path=str(notebook_path if same_notebook else foreign_notebook),
        )
        manager.get_session = lambda session_id: (
            foreign_session if str(session_id) == runtime_session_id else None
        )
        response = client.get(
            support_url,
            headers={
                "Marimo-Session-Id": runtime_session_id,
                "Marimo-Studio-Preview-Session-Id": presentation_session_id,
            },
        )

    assert response.status_code == 403
    assert response.json()["error"] == "presentation-capability-forbidden"


def test_claim_inserted_after_authorize_remains_a_fresh_connector_expectation(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    studio = _configured(notebook_path)
    app = _marimo_app(studio.notebook)
    manager = _session_manager(app)
    claimed: dict[str, object] = {}
    manager.get_session = lambda session_id: claimed.get(str(session_id))
    authorize = SessionIdAllocator.authorize
    cancel = SessionIdAllocator.cancel_admission
    cancelled: list[str] = []

    def inject_claim(
        allocator: SessionIdAllocator,
        context: ServerContext,
        sessions: Any,
        view_name: str,
        presentation_session_id: str,
        runtime_session_id: str,
        **options: Any,
    ) -> bool:
        authorized = authorize(
            allocator,
            context,
            sessions,
            view_name,
            presentation_session_id,
            runtime_session_id,
            **options,
        )
        if authorized and options.get("native_admission"):
            claimed[runtime_session_id] = _live_test_session(
                (),
                initialization_id=str(studio.notebook),
                path=str(studio.notebook),
            )
        return authorized

    def track_cancel(
        allocator: SessionIdAllocator,
        context: ServerContext,
        view_name: str,
        presentation_session_id: str,
        runtime_session_id: str,
    ) -> None:
        cancelled.append(runtime_session_id)
        cancel(
            allocator,
            context,
            view_name,
            presentation_session_id,
            runtime_session_id,
        )

    monkeypatch.setattr(SessionIdAllocator, "authorize", inject_claim)
    monkeypatch.setattr(SessionIdAllocator, "cancel_admission", track_cancel)
    with TestClient(app) as client:
        config = client.get("/_marimo-studio/views/dashboard/config").json()
        runtime_session_id = config["runtime"]["data"]["sessionId"]
        root = urlsplit(config["runtime"]["data"]["url"])
        websocket_url = (
            f"{root.path.rstrip('/')}/ws?session_id={config['presentationSessionId']}"
        )
        with (
            pytest.raises(WebSocketDisconnect),
            client.websocket_connect(websocket_url),
        ):
            pass

    assert runtime_session_id in claimed
    assert cancelled == [runtime_session_id]


@pytest.mark.parametrize("edit", [True, False])
def test_native_widget_resources_retain_edit_session_authority_across_revisions(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    edit: bool,
) -> None:
    studio = _configured(notebook_path)
    app = _marimo_app(studio.notebook)
    if edit:
        _edit_mode(app)
    forwarded: list[object] = []

    async def native(_app: Any, scope: Any, receive: Any, send: Any) -> None:
        forwarded.append(
            await Request(scope, receive).json()
            if scope["method"] == "POST"
            else scope["path"]
        )
        await Response(status_code=204)(scope, receive, send)

    monkeypatch.setattr(presentation_access, "_send_capability_app", native)
    with TestClient(app) as client:
        config = client.get("/_marimo-studio/views/dashboard/config").json()
        document = studio.views["dashboard"].root / "index.html"
        document.write_text(
            document.read_text(encoding="utf-8") + "\n<p>New revision</p>",
            encoding="utf-8",
        )
        current = client.get("/_marimo-studio/views/dashboard/config").json()
        assert config["revision"] != current["revision"]
        headers = {"Marimo-Session-Id": config["presentationSessionId"]}
        asset = client.get(config["runtime"]["data"]["url"] + "@file/tool.js")
        assert asset.status_code == (204 if edit else 403)
        model = {
            "modelId": "tool-model",
            "message": {"method": "custom", "content": {}},
            "buffers": [],
        }
        model_url = config["runtime"]["data"]["url"] + "api/kernel/set_model_value"
        assert client.post(model_url, headers=headers, json=model).status_code == (
            204 if edit else 403
        )
        assert (
            client.post(
                model_url, headers={"Marimo-Session-Id": "s_other1"}, json=model
            ).status_code
            == 403
        )
        control_url = (
            config["runtime"]["data"]["url"] + "api/kernel/set_ui_element_value"
        )
        assert client.post(control_url, headers=headers, json={}).status_code == 403
        function_url = config["runtime"]["data"]["url"] + "api/kernel/function_call"
        assert client.post(function_url, headers=headers, json={}).status_code == 403
        token = config["runtime"]["data"]["capabilityToken"]
        forged = token[:-1] + ("0" if token[-1] != "0" else "1")
        assert (
            client.post(
                model_url.replace(token, forged), headers=headers, json=model
            ).status_code
            == 403
        )
    assert forwarded == (["/@file/tool.js", model] if edit else [])
