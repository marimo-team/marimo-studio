from __future__ import annotations

import threading
from collections.abc import AsyncGenerator, Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path
from typing import Any, cast

import pytest
from starlette.testclient import TestClient

import marimo_studio._server.studio.deletion as deletion_service
import marimo_studio._server.studio.routes as studio_api_module
import marimo_studio._views.remove as workspace_views
from marimo_studio._server.development.coordinator import (
    DevelopmentCoordinator,
)
from marimo_studio._server.notebook_scope import NotebookScope
from marimo_studio._server.presentation.service import NotebookPresentation
from marimo_studio._views.api import prepare_view
from marimo_studio._workspace import load_studio
from marimo_studio._workspace.models import StudioWorkspace
from marimo_studio.errors import ViewDeletionError

from ..app_helpers import configured as _configured
from ..app_helpers import edit_mode as _edit_mode
from ..app_helpers import marimo_app as _marimo_app
from ..app_helpers import session_manager as _session_manager
from ._view_mutation_test_support import _create_owned_view


def _view_owner(client: TestClient, name: str) -> tuple[str, str]:
    inventory = client.get("/_marimo-studio/views").json()
    view = next(item for item in inventory["views"] if item["name"] == name)
    return cast(str, inventory["generation"]), cast(str, view["generation"])


def _delete_owned_view(
    client: TestClient,
    name: str,
    headers: dict[str, str],
    owner: tuple[str, str] | None = None,
):
    catalog_generation, view_generation = owner or _view_owner(client, name)
    return client.request(
        "DELETE",
        f"/_marimo-studio/views/{name}",
        headers=headers,
        json={
            "catalog_generation": catalog_generation,
            "name": name,
            "view_generation": view_generation,
        },
    )


def test_view_deletion_removes_files_promotes_the_default_and_keeps_one_view(
    notebook_path: Path,
) -> None:
    studio = _configured(notebook_path)
    prepare_view(studio.notebook, "operations")
    asset = studio.view_root / "operations" / "assets" / "note.txt"
    asset.parent.mkdir(parents=True)
    asset.write_text("authored view asset", encoding="utf-8")
    app = _marimo_app(studio.notebook)
    _edit_mode(app)
    headers = {"Marimo-Server-Token": str(_session_manager(app).skew_protection_token)}

    with TestClient(app) as client:
        removed = _delete_owned_view(client, "operations", headers)
        promoted = _delete_owned_view(client, "dashboard", headers)
        last = _delete_owned_view(client, "executive", headers)
        views = client.get("/_marimo-studio/views").json()

    assert removed.status_code == 200, removed.text
    removed_payload = removed.json()
    assert removed_payload["schema"] == 1
    assert removed_payload["name"] == "operations"
    assert removed_payload["default_view"] == "dashboard"
    assert [item["name"] for item in removed_payload["views"]] == [
        "dashboard",
        "executive",
    ]
    assert not (studio.view_root / "operations").exists()
    assert promoted.status_code == 200
    assert promoted.json()["default_view"] == "executive"
    updated = load_studio(studio.notebook)
    assert views["schema"] == 1
    assert views["default_view"] == "executive"
    assert [item["name"] for item in views["views"]] == ["executive"]
    assert updated.default_view == "executive"
    assert not (studio.view_root / "dashboard").exists()
    assert last.status_code == 409
    assert last.json() == {
        "error": "last-view",
        "message": "Keep at least one view.",
    }
    assert (studio.views["executive"].root / "index.html").is_file()


