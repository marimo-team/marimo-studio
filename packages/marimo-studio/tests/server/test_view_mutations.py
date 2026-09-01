from __future__ import annotations

import asyncio
import shutil
import threading
from collections.abc import MutableMapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path, PurePosixPath
from typing import Any, cast

import pytest
from starlette.testclient import TestClient

import marimo_studio._server.studio.routes as studio_api_module
from marimo_studio import create_asgi_app
from marimo_studio._views.api import prepare_view
from marimo_studio._views.records import ViewDocument
from marimo_studio._workspace import load_studio
from marimo_studio._workspace.config import load_studio_definition
from marimo_studio._workspace.metadata import update_notebook_config
from marimo_studio.errors import WorkspaceGenerationConflictError
from marimo_studio.view_providers import ProjectDiagnostic, SourceLocation
from marimo_studio.view_providers._host import provider_registry

from ..app_helpers import configured as _configured
from ..app_helpers import edit_mode as _edit_mode
from ..app_helpers import marimo_app as _marimo_app
from ..app_helpers import session_manager as _session_manager
from ._view_mutation_test_support import _create_owned_view
from .app_test_support import (
    _studio_host,
)


def _source_owner_headers(client: TestClient, view: str) -> dict[str, str]:
    project = client.get(f"/_marimo-studio/views/{view}/project").json()
    return {
        "Marimo-Studio-Catalog-Generation": cast(
            str,
            project["catalog_generation"],
        ),
        "Marimo-Studio-View-Generation": cast(str, project["view_generation"]),
    }


def test_view_list_tracks_new_folders_without_restarting_marimo(
    notebook_path: Path,
) -> None:
    studio = _configured(notebook_path)
    app = create_asgi_app(studio.notebook)

    with TestClient(app) as client:
        before = client.get("/_marimo-studio/views").json()
        prepare_view(studio.notebook, "operations")
        after = client.get("/_marimo-studio/views").json()
        page = client.get("/operations/")

    assert [item["name"] for item in before["views"]] == [
        "dashboard",
        "executive",
    ]
    assert [item["name"] for item in after["views"]] == [
        "dashboard",
        "executive",
        "operations",
    ]
    assert len(before["generation"]) == 64
    assert before["generation"] != after["generation"]
    before_views = {item["name"]: item["generation"] for item in before["views"]}
    after_views = {item["name"]: item["generation"] for item in after["views"]}
    assert all(len(generation) == 64 for generation in after_views.values())
    assert before_views == {
        name: after_views[name] for name in ("dashboard", "executive")
    }
    assert page.status_code == 200


def test_catalog_generation_tracks_default_without_replacing_views(
    notebook_path: Path,
) -> None:
    studio = _configured(notebook_path)
    before = load_studio(studio.notebook)

    def select_executive(config: MutableMapping[str, Any]) -> None:
        config["default"] = "executive"

    update_notebook_config(studio.notebook, select_executive)
    after = load_studio(studio.notebook)

    assert after.catalog_generation != before.catalog_generation
    assert after.view_generations == before.view_generations


def test_cancelled_http_source_write_finishes_commit_and_refresh_once(
    tmp_path: Path,
) -> None:
    path = tmp_path / "index.html"
    started = threading.Event()
    release = threading.Event()
    refreshes = 0

    def write() -> ViewDocument:
        started.set()
        assert release.wait(timeout=2)
        path.write_text("committed", encoding="utf-8")
        return ViewDocument(
            PurePosixPath("index.html"),
            "html",
            "edit",
            "committed",
            "revision",
        )

    class Development:
        async def refresh(self, view_name: str) -> None:
            nonlocal refreshes
            assert view_name == "dashboard"
            refreshes += 1

    async def exercise() -> None:
        mutation = asyncio.create_task(
            studio_api_module._write_source_and_refresh(
                write,
                cast(Any, Development()),
                "dashboard",
            )
        )
        assert await asyncio.to_thread(started.wait, 1)
        mutation.cancel()
        await asyncio.sleep(0)
        mutation.cancel()
        await asyncio.sleep(0)
        assert not mutation.done()
        assert not path.exists()

        release.set()
        with pytest.raises(asyncio.CancelledError):
            await mutation
        assert path.read_text(encoding="utf-8") == "committed"
        assert refreshes == 1

    try:
        asyncio.run(exercise())
    finally:
        release.set()


