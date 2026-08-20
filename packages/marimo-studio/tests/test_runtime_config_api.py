from __future__ import annotations

from collections.abc import Iterator, MutableMapping
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest
from starlette.testclient import TestClient

from marimo_studio import create_asgi_app
from marimo_studio._runtime import SERVER_RUNTIME, ZERO_PYTHON_RUNTIME
from marimo_studio._server.live_clients import StudioClientRegistry
from marimo_studio._server.prepared_views import (
    PreparedViewRegistry,
    PreparedViewRequest,
)
from marimo_studio._server.presentation import NotebookPresentation
from marimo_studio._server.runtimes import RuntimeProjectionRequest, RuntimeProvider
from marimo_studio._server.session_controls import SessionControlBindingReader
from marimo_studio._workspace.metadata import update_notebook_config
from marimo_studio.errors import PublicationLimitError

from .app_helpers import configured as _configured
from .app_helpers import edit_mode as _edit_mode
from .app_helpers import marimo_app as _marimo_app
from .app_helpers import studio_bootstrap as _studio_bootstrap


def test_studio_runtime_config_targets_its_editor_session(
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

    async def runtime_config(
        runtime_request: RuntimeProjectionRequest,
        provider: RuntimeProvider,
    ) -> dict[str, object]:
        captured["runtime_id"] = provider.descriptor.id
        captured["authority"] = runtime_request.authority
        captured["session_id"] = runtime_request.session_id
        captured["binding_id"] = runtime_request.binding_id
        return {"runtime": {"descriptor": SERVER_RUNTIME.to_dict()}}

    def attach_session(
        _attachment: object,
        _context: object,
        consumer_id: str,
        session_id: str,
    ) -> bool:
        captured["consumer_id"] = consumer_id
        captured["editor_session_id"] = session_id
        return True

    monkeypatch.setattr(
        StudioClientRegistry,
        "session_for_client",
        session_for_client,
    )
    monkeypatch.setattr(
        "marimo_studio._server.runtime_config_api.build_runtime_config",
        runtime_config,
    )
    monkeypatch.setattr(
        "marimo_studio._compat.server.session_state.PrivateSessionState.exists",
        lambda _sessions, _context, session_id: session_id == "s_123456",
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
                "Marimo-Session-Id": "s_abc123",
                "Marimo-Studio-Preview-Session-Id": "s_view01",
            },
        )
        invalid = client.get(
            "/_marimo-studio/views/dashboard/config",
            params={"marimo_studio_client": "browser-client-1234"},
        )

    assert response.status_code == 200
    assert response.json()["editorSessionId"] == "s_123456"
    assert captured == {
        "client_id": "browser-client-1234",
        "runtime_id": "server",
        "authority": "edit",
        "session_id": "s_123456",
        "binding_id": "browser-client-1234",
        "consumer_id": "s_view01",
        "editor_session_id": "s_123456",
    }
    assert invalid.status_code == 400
    assert invalid.json()["error"] == "invalid-studio-session"


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

    original_snapshot_async = NotebookPresentation.snapshot_async

    async def snapshot_async(
        _presentation: NotebookPresentation,
        _view_name: str,
    ) -> object:
        active["session_id"] = "s_654321"
        return await original_snapshot_async(_presentation, _view_name)

    async def session_for_client(
        _clients: StudioClientRegistry,
        _client_id: str,
    ) -> str:
        return active["session_id"]

    async def runtime_config(
        runtime_request: RuntimeProjectionRequest,
        _provider: RuntimeProvider,
    ) -> dict[str, object]:
        captured["session_id"] = runtime_request.session_id
        captured["binding_id"] = runtime_request.binding_id
        captured["authority"] = runtime_request.authority
        return {"runtime": {"descriptor": SERVER_RUNTIME.to_dict()}}

    def attach_session(
        _attachment: object,
        _context: object,
        _consumer_id: str,
        session_id: str,
    ) -> bool:
        captured["editor_session"] = sessions[session_id]
        return True

    monkeypatch.setattr(NotebookPresentation, "snapshot_async", snapshot_async)
    monkeypatch.setattr(
        StudioClientRegistry,
        "session_for_client",
        session_for_client,
    )
    monkeypatch.setattr(
        "marimo_studio._server.runtime_config_api.build_runtime_config",
        runtime_config,
    )
    monkeypatch.setattr(
        "marimo_studio._compat.server.session_state.PrivateSessionState.exists",
        lambda _sessions, _context, session_id: session_id in sessions,
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
            headers={"Marimo-Studio-Preview-Session-Id": "s_view01"},
        )

    assert response.status_code == 200
    assert response.json()["editorSessionId"] == "s_654321"
    assert captured == {
        "session_id": "s_654321",
        "binding_id": "browser-client-1234",
        "authority": "edit",
        "editor_session": sessions["s_654321"],
    }


