from __future__ import annotations

from collections.abc import MutableMapping
from pathlib import Path
from unittest.mock import Mock
from urllib.parse import parse_qs, urlsplit

import pytest
from starlette.testclient import TestClient

from marimo_studio import create_asgi_app
from marimo_studio._server.agent.clients import StudioClientRegistry
from marimo_studio._server.presentation.service import NotebookPresentation
from marimo_studio._workspace.metadata import update_notebook_config
from marimo_studio.errors._internal import RuntimeStartupError
from marimo_studio.view_providers import BuildProfile

from ..app_helpers import configured as _configured
from ..app_helpers import edit_mode as _edit_mode
from ..app_helpers import marimo_app as _marimo_app
from ..app_helpers import session_manager as _session_manager
from .app_test_support import (
    _editor_mount_value,
    _presentation_frame_url,
    _studio_bootstrap,
    _view_support_url,
)


def test_edit_mode_offers_the_configured_preview_runtimes(notebook_path: Path) -> None:
    studio = _configured(notebook_path)
    server_app = _marimo_app(studio.notebook)
    _edit_mode(server_app)

    with TestClient(server_app) as client:
        unavailable = client.get("/_marimo-studio/views/dashboard/config?runtime=wasm")
        server_workspace = client.get("/studio/dashboard/")

    assert unavailable.status_code == 400
    assert _studio_bootstrap(server_workspace.text)["runtimes"] == [
        {"id": "server", "label": "Server"},
    ]

    def enable_wasm(config: MutableMapping[str, object]) -> None:
        config["runtimes"] = ["server", "wasm"]

    update_notebook_config(studio.notebook, enable_wasm)
    wasm_app = _marimo_app(studio.notebook)
    _edit_mode(wasm_app)
    with TestClient(wasm_app) as client:
        config = client.get(
            "/_marimo-studio/views/dashboard/config?runtime=wasm"
        ).json()
        workspace = client.get("/studio/dashboard/")

    assert config["runtime"]["id"] == "wasm"
    bootstrap = _studio_bootstrap(workspace.text)
    assert bootstrap["schema"] == 1
    assert bootstrap["selectedView"] == "dashboard"
    assert bootstrap["views"] == ["dashboard", "executive"]
    assert bootstrap["runtimes"] == [
        {"id": "server", "label": "Server"},
        {"id": "wasm", "label": "WebAssembly"},
    ]
    assert bootstrap["urls"]["query"] == "/_marimo-studio/query"