def test_definition_state_initializes_the_first_view_from_edit_mode(
    notebook_path: Path,
) -> None:
    setup = prepare_view(notebook_path)
    assert setup.workspace is not None
    shutil.rmtree(setup.workspace.view_root)
    definition = load_studio_definition(notebook_path)
    app = _marimo_app(notebook_path)
    _edit_mode(app)
    headers = {"Marimo-Server-Token": str(_session_manager(app).skew_protection_token)}

    with TestClient(app) as client:
        status_before = client.get("/_marimo-studio/status")
        views_before = client.get("/_marimo-studio/views")
        before_payload = views_before.json()
        initializer = client.get("/")
        host = _studio_host(initializer.text)
        created = _create_owned_view(
            client,
            definition.default_view,
            headers,
            cast(str, before_payload["generation"]),
        )
        status_after = client.get("/_marimo-studio/status")
        bootstrap = client.get(
            f"{host['urls']['bootstrap']}&marimo_studio_view=dashboard"
        )
        workspace = client.get("/studio/dashboard/")

    assert status_before.json() == {
        "schema": 1,
        "state": "needs-view",
        "default_view": "dashboard",
        "views": [],
    }
    assert before_payload["schema"] == 1
    assert before_payload["default_view"] == "dashboard"
    assert before_payload["default_starter"] == "marimo-studio/vanilla:default"
    assert before_payload["views"] == []
    assert initializer.status_code == 200
    assert 'data-marimo-studio-state="needs-view"' in initializer.text
    assert 'id="marimo-studio-editor"' in initializer.text
    assert host["state"] == "needs-view"
    assert host["defaultView"] == "dashboard"
    assert created.status_code == 201
    created_payload = created.json()
    assert created_payload == {"schema": 1, "name": "dashboard"}
    assert status_after.json() == {
        "schema": 1,
        "state": "ready",
        "default_view": "dashboard",
        "views": ["dashboard"],
    }
    assert bootstrap.status_code == 200
    assert bootstrap.json()["selectedView"] == "dashboard"
    assert bootstrap.json()["clientId"] == host["clientId"]
    assert workspace.status_code == 200
    assert (definition.view_root / "dashboard" / "view.toml").is_file()
    assert (definition.view_root / "dashboard" / "index.html").is_file()


def test_definition_state_returns_structured_run_repair(
    notebook_path: Path,
) -> None:
    setup = prepare_view(notebook_path)
    assert setup.workspace is not None
    shutil.rmtree(setup.workspace.view_root)

    with TestClient(create_asgi_app(notebook_path)) as client:
        response = client.get("/", headers={"Accept": "application/json"})

    assert response.status_code == 409
    assert response.json() == {
        "error": "workspace-not-initialized",
        "message": "Studio is configured and needs its first view 'dashboard'.",
        "state": "needs-view",
        "default_view": "dashboard",
        "views": [],
        "hint": "Open the notebook in edit mode and create its first view.",
    }


def test_workspace_status_reports_configuration_errors(
    notebook_path: Path,
) -> None:
    studio = _configured(notebook_path)

    def select_missing(config: MutableMapping[str, Any]) -> None:
        config["default"] = "missing"

    update_notebook_config(studio.notebook, select_missing)

    with TestClient(create_asgi_app(studio.notebook)) as client:
        status = client.get("/_marimo-studio/status")

    assert status.status_code == 200
    assert status.json()["schema"] == 1
    assert status.json()["state"] == "error"
    assert status.json()["error"] == "configuration-error"