def test_isolated_preview_uses_editor_session_without_attachment(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    studio = _configured(notebook_path)
    app = _marimo_app(studio.notebook)
    _edit_mode(app)
    captured: dict[str, object] = {}

    async def session_for_client(
        _clients: StudioClientRegistry,
        _client_id: str,
    ) -> str:
        return "s_123456"

    async def runtime_config(
        runtime_request: RuntimeProjectionRequest,
        provider: RuntimeProvider,
    ) -> dict[str, object]:
        captured["runtime"] = provider.descriptor.id
        captured["session_id"] = runtime_request.session_id
        captured["binding_id"] = runtime_request.binding_id
        return {"runtime": {"descriptor": provider.descriptor.to_dict()}}

    def reject_attachment(*_args: object) -> bool:
        raise AssertionError("isolated runtime attempted to attach a preview")

    monkeypatch.setattr(StudioClientRegistry, "session_for_client", session_for_client)
    monkeypatch.setattr(
        "marimo_studio._server.runtime_config_api.build_runtime_config",
        runtime_config,
    )
    monkeypatch.setattr(
        "marimo_studio._compat.server.session_state.PrivateSessionState.exists",
        lambda _sessions, _context, session_id: session_id == "s_123456",
    )
    monkeypatch.setattr(
        "marimo_studio._compat.server.existing_session.PrivateExistingSessionAttachment.attach",
        reject_attachment,
    )

    with TestClient(app) as client:
        response = client.get(
            "/_marimo-studio/views/dashboard/config",
            params={
                "runtime": "wasm",
                "marimo_studio_client": "browser-client-1234",
            },
            headers={
                "Marimo-Session-Id": "s_abc123",
                "Marimo-Studio-Preview-Session-Id": "s_abc123",
            },
        )

    assert response.status_code == 200
    assert captured == {
        "runtime": "wasm",
        "session_id": "s_123456",
        "binding_id": "browser-client-1234",
    }


def test_runtime_config_keeps_parallel_preview_bootstraps(
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

    async def runtime_config(*_args: object, **_kwargs: object) -> dict[str, object]:
        return {"runtime": {"descriptor": SERVER_RUNTIME.to_dict()}}

    monkeypatch.setattr(
        "marimo_studio._server.runtime_config_api.build_runtime_config",
        runtime_config,
    )
    monkeypatch.setattr(
        "marimo_studio._compat.server.session_state.PrivateSessionState.exists",
        lambda _sessions, _context, session_id: session_id == "s_123456",
    )
    monkeypatch.setattr(
        "marimo_studio._compat.server.existing_session.PrivateExistingSessionAttachment.attach",
        lambda _attachment, _context, _consumer_id, _session_id: True,
    )

    with TestClient(app) as client:
        statuses = [
            client.get(
                "/_marimo-studio/views/dashboard/config",
                params={
                    "runtime": "server",
                    "marimo_studio_client": "browser-client-1234",
                },
                headers={
                    "Marimo-Studio-Preview-Session-Id": f"s_v{index:05d}",
                },
            ).status_code
            for index in range(2)
        ]

    assert statuses == [200, 200]


def test_zero_python_preview_uses_editor_session_without_preview_session(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    studio = _configured(notebook_path)
    app = _marimo_app(studio.notebook)
    _edit_mode(app)
    captured: list[PreparedViewRequest] = []

    async def session_for_client(
        _clients: StudioClientRegistry,
        _client_id: str,
    ) -> str:
        return "s_123456"

    async def prepare(
        _publications: PreparedViewRegistry,
        request: PreparedViewRequest,
    ) -> object:
        captured.append(request)
        return SimpleNamespace(
            instance="a" * 64,
            plan_digest="d" * 64,
        )

    def reject_attachment(*_args: object) -> bool:
        raise AssertionError("sessionless runtime attempted to attach a preview")

    monkeypatch.setattr(StudioClientRegistry, "session_for_client", session_for_client)
    monkeypatch.setattr(PreparedViewRegistry, "prepare", prepare)
    monkeypatch.setattr(
        "marimo_studio._compat.server.session_state.PrivateSessionState.exists",
        lambda _sessions, _context, session_id: session_id == "s_123456",
    )
    monkeypatch.setattr(
        "marimo_studio._compat.server.existing_session.PrivateExistingSessionAttachment.attach",
        reject_attachment,
    )

    with TestClient(app) as client:
        response = client.get(
            "/_marimo-studio/views/dashboard/config",
            params={
                "runtime": "zero-python",
                "marimo_studio_client": "browser-client-1234",
            },
            headers={"Marimo-Session-Id": "s_abc123"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["runtime"] == {
        "descriptor": ZERO_PYTHON_RUNTIME.to_dict(),
        "instance": "a" * 64,
        "data": {
            "manifestUrl": (
                "/_marimo-studio/views/dashboard/zero-python/current?"
                "marimo_studio_client=browser-client-1234&"
                f"revision={captured[0].snapshot.revision}"
            ),
            "planDigest": "d" * 64,
        },
    }
    assert payload["editorSessionId"] == "s_123456"
    assert captured[0].server == "http://testserver:80/"
    assert captured[0].session_id == "s_123456"
    assert captured[0].binding_id == "browser-client-1234"


def test_zero_python_capture_limit_returns_a_repairable_413(
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

    async def prepare(
        _publications: PreparedViewRegistry,
        _request: PreparedViewRequest,
    ) -> object:
        raise PublicationLimitError(
            "The prepared export exceeds its zero-Python capture byte limit."
        )

    monkeypatch.setattr(StudioClientRegistry, "session_for_client", session_for_client)
    monkeypatch.setattr(PreparedViewRegistry, "prepare", prepare)
    monkeypatch.setattr(
        "marimo_studio._compat.server.session_state.PrivateSessionState.exists",
        lambda _sessions, _context, session_id: session_id == "s_123456",
    )

    with TestClient(app) as client:
        response = client.get(
            "/_marimo-studio/views/dashboard/config",
            params={
                "runtime": "zero-python",
                "marimo_studio_client": "browser-client-1234",
            },
            headers={"Accept": "application/json"},
        )

    assert response.status_code == 413
    assert response.json() == {
        "error": "zero-python-state-limit",
        "message": ("The prepared export exceeds its zero-Python capture byte limit."),
        "hint": PublicationLimitError.public_hint,
    }


@dataclass
class _ControlSnapshotApi:
    client: TestClient
    params: dict[str, str]
    headers: dict[str, str]
    revision: str
    notebook_revision: str
    inspected: list[tuple[str, str]]
    owns_session: dict[str, bool]
    control_generation: dict[str, int]


@pytest.fixture
def control_snapshot_api(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[_ControlSnapshotApi]:
    studio = _configured(notebook_path)
    app = _marimo_app(studio.notebook)
    _edit_mode(app)
    snapshot = NotebookPresentation(studio.notebook).snapshot("dashboard")
    notebook_revision = snapshot.notebook_revision
    inspected: list[tuple[str, str]] = []
    owns_session = {"value": True}
    control_generation = {"value": 7}

    async def session_for_client(
        _clients: StudioClientRegistry,
        _client_id: str,
    ) -> str:
        return "s_123456"

    async def bindings(
        _reader: SessionControlBindingReader,
        _context: object,
        session_id: str,
        notebook_revision: str,
        control_revision: int,
    ) -> dict[str, dict[str, object]]:
        inspected.append((session_id, f"{notebook_revision}:{control_revision}"))
        return {
            "editor-root": {"input": "filters", "path": []},
            "editor-region": {
                "input": "filters",
                "path": [{"kind": "key", "value": "region"}],
            },
        }

    def reject_side_effect(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("control snapshot invoked a prepared or attached runtime")

    monkeypatch.setattr(StudioClientRegistry, "session_for_client", session_for_client)
    monkeypatch.setattr(SessionControlBindingReader, "bindings", bindings)
    monkeypatch.setattr(
        "marimo_studio._compat.server.session_state.PrivateSessionState.exists",
        lambda _sessions, _context, session_id: (
            owns_session["value"] and session_id == "s_123456"
        ),
    )
    monkeypatch.setattr(
        "marimo_studio._compat.server.session_state.PrivateSessionState.live_cells",
        lambda *_args: None,
    )
    monkeypatch.setattr(
        "marimo_studio._compat.server.session_state.PrivateSessionState.control_revision",
        lambda *_args: control_generation["value"],
    )
    monkeypatch.setattr(PreparedViewRegistry, "prepare", reject_side_effect)
    monkeypatch.setattr(
        "marimo_studio._compat.server.existing_session.PrivateExistingSessionAttachment.attach",
        reject_side_effect,
    )

    with TestClient(app) as client:
        workspace = client.get("/studio/dashboard/")
        bootstrap = _studio_bootstrap(workspace.text)
        revision = snapshot.revision
        yield _ControlSnapshotApi(
            client=client,
            params={
                "revision": revision,
                "marimo_studio_client": bootstrap["clientId"],
            },
            headers={"Marimo-Session-Id": "s_123456"},
            revision=revision,
            notebook_revision=notebook_revision,
            inspected=inspected,
            owns_session=owns_session,
            control_generation=control_generation,
        )


def test_control_snapshot_returns_bindings_and_conditional_updates(
    control_snapshot_api: _ControlSnapshotApi,
) -> None:
    api = control_snapshot_api
    server = api.client.get(
        "/_marimo-studio/views/dashboard/controls",
        params={**api.params, "runtime": "server"},
        headers=api.headers,
    )
    unchanged = api.client.get(
        "/_marimo-studio/views/dashboard/controls",
        params={**api.params, "runtime": "server"},
        headers={**api.headers, "If-None-Match": server.headers["etag"]},
    )
    api.control_generation["value"] = 8
    changed = api.client.get(
        "/_marimo-studio/views/dashboard/controls",
        params={**api.params, "runtime": "server"},
        headers={**api.headers, "If-None-Match": server.headers["etag"]},
    )

    assert server.status_code == 200
    server_payload = server.json()
    assert server_payload["schema"] == 1
    assert server_payload["revision"] == api.revision
    assert server_payload["runtime"] == "server"
    assert server_payload["controlRevision"] == 7
    assert server_payload["controls"]["bindings"] == {
        "editor-root": {"input": "filters", "path": []},
        "editor-region": {
            "input": "filters",
            "path": [{"kind": "key", "value": "region"}],
        },
    }
    assert "native" in server_payload["controls"]
    assert unchanged.status_code == 304
    assert unchanged.headers["etag"] == server.headers["etag"]
    assert changed.status_code == 200
    assert changed.json()["controlRevision"] == 8
    assert changed.headers["etag"] != server.headers["etag"]
    assert api.inspected == [
        ("s_123456", f"{api.notebook_revision}:7"),
        ("s_123456", f"{api.notebook_revision}:8"),
    ]


def test_control_snapshot_describes_each_browser_runtime(
    control_snapshot_api: _ControlSnapshotApi,
) -> None:
    api = control_snapshot_api
    wasm = api.client.get(
        "/_marimo-studio/views/dashboard/controls",
        params={**api.params, "runtime": "wasm"},
        headers=api.headers,
    )
    prepared = api.client.get(
        "/_marimo-studio/views/dashboard/controls",
        params={**api.params, "runtime": "zero-python"},
        headers=api.headers,
    )

    assert wasm.status_code == 200
    assert set(wasm.json()["controls"]) == {"native"}
    assert prepared.status_code == 200
    assert "controls" not in prepared.json()


def test_control_snapshot_requires_the_bound_editor_session(
    control_snapshot_api: _ControlSnapshotApi,
) -> None:
    api = control_snapshot_api
    api.owns_session["value"] = False
    cross_notebook = api.client.get(
        "/_marimo-studio/views/dashboard/controls",
        params={**api.params, "runtime": "server"},
        headers=api.headers,
    )
    api.owns_session["value"] = True
    wrong_session = api.client.get(
        "/_marimo-studio/views/dashboard/controls",
        params={**api.params, "runtime": "server"},
        headers={"Marimo-Session-Id": "s_654321"},
    )
    missing_client = api.client.get(
        "/_marimo-studio/views/dashboard/controls",
        params={"revision": api.revision, "runtime": "server"},
        headers=api.headers,
    )

    assert cross_notebook.status_code == 409
    assert wrong_session.status_code == 409
    assert missing_client.status_code == 400


def test_control_snapshot_route_rejects_mutating_methods(
    control_snapshot_api: _ControlSnapshotApi,
) -> None:
    api = control_snapshot_api
    wrong_method = api.client.post(
        "/_marimo-studio/views/dashboard/controls",
        params={**api.params, "runtime": "server"},
        headers=api.headers,
    )

    assert wrong_method.status_code == 405


def test_run_mode_rejects_control_snapshot_authority(notebook_path: Path) -> None:
    studio = _configured(notebook_path)

    with TestClient(create_asgi_app(studio.notebook)) as client:
        response = client.get(
            "/_marimo-studio/views/dashboard/controls",
            params={
                "runtime": "server",
                "revision": "a" * 64,
                "marimo_studio_client": "browser-client-1234",
            },
            headers={"Marimo-Session-Id": "s_123456"},
        )

    assert response.status_code == 403


def test_sessionless_zero_python_config_reports_publication_pending(
    notebook_path: Path,
) -> None:
    studio = _configured(notebook_path)
    app = _marimo_app(studio.notebook)
    _edit_mode(app)

    with TestClient(app) as client:
        response = client.get(
            "/_marimo-studio/views/dashboard/config?runtime=zero-python",
            headers={"Accept": "application/json"},
        )

    assert response.status_code == 409
    assert response.json() == {
        "error": "zero-python-publication-unavailable",
        "message": (
            "The zero-Python publication for this view is unavailable. "
            "Open the view in Studio to prepare its current notebook state."
        ),
        "transient": True,
    }


def test_run_mode_never_selects_zero_python_runtime(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    studio = _configured(notebook_path)

    def configure(config: MutableMapping[str, object]) -> None:
        config["runtime"] = "zero-python"
        config["runtimes"] = ["server", "wasm", "zero-python"]

    update_notebook_config(studio.notebook, configure)

    def reject_current(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("run mode attempted to select a prepared publication")

    async def reject_prepare(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("read authority attempted to prepare a publication")

    monkeypatch.setattr(PreparedViewRegistry, "current", reject_current)
    monkeypatch.setattr(PreparedViewRegistry, "prepare", reject_prepare)

    with TestClient(create_asgi_app(studio.notebook)) as client:
        selected = client.get(
            "/_marimo-studio/views/dashboard/config",
            params={"marimo_studio_client": "browser-client-1234"},
        )
        rejected = client.get(
            "/_marimo-studio/views/dashboard/config",
            params={
                "runtime": "zero-python",
                "marimo_studio_client": "browser-client-1234",
            },
        )

    assert selected.status_code == 200
    assert selected.json()["runtime"]["descriptor"] == SERVER_RUNTIME.to_dict()
    assert rejected.status_code == 400
    assert rejected.json()["error"] == "runtime-unavailable"
