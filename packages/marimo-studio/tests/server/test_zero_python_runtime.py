from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from urllib.parse import parse_qs, urljoin, urlsplit

import pytest
from starlette.testclient import TestClient

from marimo_studio._server.agent.clients import StudioClientRegistry
from marimo_studio._server.prepared_views import (
    PreparedViewRegistry,
    PreparedViewRequest,
)
from marimo_studio._server.publication_runtime import (
    PreparedRuntimeState,
    PublicationRuntimeProjector,
)
from marimo_studio._server.records import ServerContext, ServerHandle
from marimo_studio._server.runtime.catalog import ZeroPythonRuntime
from marimo_studio._server.runtime.progress import RuntimeProgress, RuntimeProgressSink
from marimo_studio._workspace.metadata import update_notebook_config

from ..app_helpers import configured, edit_mode, marimo_app


def test_zero_python_runtime_uses_notebook_scoped_publication_owner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    publication_owner = object()
    scope = SimpleNamespace(publications=publication_owner)
    notebooks = SimpleNamespace(get=lambda _notebook: scope)
    calls: list[tuple[object, ...]] = []
    updates: list[RuntimeProgress] = []

    async def project(
        self: PublicationRuntimeProjector,
        snapshot: object,
        context: object,
        authority: str,
        session_id: str | None,
        binding_id: str | None,
        presentation_session_id: str | None,
        *,
        client_id: str | None = None,
        progress: RuntimeProgressSink | None = None,
    ) -> PreparedRuntimeState:
        calls.append(
            (
                self,
                snapshot,
                context,
                authority,
                session_id,
                binding_id,
                presentation_session_id,
                client_id,
            )
        )
        if progress is not None:
            progress(RuntimeProgress("Capturing notebook states", 1, 3))
        return PreparedRuntimeState("a" * 64, {"manifestUrl": "/prepared"})

    monkeypatch.setattr(PublicationRuntimeProjector, "project", project)
    resolved = SimpleNamespace(runtime_cell_refs=lambda _cells: {"cell-ref": "cell-id"})
    snapshot = SimpleNamespace(resolved=resolved)
    context = ServerContext(
        notebook=tmp_path / "notebook.py",
        file_key="notebook.py",
        base_url="",
        mode="edit",
        dev=True,
        routing_query=(),
        user_config={},
        config_overrides={},
        server_token="token",
        handle=ServerHandle(object()),
        internal_url="http://127.0.0.1:4312/",
    )
    runtime = ZeroPythonRuntime(cast(Any, notebooks))

    result = asyncio.run(
        runtime.project(
            cast(Any, snapshot),
            context,
            "s_editor",
            "s_editor",
            "s_preview",
            client_id="browser-client-1234",
            progress=updates.append,
        )
    )

    assert updates == [RuntimeProgress("Capturing notebook states", 1, 3)]
    assert result.runtime_id == "zero-python"
    assert result.instance == "a" * 64
    assert result.cell_refs == {"cell-ref": "cell-id"}
    assert calls[0][3:] == (
        "edit",
        "s_editor",
        "s_editor",
        "s_preview",
        "browser-client-1234",
    )
    assert (
        cast(PublicationRuntimeProjector, calls[0][0])._publications
        is publication_owner
    )


