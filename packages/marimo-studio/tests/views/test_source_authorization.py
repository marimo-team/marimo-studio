"""Source authorization races through the public Studio HTTP boundary."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import AbstractContextManager, contextmanager
from dataclasses import replace
from pathlib import Path, PurePosixPath
from threading import Barrier

import pytest
from starlette.testclient import TestClient

import marimo_studio._server.studio.routes as studio_routes
import marimo_studio._views.sources as sources_module
from marimo_studio._artifacts.inputs import ProjectInputState
from marimo_studio._filesystem.secure import SecureDirectory
from marimo_studio._views.api import ensure_view
from marimo_studio._views.records import ViewDocument
from marimo_studio._workspace import load_studio
from marimo_studio._workspace.models import StudioWorkspace
from marimo_studio.view_providers import (
    BuildRequest,
    BuildResult,
    InspectionRequest,
    ProjectInput,
    ProjectInspection,
    ProviderAvailability,
    ProviderInfo,
    ProviderStarter,
    SourceDocument,
    StarterContext,
    ViewProject,
)
from marimo_studio.view_providers._bundled.vanilla import provider as vanilla_provider
from marimo_studio.view_providers._host.identity import starter_id
from marimo_studio.view_providers._host.registry import ProviderRegistry

from ..app_helpers import edit_mode, marimo_app, session_manager
from ..provider_test_support import candidate, install_registry

_POLICY = PurePosixPath("source-access.txt")
_SOURCE = PurePosixPath("index.html")
_SourceLock = Callable[[Path, str], AbstractContextManager[None]]


class _InputAccessProvider:
    """Expose source access from a separate declared provider input."""

    info: ProviderInfo = vanilla_provider.info
    starter: ProviderStarter = replace(
        vanilla_provider.starters()[0],
        key="source-policy",
    )

    def availability(self, project: ViewProject | None = None) -> ProviderAvailability:
        del project
        return ProviderAvailability(True)

    def starters(self) -> tuple[ProviderStarter, ...]:
        return (self.starter,)

    def create(
        self,
        starter: ProviderStarter,
        context: StarterContext,
    ) -> dict[PurePosixPath, bytes]:
        files = vanilla_provider.create(
            vanilla_provider.starters()[0],
            context,
        )
        return {**files, _POLICY: b"edit\n"}

    def inspect(self, request: InspectionRequest) -> ProjectInspection:
        project = request.project
        inspection = vanilla_provider.inspect(request)
        access = (
            project.root.joinpath(*_POLICY.parts).read_text(encoding="utf-8").strip()
        )
        if access not in {"edit", "read"}:
            raise ValueError("source-access.txt must contain edit or read")
        documents = tuple(
            replace(item, access=access) if item.path == _SOURCE else item
            for item in inspection.editor_documents
        )
        return replace(
            inspection,
            editor_documents=documents,
            input_scope=(*inspection.input_scope, ProjectInput(_POLICY, "file")),
            build_fingerprint=f"{inspection.build_fingerprint}:source-policy-v1",
        )

    def build(self, request: BuildRequest) -> BuildResult:
        return vanilla_provider.build(request)


def _source_headers(app: object) -> dict[str, str]:
    return {"Marimo-Server-Token": str(session_manager(app).skew_protection_token)}


def _pause_source_lock(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[_SourceLock, Barrier]:
    original = sources_module.view_mutation_lock
    waiting = Barrier(2)

    @contextmanager
    def observed(view_root: Path, view_name: str) -> Iterator[None]:
        waiting.wait(timeout=5)
        with original(view_root, view_name):
            yield

    monkeypatch.setattr(sources_module, "view_mutation_lock", observed)
    return original, waiting


def test_waiting_put_revalidates_access_from_another_provider_input(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _InputAccessProvider()
    registry = ProviderRegistry((candidate("source-policy", provider),))
    install_registry(monkeypatch, registry)
    ensure_view(
        notebook_path,
        starter=starter_id(registry.ids[0], provider.starter.key),
    )
    studio = load_studio(notebook_path)
    project = studio.views["dashboard"]
    source = project.root.joinpath(*_SOURCE.parts)
    policy = project.root.joinpath(*_POLICY.parts)
    original_content = source.read_text(encoding="utf-8")
    app = marimo_app(notebook_path)
    edit_mode(app)

    with TestClient(app) as client, ThreadPoolExecutor(max_workers=1) as executor:
        loaded = client.get("/_marimo-studio/views/dashboard/source/index.html")
        assert loaded.status_code == 200
        original_lock, waiting = _pause_source_lock(monkeypatch)
        with original_lock(studio.view_root, project.name):
            pending = executor.submit(
                client.put,
                "/_marimo-studio/views/dashboard/source/index.html",
                content=f"{original_content}\n",
                headers={
                    **_source_headers(app),
                    "If-Match": loaded.headers["etag"],
                },
            )
            waiting.wait(timeout=5)
            policy.write_text("read\n", encoding="utf-8")
        response = pending.result(timeout=5)

    assert response.status_code == 412
    assert response.json()["error"] == "source-conflict"
    assert source.read_text(encoding="utf-8") == original_content


def test_policy_change_after_target_replacement_rolls_back_the_source(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _InputAccessProvider()
    registry = ProviderRegistry((candidate("source-policy", provider),))
    install_registry(monkeypatch, registry)
    ensure_view(
        notebook_path,
        starter=starter_id(registry.ids[0], provider.starter.key),
    )
    studio = load_studio(notebook_path)
    project = studio.views["dashboard"]
    source = project.root.joinpath(*_SOURCE.parts)
    policy = project.root.joinpath(*_POLICY.parts)
    original_content = source.read_text(encoding="utf-8")
    app = marimo_app(notebook_path)
    edit_mode(app)
    replacement_committed = Barrier(2)
    release_validation = Barrier(2)
    state_calls = 0
    input_state = sources_module.project_input_state

    def pause_final_validation(
        selected: ViewProject,
        inspection: ProjectInspection,
        *,
        files: SecureDirectory | None = None,
    ) -> ProjectInputState:
        nonlocal state_calls
        state_calls += 1
        if state_calls == 2:
            replacement_committed.wait(timeout=5)
            release_validation.wait(timeout=5)
        return input_state(selected, inspection, files=files)

    monkeypatch.setattr(sources_module, "project_input_state", pause_final_validation)

    with TestClient(app) as client, ThreadPoolExecutor(max_workers=1) as executor:
        loaded = client.get("/_marimo-studio/views/dashboard/source/index.html")
        assert loaded.status_code == 200
        pending = executor.submit(
            client.put,
            "/_marimo-studio/views/dashboard/source/index.html",
            content=f"{original_content}\n",
            headers={
                **_source_headers(app),
                "If-Match": loaded.headers["etag"],
            },
        )
        replacement_committed.wait(timeout=5)
        policy.write_text("read\n", encoding="utf-8")
        release_validation.wait(timeout=5)
        response = pending.result(timeout=5)

    assert response.status_code == 412
    assert response.json()["error"] == "source-conflict"
    assert source.read_text(encoding="utf-8") == original_content


def test_source_get_retries_when_the_provider_catalog_changes_after_read(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _InputAccessProvider()
    registry = ProviderRegistry((candidate("source-policy", provider),))
    install_registry(monkeypatch, registry)
    ensure_view(
        notebook_path,
        starter=starter_id(registry.ids[0], provider.starter.key),
    )
    studio = load_studio(notebook_path)
    project = studio.views["dashboard"]
    policy = project.root.joinpath(*_POLICY.parts)
    app = marimo_app(notebook_path)
    edit_mode(app)
    first_read = Barrier(2)
    release_read = Barrier(2)
    accesses: list[str] = []
    read_project_source = studio_routes.read_project_source

    def observed_read(
        selected_studio: StudioWorkspace,
        selected_project: ViewProject,
        spec: SourceDocument,
    ) -> ViewDocument:
        document = read_project_source(selected_studio, selected_project, spec)
        accesses.append(document.access)
        if len(accesses) == 1:
            first_read.wait(timeout=5)
            release_read.wait(timeout=5)
        return document

    monkeypatch.setattr(studio_routes, "read_project_source", observed_read)

    with TestClient(app) as client, ThreadPoolExecutor(max_workers=1) as executor:
        pending = executor.submit(
            client.get,
            "/_marimo-studio/views/dashboard/source/index.html",
        )
        first_read.wait(timeout=5)
        policy.write_text("read\n", encoding="utf-8")
        release_read.wait(timeout=5)
        response = pending.result(timeout=5)

    assert response.status_code == 200
    assert accesses == ["edit", "read"]
