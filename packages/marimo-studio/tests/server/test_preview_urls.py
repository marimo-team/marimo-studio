from __future__ import annotations

from collections.abc import MutableMapping
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit

import pytest
from marimo._server.workspace._directory import DirectoryWorkspace
from starlette.applications import Starlette
from starlette.routing import Mount
from starlette.testclient import TestClient

from marimo_studio._artifacts.lock import build_lock
from marimo_studio._artifacts.publication import record_build_started
from marimo_studio._views.api import prepare_view
from marimo_studio._views.build import build_view_project_sync
from marimo_studio._views.revisions import capture_source_snapshot
from marimo_studio._workspace import load_studio
from marimo_studio._workspace.metadata import update_notebook_config
from marimo_studio.errors import ViewProjectError

from ..app_helpers import configured, edit_mode, marimo_app, session_manager
from .app_test_support import _editor_mount_value, _view_support_url

ENDPOINT = "/_marimo-studio/views/dashboard/preview"
REVISION = "marimo_studio_revision"


def _enable_wasm(notebook: Path) -> None:
    def configure(config: MutableMapping[str, object]) -> None:
        config["runtimes"] = ["server", "wasm"]

    update_notebook_config(notebook, configure)


def test_preview_rejects_a_different_notebook_owner(notebook_path: Path) -> None:
    selected = configured(notebook_path)
    other = notebook_path.with_name("other.py")
    other.write_bytes(notebook_path.read_bytes())
    configured(other)
    app = marimo_app(other)
    edit_mode(app)
    with TestClient(app) as client:
        response = client.get(
            ENDPOINT,
            params={
                "runtime": "server",
                "catalog_generation": selected.catalog_generation,
                "view_generation": selected.view_generations["dashboard"],
            },
        )
    assert response.status_code == 409
    assert response.json()["error"] == "view-generation-conflict"


def test_wasm_preview_opens_without_an_editor_or_browser_client(
    notebook_path: Path,
) -> None:
    configured(notebook_path)
    _enable_wasm(notebook_path)
    app = marimo_app(notebook_path)
    edit_mode(app)
    with TestClient(app) as client:
        response = client.get(ENDPOINT, params={"runtime": "wasm"})
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/plain")
        assert "no-store" in response.headers["cache-control"]
        document = client.get(response.text)
        server = client.get(ENDPOINT, params={"runtime": "server"})
        waiting = client.get(server.text)
    assert document.status_code == 200
    assert "<marimo-cell" in document.text
    assert 'id="marimo-studio-presentation"' not in document.text
    assert _editor_mount_value(document.text, "runtime") == "wasm"
    policy = document.headers["content-security-policy"]
    assert policy.startswith("sandbox ")
    assert "allow-same-origin" not in policy
    assert waiting.status_code == 202
    assert waiting.headers["retry-after"] == "1"


def test_preview_preserves_mounted_directory_notebook_routing(
    notebook_path: Path,
) -> None:
    configured(notebook_path)
    _enable_wasm(notebook_path)
    child = marimo_app(notebook_path, path="/base", programmatic=True)
    edit_mode(child)
    session_manager(child).workspace = DirectoryWorkspace(
        str(notebook_path.parent), include_markdown=False
    )
    app = Starlette(routes=[Mount("/parent", app=child)])
    with TestClient(app) as client:
        response = client.get(
            f"/parent/base{ENDPOINT}",
            params={"file": notebook_path.name, "runtime": "wasm"},
        )
        assert response.status_code == 200
        parts = urlsplit(response.text)
        assert parts.path == "/parent/base/dashboard/"
        assert parse_qs(parts.query) == {
            "file": [notebook_path.name],
            "runtime": ["wasm"],
            "marimo_studio_unframed": ["1"],
        }
        document = client.get(response.text)
    assert document.status_code == 200
    assert _editor_mount_value(document.text, "runtime") == "wasm"


def test_preview_requires_normal_notebook_authentication(notebook_path: Path) -> None:
    configured(notebook_path)
    app = marimo_app(notebook_path, token="secret", skew_protection=True)
    edit_mode(app)
    with TestClient(app) as client:
        missing = client.get(
            ENDPOINT,
            params={"runtime": "server"},
            headers={"Accept": "application/json"},
            follow_redirects=False,
        )
        authenticated = client.get(
            ENDPOINT,
            params={"runtime": "server"},
            headers={"Authorization": "Bearer secret"},
        )
        client.cookies.clear()
        browser_without_login = client.get(
            authenticated.text,
            headers={"Accept": "text/html"},
            follow_redirects=False,
        )
    assert missing.status_code == 401
    assert authenticated.status_code == 200
    assert browser_without_login.status_code == 303
    assert browser_without_login.headers["location"].startswith("/auth/login")
    assert "secret" not in authenticated.text