def test_prepared_manifest_follows_the_browser_editor_binding(
    notebook_path: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    studio = configured(notebook_path)
    update_notebook_config(
        studio.notebook,
        lambda config: config.update({"runtimes": ["server", "zero-python"]}),
    )
    app = marimo_app(studio.notebook)
    edit_mode(app)
    browser_client = "browser-client-1234"
    editor_session: str | None = "s_abcdef"
    publications: dict[tuple[str, str, str], Any] = {}
    index = tmp_path / "index.json"
    index.write_text('{"asset": "assets/value.txt"}', encoding="utf-8")
    asset = tmp_path / "value.txt"
    asset.write_text("prepared value", encoding="utf-8")

    async def session_for_client(
        _clients: StudioClientRegistry, client_id: str
    ) -> str | None:
        return editor_session if client_id == browser_client else None

    async def prepare(
        _registry: PreparedViewRegistry,
        request: PreparedViewRequest,
        *,
        progress: RuntimeProgressSink | None = None,
    ) -> Any:
        assert request.binding_id == editor_session
        assert request.session_id == editor_session
        instance = ("1" if editor_session == "s_abcdef" else "2") * 64

        def manifest(export_url: str) -> dict[str, object]:
            return {
                "schema": "marimo-studio.prepared.v1",
                "prepared": {
                    "schema": "marimo-export.prepared.v1",
                    "instance": instance,
                    "export_url": export_url,
                    "inputs": {},
                    "state_fingerprint": "c" * 64,
                },
                "projections": {"cells": {}, "outputs": {}, "values": {}},
                "document_sha256": "d" * 64,
                "view": "dashboard",
                "plan_digest": "b" * 64,
            }

        selected = SimpleNamespace(
            instance=instance, plan_digest="b" * 64, manifest=manifest
        )
        publications[("dashboard", request.binding_id, request.snapshot.revision)] = (
            selected
        )
        return selected

    def current(
        _registry: PreparedViewRegistry, view: str, binding: str, revision: str
    ) -> Any:
        return publications.get((view, binding, revision))

    async def publication_asset(
        _registry: PreparedViewRegistry, view: str, instance: str, relative: str
    ) -> Any:
        if view != "dashboard" or instance not in {"1" * 64, "2" * 64}:
            return None
        path = {"index.json": index, "assets/value.txt": asset}.get(relative)
        return SimpleNamespace(path=path, close=lambda: None) if path else None

    monkeypatch.setattr(StudioClientRegistry, "session_for_client", session_for_client)
    monkeypatch.setattr(PreparedViewRegistry, "prepare", prepare)
    monkeypatch.setattr(PreparedViewRegistry, "current", current)
    monkeypatch.setattr(PreparedViewRegistry, "poll_current", current)
    monkeypatch.setattr(PreparedViewRegistry, "publication_asset", publication_asset)
    monkeypatch.setattr(
        "marimo_studio._compat.server.session_state.PrivateSessionState.exists",
        lambda _sessions, _context, session_id: session_id == editor_session,
    )
    monkeypatch.setattr(
        "marimo_studio._compat.server.session_state.PrivateSessionState.ensure_started",
        lambda *_args: True,
    )
    params = {"runtime": "zero-python", "marimo_studio_client": browser_client}
    headers = {"Marimo-Studio-Preview-Session-Id": "s_123456"}
    with TestClient(app) as client:
        configured_response = client.get(
            "/_marimo-studio/views/dashboard/config", params=params, headers=headers
        )
        assert configured_response.status_code == 200, configured_response.text
        manifest_url = configured_response.json()["runtime"]["data"]["manifestUrl"]
        assert parse_qs(urlsplit(manifest_url).query)["marimo_studio_client"] == [
            browser_client
        ]
        assert "s_abcdef" not in manifest_url
        manifest = client.get(manifest_url, headers={"Origin": "null"})
        assert manifest.json()["prepared"]["instance"] == "1" * 64
        export_url = manifest.json()["prepared"]["export_url"]
        index_response = client.get(
            urljoin(export_url, "index.json"), headers={"Origin": "null"}
        )
        assert index_response.headers["Access-Control-Allow-Origin"] == "null"
        assert index_response.json() == {"asset": "assets/value.txt"}
        asset_response = client.get(
            urljoin(export_url, index_response.json()["asset"]),
            headers={"Origin": "null"},
        )
        assert asset_response.headers["Access-Control-Allow-Origin"] == "null"
        assert asset_response.text == "prepared value"

        editor_session = "s_ghijkl"
        assert client.get(manifest_url).status_code == 409
        rebound = client.get(
            "/_marimo-studio/views/dashboard/config", params=params, headers=headers
        )
        assert rebound.status_code == 200, rebound.text
        assert client.get(manifest_url).json()["prepared"]["instance"] == "2" * 64

        editor_session = None
        assert client.get(manifest_url).status_code == 409


def test_editor_controls_read_bindings_without_preparing_a_runtime(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    studio = configured(notebook_path)
    app = marimo_app(studio.notebook)
    edit_mode(app)
    bound = "s_abcdef"
    rebinding = False
    bindings: dict[str, object] = {"PKri-0": {"input": "sport", "path": []}}

    async def session_for_client(
        _clients: StudioClientRegistry, client_id: str
    ) -> str | None:
        return bound if client_id == "browser-client-1234" else None

    async def read_bindings(*_args: object) -> dict[str, object]:
        nonlocal bound
        if rebinding:
            bound = "s_ghijkl"
        return bindings

    async def live_cells(*_args: object, **_kwargs: object) -> None:
        return None

    async def prepare(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("Control metadata must not prepare notebook states")

    monkeypatch.setattr(StudioClientRegistry, "session_for_client", session_for_client)
    monkeypatch.setattr(PreparedViewRegistry, "prepare", prepare)
    monkeypatch.setattr(
        "marimo_studio._server.runtime.catalog.RuntimeRegistry.project", prepare
    )
    monkeypatch.setattr(
        "marimo_studio._compat.server.session_state.PrivateSessionState.live_cells",
        live_cells,
    )
    monkeypatch.setattr(
        "marimo_studio._compat.server.session_state.PrivateSessionState.control_bindings",
        read_bindings,
    )
    monkeypatch.setattr(
        "marimo_studio._compat.server.session_state.PrivateSessionState.exists",
        lambda _sessions, _context, session_id: session_id == bound,
    )
    with TestClient(app) as client:
        revision = client.get("/_marimo-studio/views/dashboard/runtimes").json()[
            "revision"
        ]
        params = {"marimo_studio_client": "browser-client-1234", "revision": revision}
        headers = {"Marimo-Session-Id": "s_abcdef"}
        response = client.get(
            "/_marimo-studio/views/dashboard/controls", params=params, headers=headers
        )
        assert response.status_code == 200, response.text
        assert response.json()["controls"]["bindings"] == bindings
        assert response.json()["revision"] == revision
        unchanged = client.get(
            "/_marimo-studio/views/dashboard/controls",
            params=params,
            headers={**headers, "If-None-Match": response.headers["ETag"]},
        )
        assert unchanged.status_code == 304

        rebinding = True
        rebound = client.get(
            "/_marimo-studio/views/dashboard/controls", params=params, headers=headers
        )
        assert rebound.status_code == 409