def test_view_deletion_rejects_a_recreated_view_until_its_owner_is_refreshed(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    studio = _configured(notebook_path)
    prepare_view(studio.notebook, "operations")
    development_deletions: list[str] = []
    presentation_deletions: list[str] = []
    development_deleting_view = DevelopmentCoordinator.deleting_view
    presentation_deleting_view = NotebookPresentation.deleting_view

    @asynccontextmanager
    async def track_development_deletion(
        coordinator: DevelopmentCoordinator,
        view_name: str,
    ) -> AsyncGenerator[Any, None]:
        development_deletions.append(view_name)
        async with development_deleting_view(coordinator, view_name) as deletion:
            yield deletion

    @contextmanager
    def track_presentation_deletion(
        presentation: NotebookPresentation,
        view_name: str,
    ) -> Iterator[None]:
        presentation_deletions.append(view_name)
        with presentation_deleting_view(presentation, view_name):
            yield

    monkeypatch.setattr(
        DevelopmentCoordinator,
        "deleting_view",
        track_development_deletion,
    )
    monkeypatch.setattr(
        NotebookPresentation,
        "deleting_view",
        track_presentation_deletion,
    )
    app = _marimo_app(studio.notebook)
    _edit_mode(app)
    headers = {"Marimo-Server-Token": str(_session_manager(app).skew_protection_token)}

    with TestClient(app) as client:
        original_owner = _view_owner(client, "operations")
        original = _delete_owned_view(client, "operations", headers, original_owner)
        recreated = _create_owned_view(client, "operations", headers)
        replacement_owner = _view_owner(client, "operations")
        development_deletions.clear()
        presentation_deletions.clear()
        stale_catalog = _delete_owned_view(
            client,
            "operations",
            headers,
            original_owner,
        )
        stale_view = _delete_owned_view(
            client,
            "operations",
            headers,
            (replacement_owner[0], original_owner[1]),
        )
        assert development_deletions == []
        assert presentation_deletions == []
        current = _delete_owned_view(client, "operations", headers, replacement_owner)

    assert original.status_code == 200
    assert recreated.status_code == 201
    assert replacement_owner != original_owner
    assert stale_catalog.status_code == 409
    assert stale_catalog.json()["error"] == "workspace-generation-conflict"
    assert stale_view.status_code == 409
    assert stale_view.json() == {
        "error": "view-generation-conflict",
        "message": "View 'operations' was replaced before the operation.",
        "view": "operations",
        "current_generation": replacement_owner[1],
        "hint": "Reopen the workspace and reacquire the view before retrying.",
        "transient": True,
    }
    assert current.status_code == 200
    assert development_deletions == ["operations"]
    assert presentation_deletions == ["operations"]
    assert not (studio.view_root / "operations").exists()


def test_view_deletion_resolves_provider_starters_off_the_event_loop(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    studio = _configured(notebook_path)
    prepare_view(studio.notebook, "operations")
    app = _marimo_app(studio.notebook)
    _edit_mode(app)
    headers = {"Marimo-Server-Token": str(_session_manager(app).skew_protection_token)}
    current = load_studio(studio.notebook)
    owner = (current.catalog_generation, current.view_generations["operations"])
    installed_starters = studio_api_module.starters
    started = threading.Event()
    release = threading.Event()

    def blocking_starters(*args: Any, **kwargs: Any) -> Any:
        started.set()
        assert release.wait(timeout=2)
        return installed_starters(*args, **kwargs)

    monkeypatch.setattr(studio_api_module, "starters", blocking_starters)

    with TestClient(app) as client, ThreadPoolExecutor(max_workers=2) as executor:
        deletion = executor.submit(
            _delete_owned_view,
            client,
            "operations",
            headers,
            owner,
        )
        assert started.wait(timeout=2)
        health = executor.submit(client.get, "/health")
        try:
            assert health.result(timeout=1).status_code == 200
        finally:
            release.set()
    assert deletion.result(timeout=2).status_code == 200


def test_view_deletion_capacity_returns_a_retryable_response(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    studio = _configured(notebook_path)
    prepare_view(studio.notebook, "operations")
    app = _marimo_app(studio.notebook)
    _edit_mode(app)
    headers = {"Marimo-Server-Token": str(_session_manager(app).skew_protection_token)}
    slots = threading.BoundedSemaphore(1)
    assert slots.acquire(blocking=False)
    monkeypatch.setattr(deletion_service, "_DELETION_SLOTS", slots)

    try:
        with TestClient(app) as client:
            response = _delete_owned_view(client, "operations", headers)
    finally:
        slots.release()

    assert response.status_code == 503
    assert response.json() == {
        "error": "view-deletion-capacity-exhausted",
        "message": (
            "Studio is already processing the maximum number of view deletions."
        ),
        "hint": "Retry after an in-flight view deletion finishes.",
        "transient": True,
    }
    assert studio.view_root.joinpath("operations", "view.toml").is_file()


def test_committed_view_deletion_reports_incomplete_cleanup_as_success(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    studio = _configured(notebook_path)
    prepare_view(studio.notebook, "operations")
    app = _marimo_app(studio.notebook)
    _edit_mode(app)
    headers = {"Marimo-Server-Token": str(_session_manager(app).skew_protection_token)}
    delete = deletion_service.delete_view
    cleanup = tmp_path / "preserved-cleanup"

    def delete_with_cleanup_warning(
        workspace: StudioWorkspace,
        view_name: str,
        *,
        expected_catalog_generation: str,
        expected_generation: str,
    ) -> StudioWorkspace:
        updated = delete(
            workspace,
            view_name,
            expected_catalog_generation=expected_catalog_generation,
            expected_generation=expected_generation,
        )
        raise ViewDeletionError(cleanup, committed_workspace=updated)

    monkeypatch.setattr(
        deletion_service,
        "delete_view",
        delete_with_cleanup_warning,
    )

    with TestClient(app) as client:
        response = _delete_owned_view(client, "operations", headers)

    assert response.status_code == 200
    assert response.json()["cleanup"] == str(cleanup)
    assert response.json()["name"] == "operations"
    assert [view["name"] for view in response.json()["views"]] == [
        "dashboard",
        "executive",
    ]
    assert not (studio.view_root / "operations").exists()


def test_view_deletion_releases_retained_artifacts_before_windows_cleanup(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    studio = _configured(notebook_path)
    prepare_view(studio.notebook, "operations")
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
    app = _marimo_app(studio.notebook)
    _edit_mode(app)
    headers = {"Marimo-Server-Token": str(_session_manager(app).skew_protection_token)}
    remove_tree = workspace_views.SecureDirectory.remove_tree

    def reject_retained_handles(
        filesystem: workspace_views.SecureDirectory,
        path: Path,
    ) -> None:
        pins = tuple(path.glob("**/.artifacts/.pins/*/*"))
        if pins:
            raise PermissionError(f"retained artifact handle: {pins[0]}")
        remove_tree(filesystem, path)

    with TestClient(app) as client:
        owner = _view_owner(client, "operations")
        assert len(scopes) == 1
        scopes[0].presentation.snapshot("operations")
        retained_pins = tuple(
            (studio.view_root / "operations").glob(".artifacts/.pins/*/*")
        )
        monkeypatch.setattr(
            workspace_views.SecureDirectory,
            "remove_tree",
            reject_retained_handles,
        )
        removed = _delete_owned_view(client, "operations", headers, owner)

    assert retained_pins
    assert removed.status_code == 200
    assert not (studio.view_root / "operations").exists()


def test_project_and_source_reads_report_transient_deletion(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    studio = _configured(notebook_path)
    prepare_view(studio.notebook, "operations")
    app = _marimo_app(studio.notebook)
    _edit_mode(app)
    headers = {"Marimo-Server-Token": str(_session_manager(app).skew_protection_token)}
    remove = deletion_service.delete_view
    deletion_started = threading.Event()
    release_deletion = threading.Event()

    def block_deletion(
        workspace: StudioWorkspace,
        view_name: str,
        *,
        expected_catalog_generation: str,
        expected_generation: str,
    ) -> StudioWorkspace:
        deletion_started.set()
        if not release_deletion.wait(timeout=2):
            raise RuntimeError("view deletion was not released")
        return remove(
            workspace,
            view_name,
            expected_catalog_generation=expected_catalog_generation,
            expected_generation=expected_generation,
        )

    monkeypatch.setattr(deletion_service, "delete_view", block_deletion)

    with TestClient(app) as client, ThreadPoolExecutor(max_workers=1) as executor:
        owner = _view_owner(client, "operations")
        pending = executor.submit(
            _delete_owned_view,
            client,
            "operations",
            headers,
            owner,
        )
        assert deletion_started.wait(timeout=2)
        try:
            project = client.get("/_marimo-studio/views/operations/project")
            source = client.get("/_marimo-studio/views/operations/source/index.html")
        finally:
            release_deletion.set()
        removed = pending.result(timeout=2)

    expected = {
        "error": "view-deletion-in-progress",
        "message": "View 'operations' is being deleted.",
        "view": "operations",
        "transient": True,
    }
    assert project.status_code == 409
    assert project.json() == expected
    assert source.status_code == 409
    assert source.json() == expected
    assert removed.status_code == 200


def test_view_deletion_cancels_build_before_off_thread_filesystem_cleanup(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    studio = _configured(notebook_path)
    prepare_view(studio.notebook, "operations")
    app = _marimo_app(studio.notebook)
    _edit_mode(app)
    headers = {"Marimo-Server-Token": str(_session_manager(app).skew_protection_token)}
    events: list[tuple[str, int]] = []
    remove = deletion_service.delete_view

    @asynccontextmanager
    async def deleting_view(
        _coordinator: object,
        view_name: str,
    ) -> AsyncGenerator[None, None]:
        assert view_name == "operations"
        events.append(("guard-enter", threading.get_ident()))
        try:
            yield
        finally:
            events.append(("guard-exit", threading.get_ident()))

    def remove_off_thread(
        workspace: StudioWorkspace,
        view_name: str,
        *,
        expected_catalog_generation: str,
        expected_generation: str,
    ) -> StudioWorkspace:
        events.append(("delete", threading.get_ident()))
        return remove(
            workspace,
            view_name,
            expected_catalog_generation=expected_catalog_generation,
            expected_generation=expected_generation,
        )

    monkeypatch.setattr(DevelopmentCoordinator, "deleting_view", deleting_view)
    monkeypatch.setattr(deletion_service, "delete_view", remove_off_thread)

    with TestClient(app) as client:
        removed = _delete_owned_view(client, "operations", headers)

    assert removed.status_code == 200
    assert [name for name, _thread in events] == [
        "guard-enter",
        "delete",
        "guard-exit",
    ]
    assert events[0][1] != events[1][1]
    assert events[0][1] == events[2][1]