@pytest.mark.parametrize("mode", ["edit", "run"])
def test_exact_preview_opens_its_current_published_revision(
    notebook_path: Path, mode: str
) -> None:
    configured(notebook_path)
    _enable_wasm(notebook_path)
    studio = load_studio(notebook_path)
    profile = "development" if mode == "edit" else "production"
    with build_view_project_sync(studio.views["dashboard"], profile=profile):
        pass
    app = marimo_app(notebook_path)
    if mode == "edit":
        edit_mode(app)
    with TestClient(app) as client:
        resolved = client.get(ENDPOINT, params={"runtime": "wasm", "exact": "1"})
        assert resolved.status_code == 200, resolved.text
        revision = parse_qs(urlsplit(resolved.text).query)[REVISION][0]
        document = client.get(resolved.text)
        mismatch = client.get(
            "/dashboard/?" + urlencode({"runtime": "wasm", REVISION: "0" * 64}),
        )
    assert document.status_code == 200
    assert document.headers["Marimo-Studio-Revision"] == revision
    assert mismatch.status_code == 409
    assert "exact preview is stale" in mismatch.text


@pytest.mark.parametrize("source_changed", [False, True])
def test_exact_preview_only_reads_matching_publication_during_an_active_build(
    notebook_path: Path,
    source_changed: bool,
) -> None:
    configured(notebook_path)
    _enable_wasm(notebook_path)
    studio = load_studio(notebook_path)
    project = studio.views["dashboard"]
    with build_view_project_sync(project):
        pass
    if source_changed:
        document = project.root / "index.html"
        document.write_text(
            document.read_text(encoding="utf-8") + "<!-- changed -->", encoding="utf-8"
        )
    project_revision = (
        capture_source_snapshot(studio, ("dashboard",)).projects["dashboard"].input_id
    )
    app = marimo_app(notebook_path)
    edit_mode(app)
    with TestClient(app) as client, build_lock(project) as acquired:
        assert acquired
        record_build_started(project, "development", project_revision, None)
        resolved = client.get(ENDPOINT, params={"runtime": "wasm", "exact": "1"})
        if source_changed:
            assert resolved.status_code == 409
            assert resolved.json()["error"] == "preview-source-not-current"
            return
        assert resolved.status_code == 200, resolved.text
        document = client.get(resolved.text)
        assert document.status_code == 200, document.text
        assert (
            document.headers["Marimo-Studio-Revision"]
            == parse_qs(urlsplit(resolved.text).query)[REVISION][0]
        )


def test_exact_url_rejects_a_new_published_presentation(notebook_path: Path) -> None:
    configured(notebook_path)
    _enable_wasm(notebook_path)
    studio = load_studio(notebook_path)
    project = studio.views["dashboard"]
    with build_view_project_sync(project):
        pass
    app = marimo_app(notebook_path)
    edit_mode(app)
    with TestClient(app) as client:
        first = client.get(ENDPOINT, params={"runtime": "wasm", "exact": "1"})
        assert first.status_code == 200
        assert client.get(first.text).status_code == 200
        source = project.root / "index.html"
        source.write_text(source.read_text() + "\n<!-- next publication -->\n")
        with build_view_project_sync(project):
            pass
        second = client.get(ENDPOINT, params={"runtime": "wasm", "exact": "1"})
        assert second.status_code == 200, second.text
        assert second.text != first.text
        stale = client.get(first.text)
        current = client.get(second.text)
    assert stale.status_code == 409
    assert current.status_code == 200
    assert (
        current.headers["Marimo-Studio-Revision"]
        == parse_qs(urlsplit(second.text).query)[REVISION][0]
    )