def test_edit_workspace_creates_views_and_conditionally_updates_source(
    notebook_path: Path,
) -> None:
    studio = _configured(notebook_path)
    app = _marimo_app(studio.notebook)
    _edit_mode(app)
    mutation_headers = {
        "Marimo-Server-Token": str(_session_manager(app).skew_protection_token)
    }

    with TestClient(app) as client:
        loaded = client.get("/_marimo-studio/views/dashboard/source/index.html")
        owner_headers = _source_owner_headers(client, "dashboard")
        replacement = loaded.text.replace(
            '<main id="app-shell">',
            '<main id="app-shell"><h1>Updated in Studio</h1>',
        ).replace("\n", "\r\n")
        saved = client.put(
            "/_marimo-studio/views/dashboard/source/index.html",
            content=replacement,
            headers={
                "If-Match": loaded.headers["etag"],
                **owner_headers,
                **mutation_headers,
            },
        )
        stale = client.put(
            "/_marimo-studio/views/dashboard/source/index.html",
            content="stale",
            headers={
                "If-Match": loaded.headers["etag"],
                **owner_headers,
                **mutation_headers,
            },
        )
        created = _create_owned_view(client, "operations", mutation_headers)
        duplicate = _create_owned_view(client, "operations", mutation_headers)
        invalid = _create_owned_view(client, "Operations Report", mutation_headers)
        generation = client.get("/_marimo-studio/views").json()["generation"]
        null_starter = client.post(
            "/_marimo-studio/views",
            headers=mutation_headers,
            json={
                "catalog_generation": generation,
                "name": "null-starter",
                "starter": None,
            },
        )

    assert loaded.status_code == 200
    assert loaded.headers["content-type"].startswith("text/plain")
    assert loaded.headers["etag"].startswith('"sha256:')
    assert saved.status_code == 204
    assert saved.headers["etag"] != loaded.headers["etag"]
    assert (
        studio.views["dashboard"].root / "index.html"
    ).read_bytes() == replacement.encode()
    assert stale.status_code == 412
    assert stale.json()["error"] == "source-conflict"
    assert stale.json()["revision"] == saved.headers["etag"].strip('"')
    assert created.status_code == 201
    assert created.json() == {"schema": 1, "name": "operations"}
    assert (studio.view_root / "operations" / "view.toml").is_file()
    assert (studio.view_root / "operations" / "index.html").is_file()
    assert duplicate.status_code == 409
    assert duplicate.json()["error"] == "view-exists"
    assert invalid.status_code == 400
    assert invalid.json()["error"] == "invalid-view-name"
    assert null_starter.status_code == 400
    assert null_starter.json()["error"] == "invalid-view-starter"