def test_studio_runtime_config_binds_without_exposing_its_editor_session(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    studio = _configured(notebook_path)
    app = _marimo_app(studio.notebook)
    _edit_mode(app)
    captured: dict[str, object] = {}

    async def session_for_client(
        _clients: StudioClientRegistry,
        client_id: str,
    ) -> str | None:
        captured["client_id"] = client_id
        return "s_123456"

    def runtime_config(
        _snapshot: object,
        _context: object,
        _runtimes: object,
        runtime_id: str | None,
        session_id: str | None,
        binding_id: str | None,
        presentation_session_id: str | None,
        runtime_session_id: str | None,
    ) -> dict[str, object]:
        captured["runtime_id"] = runtime_id
        captured["session_id"] = session_id
        captured["binding_id"] = binding_id
        captured["presentation_session_id"] = presentation_session_id
        captured["runtime_session_id"] = runtime_session_id
        return {"runtime": {"id": "server"}}

    def attach_session(
        _attachment: object,
        _context: object,
        consumer_id: str,
        session_id: str,
    ) -> bool:
        captured["consumer_id"] = consumer_id
        captured["attached_session_id"] = session_id
        return True

    monkeypatch.setattr(
        StudioClientRegistry,
        "session_for_client",
        session_for_client,
    )
    monkeypatch.setattr(
        "marimo_studio._server.runtime.routes.build_runtime_config",
        runtime_config,
    )
    monkeypatch.setattr(
        "marimo_studio._compat.server.session_state.PrivateSessionState.exists",
        lambda _sessions, _context, session_id: session_id == "s_123456",
    )
    monkeypatch.setattr(
        "marimo_studio._compat.server.session_state.PrivateSessionState.has_notebook_session",
        lambda _sessions, _context: True,
    )
    monkeypatch.setattr(
        "marimo_studio._compat.server.session_state.PrivateSessionState.ensure_started",
        lambda _sessions, _context, _session_id: True,
    )
    monkeypatch.setattr(
        "marimo_studio._compat.server.existing_session.PrivateExistingSessionAttachment.attach",
        attach_session,
    )

    with TestClient(app) as client:
        document = client.get(
            "/dashboard/",
            params={"marimo_studio_client": "browser-client-1234"},
        )
        frame_url = _presentation_frame_url(document.text)
        invalid_frame = client.get(f"{frame_url}&marimo_studio_lifecycle=0")
        presentation = client.get(f"{frame_url}&marimo_studio_lifecycle=7")
        presentation_session_id = _editor_mount_value(
            presentation.text,
            "sessionId",
        )
        runtime_session_id = parse_qs(urlsplit(str(presentation.url)).query)[
            "session_id"
        ][0]
        assert _editor_mount_value(presentation.text, "clientId") == (
            "browser-client-1234"
        )
        assert _editor_mount_value(presentation.text, "lifecycleId") == 7
        assert _editor_mount_value(presentation.text, "runtimeSessionId") == (
            runtime_session_id
        )
        assert _editor_mount_value(presentation.text, "replay") is False
        assert "clientId" not in invalid_frame.text
        assert "lifecycleId" not in invalid_frame.text
        response = client.get(
            _view_support_url(
                {"supportUrl": _editor_mount_value(presentation.text, "supportUrl")},
                "config",
            ),
            params={
                "runtime": "server",
                "marimo_studio_client": "browser-client-1234",
            },
            headers={
                "Marimo-Session-Id": runtime_session_id,
                "Marimo-Studio-Preview-Session-Id": presentation_session_id,
            },
        )
        invalid = client.get(
            "/_marimo-studio/views/dashboard/config",
            params={"marimo_studio_client": "browser-client-1234"},
        )

    assert response.status_code == 200
    assert "editorSessionId" not in response.json()
    assert captured == {
        "client_id": "browser-client-1234",
        "runtime_id": "server",
        "session_id": "s_123456",
        "binding_id": "s_123456",
        "presentation_session_id": presentation_session_id,
        "runtime_session_id": runtime_session_id,
        "consumer_id": runtime_session_id,
        "attached_session_id": "s_123456",
    }
    assert invalid.status_code == 400
    assert invalid.json()["error"] == "invalid-studio-session"


def test_studio_runtime_config_waits_for_automatic_startup(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    studio = _configured(notebook_path)
    app = _marimo_app(studio.notebook)
    _edit_mode(app)

    async def session_for_client(
        _clients: StudioClientRegistry,
        _client_id: str,
    ) -> str:
        return "s_123456"

    monkeypatch.setattr(
        StudioClientRegistry,
        "session_for_client",
        session_for_client,
    )
    monkeypatch.setattr(
        "marimo_studio._compat.server.session_state.PrivateSessionState.exists",
        lambda _sessions, _context, session_id: session_id == "s_123456",
    )
    monkeypatch.setattr(
        "marimo_studio._compat.server.session_state.PrivateSessionState.ensure_started",
        lambda _sessions, _context, _session_id: False,
    )

    with TestClient(app) as client:
        response = client.get(
            "/_marimo-studio/views/dashboard/config",
            params={"marimo_studio_client": "browser-client-1234"},
            headers={"Marimo-Studio-Preview-Session-Id": "s_view01"},
        )

    assert response.status_code == 409
    assert response.json() == {
        "error": "runtime-startup-pending",
        "message": "Studio is waiting for notebook startup.",
        "transient": True,
    }


def test_studio_preview_keeps_its_waiting_document_until_startup_completes(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    studio = _configured(notebook_path)
    app = _marimo_app(studio.notebook)
    _edit_mode(app)
    ready = False

    async def session_for_client(
        _clients: StudioClientRegistry,
        _client_id: str,
    ) -> str:
        return "s_123456"

    monkeypatch.setattr(
        StudioClientRegistry,
        "session_for_client",
        session_for_client,
    )
    monkeypatch.setattr(
        "marimo_studio._compat.server.session_state.PrivateSessionState.exists",
        lambda _sessions, _context, session_id: session_id == "s_123456",
    )
    monkeypatch.setattr(
        "marimo_studio._compat.server.session_state.PrivateSessionState.ensure_started",
        lambda _sessions, _context, _session_id: ready,
    )

    with TestClient(app) as client:
        _session_manager(app).get_session_by_file_key = Mock(return_value=object())
        waiting = client.get(
            "/executive/",
            params={"marimo_studio_client": "browser-client-1234"},
        )
        waiting_head = client.head(
            "/executive/",
            params={"marimo_studio_client": "browser-client-1234"},
        )
        ready = True
        document = client.get(
            "/executive/",
            params={"marimo_studio_client": "browser-client-1234"},
        )
        document_head = client.head(
            "/executive/",
            params={"marimo_studio_client": "browser-client-1234"},
        )

    assert waiting.status_code == 202
    assert "Starting notebook" in waiting.text
    assert "/_marimo-studio/presentation/" in waiting.text
    assert "/executive/" in waiting.text
    assert waiting_head.status_code == 202
    assert waiting_head.content == b""
    assert waiting_head.headers["content-length"] == "0"
    assert document.status_code == 200
    assert document.headers["Marimo-Studio-Revision"]
    assert document_head.status_code == 200
    assert document_head.content == b""
    assert document_head.headers["content-length"] == "0"
    assert document_head.headers["Marimo-Studio-Revision"]


def test_studio_runtime_config_reports_terminal_startup_failure(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    studio = _configured(notebook_path)
    app = _marimo_app(studio.notebook)
    _edit_mode(app)

    async def session_for_client(
        _clients: StudioClientRegistry,
        _client_id: str,
    ) -> str:
        return "s_123456"

    def fail_startup(*_args: object) -> bool:
        raise RuntimeStartupError("The kernel stopped during startup.")

    monkeypatch.setattr(
        StudioClientRegistry,
        "session_for_client",
        session_for_client,
    )
    monkeypatch.setattr(
        "marimo_studio._compat.server.session_state.PrivateSessionState.exists",
        lambda _sessions, _context, session_id: session_id == "s_123456",
    )
    monkeypatch.setattr(
        "marimo_studio._compat.server.session_state.PrivateSessionState.ensure_started",
        fail_startup,
    )

    with TestClient(app) as client:
        response = client.get(
            "/_marimo-studio/views/dashboard/config",
            params={"marimo_studio_client": "browser-client-1234"},
            headers={"Marimo-Studio-Preview-Session-Id": "s_view01"},
        )

    assert response.status_code == 500
    assert response.json() == {
        "error": "runtime-startup-failed",
        "message": "The kernel stopped during startup.",
    }


def test_studio_runtime_config_resolves_session_after_snapshot(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    studio = _configured(notebook_path)
    app = _marimo_app(studio.notebook)
    _edit_mode(app)
    active = {"session_id": "s_123456"}
    sessions = {"s_123456": object(), "s_654321": object()}
    captured: dict[str, object] = {}

    async def snapshot_async(
        _presentation: NotebookPresentation,
        _view_name: str,
        *,
        profile: BuildProfile = "development",
    ) -> object:
        assert profile == "development"
        active["session_id"] = "s_654321"
        return object()

    async def session_for_client(
        _clients: StudioClientRegistry,
        _client_id: str,
    ) -> str:
        return active["session_id"]

    def runtime_config(
        _snapshot: object,
        _context: object,
        _runtimes: object,
        _runtime_id: str | None,
        session_id: str | None,
        binding_id: str | None,
        presentation_session_id: str | None,
        runtime_session_id: str | None,
    ) -> dict[str, object]:
        captured["session_id"] = session_id
        captured["binding_id"] = binding_id
        captured["presentation_session_id"] = presentation_session_id
        captured["runtime_session_id"] = runtime_session_id
        return {"runtime": {"id": "server"}}

    def attach_session(
        _attachment: object,
        _context: object,
        consumer_id: str,
        session_id: str,
    ) -> bool:
        captured["consumer_id"] = consumer_id
        captured["editor_session"] = sessions[session_id]
        return True

    monkeypatch.setattr(NotebookPresentation, "snapshot_async", snapshot_async)
    monkeypatch.setattr(
        StudioClientRegistry,
        "session_for_client",
        session_for_client,
    )
    monkeypatch.setattr(
        "marimo_studio._server.runtime.routes.build_runtime_config",
        runtime_config,
    )
    monkeypatch.setattr(
        "marimo_studio._compat.server.session_state.PrivateSessionState.exists",
        lambda _sessions, _context, session_id: session_id in sessions,
    )
    monkeypatch.setattr(
        "marimo_studio._compat.server.session_state.PrivateSessionState.ensure_started",
        lambda _sessions, _context, _session_id: True,
    )
    monkeypatch.setattr(
        "marimo_studio._compat.server.existing_session.PrivateExistingSessionAttachment.attach",
        attach_session,
    )

    with TestClient(app) as client:
        response = client.get(
            "/_marimo-studio/views/dashboard/config",
            params={
                "runtime": "server",
                "marimo_studio_client": "browser-client-1234",
            },
            headers={
                "Marimo-Session-Id": "s_nativ1",
                "Marimo-Studio-Preview-Session-Id": "s_view01",
            },
        )

    assert response.status_code == 200
    assert "editorSessionId" not in response.json()
    runtime_session_id = captured.pop("runtime_session_id")
    consumer_id = captured.pop("consumer_id")
    assert runtime_session_id == consumer_id
    assert runtime_session_id not in {
        "s_nativ1",
        "s_view01",
        *sessions,
    }
    assert captured == {
        "session_id": "s_654321",
        "binding_id": "s_654321",
        "presentation_session_id": "s_view01",
        "editor_session": sessions["s_654321"],
    }


def test_wasm_runtime_keeps_code_stable_across_mount_declaration_changes(
    notebook_path: Path,
) -> None:
    studio = _configured(notebook_path)

    def enable_wasm(config: MutableMapping[str, object]) -> None:
        config["runtime"] = "wasm"
        config["runtimes"] = ["server", "wasm"]

    update_notebook_config(studio.notebook, enable_wasm)
    template = studio.views["dashboard"].root / "index.html"
    with TestClient(create_asgi_app(studio.notebook)) as client:
        first = client.get("/_marimo-studio/views/dashboard/config").json()
        template.write_text(
            template.read_text(encoding="utf-8").replace(
                '<marimo-output value="doubled"',
                '<marimo-output value="doubled.real"',
                1,
            ),
            encoding="utf-8",
        )
        second = client.get("/_marimo-studio/views/dashboard/config").json()
        studio.notebook.write_text(
            studio.notebook.read_text(encoding="utf-8").replace(
                "doubled = x * 2",
                "doubled = x * 3",
                1,
            ),
            encoding="utf-8",
        )
        third = client.get("/_marimo-studio/views/dashboard/config").json()

    assert first["runtime"]["instance"] == second["runtime"]["instance"]
    assert first["runtime"]["data"]["code"] == second["runtime"]["data"]["code"]
    assert first["projectionRevision"] != second["projectionRevision"]
    assert (
        first["runtime"]["data"]["executionCells"]
        == second["runtime"]["data"]["executionCells"]
    )
    assert second["runtime"]["instance"] != third["runtime"]["instance"]
    assert second["projectionRevision"] != third["projectionRevision"]


def test_projection_revision_survives_nonprojection_artifact_changes(
    notebook_path: Path,
) -> None:
    studio = _configured(notebook_path)
    document = studio.views["dashboard"].root / "index.html"

    with TestClient(create_asgi_app(studio.notebook)) as client:
        first = client.get("/_marimo-studio/views/dashboard/config").json()
        source = document.read_text(encoding="utf-8")
        changed = source.replace("margin: 0;", "margin: 1px;", 1)
        assert changed != source
        document.write_text(
            changed,
            encoding="utf-8",
        )
        second = client.get("/_marimo-studio/views/dashboard/config").json()

    assert first["revision"] != second["revision"]
    assert first["projectionRevision"] == second["projectionRevision"]


def test_server_runtime_instance_changes_with_transport_token(
    notebook_path: Path,
) -> None:
    from marimo._server.tokens import SkewProtectionToken

    studio = _configured(notebook_path)
    app = _marimo_app(studio.notebook)
    manager = _session_manager(app)

    with TestClient(app) as client:
        first = client.get("/_marimo-studio/views/dashboard/config").json()
        manager._token_manager.skew_protection_token = SkewProtectionToken.random()
        second = client.get("/_marimo-studio/views/dashboard/config").json()

    assert (
        first["runtime"]["data"]["capabilityToken"]
        != second["runtime"]["data"]["capabilityToken"]
    )
    assert first["runtime"]["instance"] != second["runtime"]["instance"]


def test_server_runtime_instance_stays_stable_when_lookup_session_connects(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    studio = _configured(notebook_path)
    app = _marimo_app(studio.notebook)
    _edit_mode(app)
    monkeypatch.setattr(
        "marimo_studio._compat.server.session_state.PrivateSessionState.live_cells",
        lambda _sessions, _context, _session_id: None,
    )

    with TestClient(app) as client:
        initial = client.get("/_marimo-studio/views/dashboard/config").json()
        connected = client.get(
            "/_marimo-studio/views/dashboard/config",
            headers={"Marimo-Session-Id": "s_123456"},
        ).json()

    assert initial["runtime"]["instance"] == connected["runtime"]["instance"]