@pytest.mark.parametrize("state", ["unbuilt", "source-changed", "wrong-profile"])
def test_exact_preview_refuses_unpublished_source_without_building(
    notebook_path: Path, state: str
) -> None:
    prepare_view(notebook_path)
    studio = load_studio(notebook_path)
    project = studio.views["dashboard"]
    if state != "unbuilt":
        profile = "production" if state == "wrong-profile" else "development"
        with build_view_project_sync(project, profile=profile):
            pass
    if state == "source-changed":
        source = project.root / "index.html"
        source.write_text(source.read_text() + "\n<!-- changed -->\n")
    before = {
        p.relative_to(project.root): p.read_bytes()
        for p in project.root.rglob("*")
        if p.is_file()
    }
    app = marimo_app(notebook_path)
    edit_mode(app)
    with TestClient(app) as client:
        response = client.get(ENDPOINT, params={"runtime": "server", "exact": "1"})
    assert response.status_code == 409
    assert response.json()["error"] == "preview-source-not-current"
    after = {
        p.relative_to(project.root): p.read_bytes()
        for p in project.root.rglob("*")
        if p.is_file()
    }
    assert after == before


@pytest.mark.parametrize(
    "query",
    [
        "runtime=server&runtime=wasm",
        "runtime=server&exact=1&exact=0",
        "runtime=server&exact=yes",
        "runtime=server&catalog_generation=" + "0" * 64,
        "exact=1",
    ],
)
def test_preview_rejects_ambiguous_requests(notebook_path: Path, query: str) -> None:
    configured(notebook_path)
    app = marimo_app(notebook_path)
    edit_mode(app)
    with TestClient(app) as client:
        response = client.get(f"{ENDPOINT}?{query}")
    assert response.status_code == 400
    assert response.json()["error"] == "invalid-preview-request"


@pytest.mark.parametrize(
    "constraint",
    ["", "abc", "A" * 64, "0" * 65, "0" * 64 + "&" + REVISION + "=" + "1" * 64],
)
def test_exact_document_rejects_invalid_revision_constraints(
    notebook_path: Path, constraint: str
) -> None:
    configured(notebook_path)
    with TestClient(marimo_app(notebook_path)) as client:
        response = client.get(f"/dashboard/?{REVISION}={constraint}")
    assert response.status_code == 400
    assert "Specify one presentation revision" in response.text


def test_preview_reports_unavailable_runtime_and_expired_session(
    notebook_path: Path,
) -> None:
    configured(notebook_path)
    app = marimo_app(notebook_path)
    edit_mode(app)
    with TestClient(app) as client:
        unavailable = client.get(ENDPOINT, params={"runtime": "not-installed"})
        expired = client.get(
            ENDPOINT,
            params={"runtime": "server"},
            headers={"Marimo-Session-Id": "s_expired"},
        )
    assert unavailable.status_code == 400
    assert "not-installed" in unavailable.text
    assert expired.status_code == 409
    assert expired.json()["error"] == "preview-session-unavailable"