def test_source_put_rejects_an_oversized_chunked_body(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    studio = _configured(notebook_path)
    app = _marimo_app(studio.notebook)
    _edit_mode(app)
    monkeypatch.setattr(studio_api_module, "SOURCE_DOCUMENT_MAX_BYTES", 8)

    with TestClient(app) as client:
        loaded = client.get("/_marimo-studio/views/dashboard/source/index.html")
        owner_headers = _source_owner_headers(client, "dashboard")
        rejected = client.put(
            "/_marimo-studio/views/dashboard/source/index.html",
            content=iter((b"too-", b"large")),
            headers={
                "If-Match": loaded.headers["etag"],
                **owner_headers,
                "Marimo-Server-Token": str(_session_manager(app).skew_protection_token),
            },
        )

    assert rejected.status_code == 413
    assert rejected.json()["error"] == "source-too-large"


def test_concurrent_same_name_view_posts_commit_once(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    studio = _configured(notebook_path)
    app = _marimo_app(studio.notebook)
    _edit_mode(app)
    headers = {"Marimo-Server-Token": str(_session_manager(app).skew_protection_token)}
    provider = provider_registry().get("marimo-studio/vanilla")
    create_files = provider.create
    planned = threading.Barrier(2)

    def synchronize_plan(*args: Any, **kwargs: Any) -> Any:
        planned.wait(timeout=5)
        return create_files(*args, **kwargs)

    monkeypatch.setattr(provider, "create", synchronize_plan)

    with TestClient(app) as client:
        generation = cast(
            str,
            client.get("/_marimo-studio/views").json()["generation"],
        )

        def create():
            return _create_owned_view(client, "operations", headers, generation)

        with ThreadPoolExecutor(max_workers=2) as executor:
            responses = tuple(executor.map(lambda _index: create(), range(2)))

    assert sorted(response.status_code for response in responses) == [201, 409]
    conflict = next(response for response in responses if response.status_code == 409)
    assert conflict.json()["error"] == "workspace-generation-conflict"
    assert tuple(load_studio(notebook_path).views).count("operations") == 1


def test_view_creation_rejects_a_stale_catalog_until_its_owner_is_refreshed(
    notebook_path: Path,
) -> None:
    studio = _configured(notebook_path)
    app = _marimo_app(studio.notebook)
    _edit_mode(app)
    headers = {"Marimo-Server-Token": str(_session_manager(app).skew_protection_token)}

    with TestClient(app) as client:
        original_generation = cast(
            str,
            client.get("/_marimo-studio/views").json()["generation"],
        )
        first = _create_owned_view(
            client,
            "operations",
            headers,
            original_generation,
        )
        stale = _create_owned_view(
            client,
            "analysis",
            headers,
            original_generation,
        )
        current_generation = cast(
            str,
            client.get("/_marimo-studio/views").json()["generation"],
        )
        current = _create_owned_view(
            client,
            "analysis",
            headers,
            current_generation,
        )

    assert first.status_code == 201
    assert current_generation != original_generation
    assert stale.status_code == 409
    assert stale.json() == {
        "error": "workspace-generation-conflict",
        "message": "The Studio workspace was replaced before the operation.",
        "hint": "Open the workspace again before retrying the operation.",
        "transient": True,
    }
    assert current.status_code == 201
    assert (studio.view_root / "operations" / "view.toml").is_file()
    assert (studio.view_root / "analysis" / "view.toml").is_file()


def test_concurrent_view_posts_reject_a_manifestless_directory(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    studio = _configured(notebook_path)
    occupied = studio.view_root / "operations"
    occupied.mkdir()
    sentinel = occupied / "sentinel.bin"
    content = b"\x00preserve-http-manifestless-view\xff"
    sentinel.write_bytes(content)
    app = _marimo_app(studio.notebook)
    _edit_mode(app)
    headers = {"Marimo-Server-Token": str(_session_manager(app).skew_protection_token)}
    provider = provider_registry().get("marimo-studio/vanilla")
    monkeypatch.setattr(
        provider,
        "create",
        lambda *_args, **_kwargs: pytest.fail("manifestless view was created"),
    )

    with TestClient(app) as client:
        generation = cast(
            str,
            client.get("/_marimo-studio/views").json()["generation"],
        )

        def create():
            return _create_owned_view(client, "operations", headers, generation)

        with ThreadPoolExecutor(max_workers=2) as executor:
            responses = tuple(executor.map(lambda _index: create(), range(2)))

    assert [response.status_code for response in responses] == [409, 409]
    assert all(response.json()["error"] == "view-exists" for response in responses)
    assert all(
        "required view.toml" in response.json()["message"] for response in responses
    )
    assert sentinel.read_bytes() == content
    assert tuple(path.name for path in occupied.iterdir()) == ("sentinel.bin",)


def test_project_and_source_reads_share_one_current_provider_catalog(
    notebook_path: Path,
) -> None:
    studio = _configured(notebook_path)
    view = studio.views["dashboard"]
    alternate = view.root / "alternate.html"
    alternate.write_text(
        (view.root / "index.html").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    app = _marimo_app(studio.notebook)
    _edit_mode(app)
    token = str(_session_manager(app).skew_protection_token)

    with TestClient(app) as client:
        project = client.get("/_marimo-studio/views/dashboard/project")
        owner_headers = {
            "Marimo-Studio-Catalog-Generation": project.json()["catalog_generation"],
            "Marimo-Studio-View-Generation": project.json()["view_generation"],
        }
        documents = [
            client.get(f"/_marimo-studio/views/dashboard/source/{path}")
            for path in ("index.html", "view.toml")
        ]

        saved = client.put(
            "/_marimo-studio/views/dashboard/source/index.html",
            content=documents[0].text + "\n",
            headers={
                "If-Match": documents[0].headers["etag"],
                **owner_headers,
                "Marimo-Server-Token": token,
            },
        )
        refreshed = client.get("/_marimo-studio/views/dashboard/source/index.html")

        manifest = view.manifest
        manifest.write_text(
            manifest.read_text(encoding="utf-8")
            + '\n[options]\nentrypoint = "alternate.html"\n',
            encoding="utf-8",
        )
        removed = client.get("/_marimo-studio/views/dashboard/source/index.html")
        selected = client.get("/_marimo-studio/views/dashboard/source/alternate.html")

    assert project.status_code == 200
    project_payload = project.json()
    assert "view.toml" not in {
        document["path"] for document in project_payload["documents"]
    }
    assert set(project_payload["artifact"]) == {"profile", "input_id", "artifact_id"}
    assert project_payload["artifact"]["profile"] == "development"
    assert all(response.status_code == 200 for response in documents)
    assert saved.status_code == 204
    assert refreshed.status_code == 200
    assert removed.status_code == 404
    assert selected.status_code == 200


def test_project_read_retries_transient_workspace_generations(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    studio = _configured(notebook_path)
    app = _marimo_app(studio.notebook)
    _edit_mode(app)
    load = studio_api_module.load_studio
    settle = studio_api_module.materialize_studio_workspace_after_conflict
    attempts = 0
    settled = 0

    def transient_load(target: str | Path):
        nonlocal attempts
        attempts += 1
        if attempts < 4:
            raise WorkspaceGenerationConflictError()
        return load(target)

    def settled_load(workspace):
        nonlocal settled
        settled += 1
        return settle(workspace)

    monkeypatch.setattr(studio_api_module, "load_studio", transient_load)
    monkeypatch.setattr(
        studio_api_module,
        "materialize_studio_workspace_after_conflict",
        settled_load,
    )

    with TestClient(app) as client:
        response = client.get("/_marimo-studio/views/dashboard/project")

    assert response.status_code == 200
    assert attempts == 1
    assert settled == 1


def test_source_put_rejects_a_same_content_recreated_view(
    notebook_path: Path,
) -> None:
    studio = _configured(notebook_path)
    prepare_view(studio.notebook, "operations")
    app = _marimo_app(studio.notebook)
    _edit_mode(app)
    headers = {"Marimo-Server-Token": str(_session_manager(app).skew_protection_token)}

    with TestClient(app) as client:
        original_project = client.get("/_marimo-studio/views/operations/project").json()
        original_source = client.get(
            "/_marimo-studio/views/operations/source/index.html"
        )
        root = studio.view_root / "operations"
        retired = root.with_name("retired-operations")
        root.rename(retired)
        shutil.copytree(retired, root)
        replacement_project = client.get(
            "/_marimo-studio/views/operations/project"
        ).json()
        replacement_source = client.get(
            "/_marimo-studio/views/operations/source/index.html"
        )
        stale = client.put(
            "/_marimo-studio/views/operations/source/index.html",
            content="stale replacement",
            headers={
                "If-Match": original_source.headers["etag"],
                "Marimo-Server-Token": headers["Marimo-Server-Token"],
                "Marimo-Studio-Catalog-Generation": replacement_project[
                    "catalog_generation"
                ],
                "Marimo-Studio-View-Generation": original_project["view_generation"],
            },
        )

    assert original_source.text == replacement_source.text
    assert original_source.headers["etag"] == replacement_source.headers["etag"]
    assert original_project["view_generation"] != replacement_project["view_generation"]
    assert stale.status_code == 409
    assert stale.json()["error"] == "view-generation-conflict"
    assert (studio.view_root / "operations" / "index.html").read_text(
        encoding="utf-8"
    ) == replacement_source.text


def test_project_endpoint_preserves_manifest_diagnostics_outside_editor_documents(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    studio = _configured(notebook_path)
    project = studio.view("dashboard")
    provider = provider_registry().get(project.provider)
    inspect = provider.inspect
    diagnostic = ProjectDiagnostic(
        "provider-options-invalid",
        "error",
        "The provider options are invalid.",
        "Repair view.toml.",
        SourceLocation(PurePosixPath("view.toml"), 1, 1),
    )

    monkeypatch.setattr(
        provider,
        "inspect",
        lambda request: replace(inspect(request), diagnostics=(diagnostic,)),
    )
    app = _marimo_app(studio.notebook)
    _edit_mode(app)

    with TestClient(app) as client:
        response = client.get("/_marimo-studio/views/dashboard/project")

    assert response.status_code == 200
    payload = response.json()
    assert "view.toml" not in {item["path"] for item in payload["documents"]}
    assert payload["diagnostics"][0]["source"]["path"] == "view.toml"
    assert payload["build"]["diagnostics"][0]["source"]["path"] == "view.toml"


def test_cold_server_lifecycle_repairs_a_malformed_manifest(
    notebook_path: Path,
) -> None:
    configured = _configured(notebook_path)
    owner_headers = {
        "Marimo-Studio-Catalog-Generation": configured.catalog_generation,
        "Marimo-Studio-View-Generation": configured.view_generations["dashboard"],
    }
    manifest = configured.views["dashboard"].manifest
    original = manifest.read_text(encoding="utf-8")
    manifest.write_text("schema = ", encoding="utf-8")
    del configured
    app = _marimo_app(notebook_path)
    _edit_mode(app)
    headers = {"Marimo-Server-Token": str(_session_manager(app).skew_protection_token)}

    with TestClient(app) as client:
        invalid_project = client.get("/_marimo-studio/views/dashboard/project")
        invalid_source = client.get("/_marimo-studio/views/dashboard/source/index.html")
        repair_source = client.get("/_marimo-studio/views/dashboard/source/view.toml")
        repair_owner_headers = {
            "Marimo-Studio-Catalog-Generation": repair_source.headers[
                "Marimo-Studio-Catalog-Generation"
            ],
            "Marimo-Studio-View-Generation": repair_source.headers[
                "Marimo-Studio-View-Generation"
            ],
        }
        rejected = client.put(
            "/_marimo-studio/views/dashboard/source/view.toml",
            content="schema = 2\n",
            headers={
                "If-Match": repair_source.headers["etag"],
                **repair_owner_headers,
                **headers,
            },
        )
        still_invalid = manifest.read_text(encoding="utf-8")
        repaired_write = client.put(
            "/_marimo-studio/views/dashboard/source/view.toml",
            content=original,
            headers={
                "If-Match": repair_source.headers["etag"],
                **repair_owner_headers,
                **headers,
            },
        )
        repaired = client.get("/_marimo-studio/views/dashboard/project")

    assert invalid_project.status_code == 500
    assert invalid_project.json()["error"] == "configuration-error"
    assert invalid_project.headers["Marimo-Studio-Error"] == "configuration-error"
    assert invalid_source.status_code == 500
    assert invalid_source.json()["error"] == "configuration-error"
    assert repair_source.status_code == 200
    assert repair_source.text == "schema = "
    assert (
        repair_owner_headers["Marimo-Studio-Catalog-Generation"]
        != owner_headers["Marimo-Studio-Catalog-Generation"]
    )
    assert (
        repair_owner_headers["Marimo-Studio-View-Generation"]
        == owner_headers["Marimo-Studio-View-Generation"]
    )
    assert rejected.status_code == 400
    assert rejected.json()["error"] == "invalid-source-content"
    assert still_invalid == "schema = "
    assert repaired_write.status_code == 204
    assert repaired.status_code == 200