def test_session_bound_preview_retains_and_revalidates_its_editor(
    notebook_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from marimo_studio._compat.server.session_state import PrivateSessionState
    from marimo_studio._delivery.urls import (
        EDITOR_SESSION_QUERY_PARAM,
        STUDIO_CLIENT_QUERY_PARAM,
    )
    from marimo_studio._server.agent.clients import StudioClientRegistry
    from marimo_studio._server.agent.session_bindings import ClientBinding

    configured(notebook_path)
    app = marimo_app(notebook_path)
    edit_mode(app)
    client_id = "browser-client-1234"
    session = "s_123456"
    current_session = session

    monkeypatch.setattr(PrivateSessionState, "exists", lambda *_args: True)
    monkeypatch.setattr(
        PrivateSessionState, "has_notebook_session", lambda *_args: True
    )
    monkeypatch.setattr(PrivateSessionState, "ensure_started", lambda *_args: True)

    async def binding(_registry, session_id):
        return ClientBinding(client_id, session_id, True)

    async def session_for_client(_registry, selected):
        assert selected == client_id
        return current_session

    monkeypatch.setattr(StudioClientRegistry, "binding_for_session", binding)
    monkeypatch.setattr(StudioClientRegistry, "session_for_client", session_for_client)

    async def live_cells(*_args, **_kwargs):
        return None

    monkeypatch.setattr(PrivateSessionState, "live_cells", live_cells)
    monkeypatch.setattr(
        "marimo_studio._compat.server.existing_session.PrivateExistingSessionAttachment.attach",
        lambda *_args: True,
    )
    with TestClient(app) as client:
        resolved = client.get(
            ENDPOINT,
            params={"runtime": "server"},
            headers={"Marimo-Session-Id": session},
        )
        assert resolved.status_code == 200
        query = parse_qs(urlsplit(resolved.text).query)
        assert query[STUDIO_CLIENT_QUERY_PARAM] == [client_id]
        assert query[EDITOR_SESSION_QUERY_PARAM] == [session]
        document = client.get(resolved.text)
        assert document.status_code == 200
        assert _editor_mount_value(document.text, "clientId") == client_id
        support = _editor_mount_value(document.text, "supportUrl")
        assert parse_qs(urlsplit(support).query)[EDITOR_SESSION_QUERY_PARAM] == [
            session
        ]
        header_support = document.headers["Marimo-Studio-Support-Url"]
        assert parse_qs(urlsplit(header_support).query)[EDITOR_SESSION_QUERY_PARAM] == [
            session
        ]
        config_url = _view_support_url({"supportUrl": header_support}, "config")
        config_url += "&" + urlencode(
            {"runtime": "server", STUDIO_CLIENT_QUERY_PARAM: client_id}
        )
        headers = {
            "Marimo-Studio-Preview-Session-Id": _editor_mount_value(
                document.text, "sessionId"
            )
        }
        config = client.get(config_url, headers=headers)
        assert config.status_code == 200, config.text
        next_support = config.json()["supportUrl"]
        assert parse_qs(urlsplit(next_support).query)[EDITOR_SESSION_QUERY_PARAM] == [
            session
        ]
        current_session = "s_newsession"
        stale_document = client.get(resolved.text)
        stale_support = client.get(
            _view_support_url({"supportUrl": next_support}, "config")
            + "&"
            + urlencode({"runtime": "server", STUDIO_CLIENT_QUERY_PARAM: client_id}),
            headers=headers,
        )
        assert stale_support.status_code == 409
        assert stale_support.json()["error"] == "preview-session-changed"
        stale_config = client.get(
            "/_marimo-studio/views/dashboard/config?"
            + urlencode(
                {
                    "runtime": "server",
                    STUDIO_CLIENT_QUERY_PARAM: client_id,
                    EDITOR_SESSION_QUERY_PARAM: session,
                }
            ),
            headers={"Marimo-Studio-Preview-Session-Id": "s_view01"},
        )
    assert stale_document.status_code == 409
    assert "session changed" in stale_document.text
    assert stale_config.status_code == 409, stale_config.text
    assert stale_config.json()["error"] == "preview-session-changed"


def test_exact_preview_rechecks_source_after_resolving_publication(
    notebook_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from marimo_studio._server.presentation.service import NotebookPresentation

    configured(notebook_path)
    project = load_studio(notebook_path).views["dashboard"]
    original = NotebookPresentation.published_snapshot_async

    async def change_after_snapshot(presentation, *args, **kwargs):
        snapshot = await original(presentation, *args, **kwargs)
        source = project.root / "index.html"
        source.write_text(source.read_text() + "\n<!-- concurrent edit -->\n")
        return snapshot

    monkeypatch.setattr(
        NotebookPresentation, "published_snapshot_async", change_after_snapshot
    )
    app = marimo_app(notebook_path)
    edit_mode(app)
    with TestClient(app) as client:
        response = client.get(ENDPOINT, params={"runtime": "server", "exact": "1"})
    assert response.status_code == 409
    assert response.json()["error"] == "preview-source-changed"


@pytest.mark.parametrize("change", ["rebind", "session-close"])
def test_runtime_config_revalidates_editor_after_preparation(
    notebook_path: Path, monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    import asyncio
    import threading
    from concurrent.futures import ThreadPoolExecutor

    from marimo_studio._compat.server.session_state import PrivateSessionState
    from marimo_studio._server.agent.clients import StudioClientRegistry

    configured(notebook_path)
    app = marimo_app(notebook_path)
    edit_mode(app)
    preparing = threading.Event()
    resume = threading.Event()
    session = "s_123456"
    current_session = session
    session_exists = True
    attached = []

    async def session_for_client(*_args):
        return current_session

    async def prepare(*_args, **_kwargs):
        preparing.set()
        assert await asyncio.to_thread(resume.wait, 3)
        return {"runtime": {"id": "server"}}

    monkeypatch.setattr(StudioClientRegistry, "session_for_client", session_for_client)
    monkeypatch.setattr(PrivateSessionState, "exists", lambda *_args: session_exists)
    monkeypatch.setattr(PrivateSessionState, "ensure_started", lambda *_args: True)
    monkeypatch.setattr(
        "marimo_studio._server.runtime.routes.build_runtime_config", prepare
    )
    monkeypatch.setattr(
        "marimo_studio._compat.server.existing_session.PrivateExistingSessionAttachment.attach",
        lambda *args: attached.append(args) or True,
    )
    with TestClient(app) as client, ThreadPoolExecutor(max_workers=1) as worker:
        request = worker.submit(
            client.get,
            "/_marimo-studio/views/dashboard/config",
            params={
                "runtime": "server",
                "marimo_studio_client": "browser-client-1234",
                "marimo_studio_editor_session": session,
            },
            headers={"Marimo-Studio-Preview-Session-Id": "s_view01"},
        )
        try:
            assert preparing.wait(3)
            if change == "rebind":
                current_session = "s_newsession"
            else:
                session_exists = False
        finally:
            resume.set()
        response = request.result(timeout=3)
    assert response.status_code == 409
    assert response.json()["error"] == "preview-session-changed"
    assert attached == []


@pytest.mark.parametrize("source_state", ["stale", "failed"])
def test_exact_document_rejects_changed_source_without_retrying(
    notebook_path: Path, source_state: str
) -> None:
    from marimo_studio._artifacts.retention import lease_published_artifact
    from marimo_studio.errors import ViewProjectError

    configured(notebook_path)
    _enable_wasm(notebook_path)
    project = load_studio(notebook_path).views["dashboard"]
    app = marimo_app(notebook_path)
    edit_mode(app)
    with TestClient(app) as client:
        exact = client.get(ENDPOINT, params={"runtime": "wasm", "exact": "1"})
        assert exact.status_code == 200
        previous = client.get(exact.text)
        assert previous.status_code == 200
        source = project.root / "index.html"
        source.write_text(source.read_text() + "\n<!-- unpublished edit -->\n")
        if source_state == "failed":
            source.unlink()
            with pytest.raises(ViewProjectError):
                build_view_project_sync(project)
        retained = lease_published_artifact(project, "development")
        assert retained is not None
        with retained:
            assert "unpublished edit" not in retained.read_text(
                retained.artifact.document
            )
        response = client.get(exact.text)
    assert response.status_code == 409
    assert response.headers["Marimo-Studio-Error"] == "preview-source-not-current"
    assert 'data-marimo-studio-state="error"' in response.text
    assert 'role="alert"' in response.text
    assert "Preview unavailable" in response.text
    assert "EventSource" not in response.text
    assert "setTimeout" not in response.text
    assert "location.reload" not in response.text
    assert "retry-after" not in response.headers


def test_stable_preview_renews_the_retained_document_after_a_failed_edit(
    notebook_path: Path,
) -> None:
    configured(notebook_path)
    _enable_wasm(notebook_path)
    project = load_studio(notebook_path).views["dashboard"]
    app = marimo_app(notebook_path)
    edit_mode(app)
    with TestClient(app) as client:
        url = client.get(ENDPOINT, params={"runtime": "wasm"}).text
        initial = client.get(url)
        assert initial.status_code == 200
        original = project.root.joinpath("index.html").read_text()
        project.root.joinpath("index.html").write_text("<marimo-cell></marimo-cell>")
        with pytest.raises(ViewProjectError):
            build_view_project_sync(project)
        retained = client.get(url)
        assert retained.status_code == 200, retained.text
        revision = retained.headers["Marimo-Studio-Revision"]
        assert revision == initial.headers["Marimo-Studio-Revision"]
        renewal = _editor_mount_value(retained.text, "renewalToken")
        session = _editor_mount_value(retained.text, "sessionId")
        config = client.get(
            f"/_marimo-studio/presentation/{renewal}/_marimo-studio/views/dashboard/config",
            params={"runtime": "wasm", "revision": revision},
            headers={"Marimo-Studio-Preview-Session-Id": session},
        )
        assert config.status_code == 200, config.text
        assert config.json()["revision"] == revision
        project.root.joinpath("index.html").write_text(original + "<!-- repaired -->")
        with build_view_project_sync(project):
            pass
        repaired = client.get(url)
        assert repaired.status_code == 200
        assert repaired.headers["Marimo-Studio-Revision"] != revision
