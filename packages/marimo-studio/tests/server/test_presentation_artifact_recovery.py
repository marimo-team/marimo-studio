from __future__ import annotations

import asyncio
import shutil
from pathlib import Path
from urllib.parse import urljoin

import pytest
from starlette.testclient import TestClient

from marimo_studio._artifacts.paths import artifact_root
from marimo_studio._artifacts.retention import lease_published_artifact
from marimo_studio._server.development.coordinator import DevelopmentCoordinator
from marimo_studio._server.presentation.service import NotebookPresentation
from marimo_studio._views.build import build_view_project_sync
from marimo_studio._workspace import load_studio
from marimo_studio._workspace.metadata import update_notebook_config

from ..app_helpers import configured, edit_mode, marimo_app
from .app_test_support import _artifact_base


@pytest.mark.parametrize("removed", ["artifact-directory", "stylesheet"])
def test_display_recovers_after_retained_artifact_files_are_removed(
    notebook_path: Path,
    removed: str,
) -> None:
    configured(notebook_path)
    update_notebook_config(
        notebook_path, lambda config: config.update(runtimes=["server", "wasm"])
    )
    project = load_studio(notebook_path).views["dashboard"]
    source = project.root / "index.html"
    source.write_text(
        source.read_text().replace(
            "</head>", '<link rel="stylesheet" href="style.css"></head>'
        )
    )
    project.root.joinpath("style.css").write_text("body { color: rgb(12, 34, 56); }")
    with build_view_project_sync(project):
        pass
    app = marimo_app(notebook_path)
    edit_mode(app)
    url = "/dashboard/?runtime=wasm&marimo_studio_unframed=1"
    with TestClient(app) as client:
        first = client.get(url)
        assert first.status_code == 200
        asset = urljoin(_artifact_base(first.text), "style.css")
        assert client.get(asset).status_code == 200
        retained = lease_published_artifact(project, "development")
        assert retained is not None
        with retained:
            if removed == "artifact-directory":
                shutil.rmtree(retained.artifact.root)
            else:
                retained.artifact.root.joinpath("style.css").unlink()
        missing = client.get(url)
        if missing.status_code == 200:
            assert (
                client.get(
                    urljoin(_artifact_base(missing.text), "style.css")
                ).status_code
                == 200
            )
        else:
            assert missing.status_code == 409
            assert "artifact" in missing.text.lower()
        with build_view_project_sync(project):
            pass
        recovered = client.get(url)
        assert recovered.status_code == 200
        stylesheet = client.get(urljoin(_artifact_base(recovered.text), "style.css"))
    assert stylesheet.status_code == 200
    assert "rgb(12, 34, 56)" in stylesheet.text


def test_identical_output_rebuild_refreshes_exact_source_provenance(
    notebook_path: Path,
) -> None:
    studio = configured(notebook_path)
    project = studio.views["dashboard"]
    development = DevelopmentCoordinator()
    presentation = NotebookPresentation(notebook_path, development=development)

    async def exercise() -> None:
        try:
            first = await presentation.current_published_snapshot_async("dashboard")
            project.manifest.write_text(
                project.manifest.read_text() + "\n# Rebuilt source provenance\n"
            )
            with await asyncio.to_thread(build_view_project_sync, project) as rebuilt:
                assert (
                    rebuilt.artifact.artifact_revision
                    == first.artifact.artifact_revision
                )
                assert (
                    rebuilt.artifact.project_revision != first.artifact.project_revision
                )
                project_revision = rebuilt.artifact.project_revision
            current = await presentation.current_published_snapshot_async("dashboard")
            assert current.revision == first.revision
            assert current.artifact.project_revision == project_revision
            lease = await asyncio.to_thread(
                presentation.lease_artifact,
                "dashboard",
                current.artifact.artifact_revision,
            )
            assert lease is not None
            with lease:
                assert lease.artifact.project_revision == project_revision
        finally:
            await asyncio.to_thread(presentation.close)
            await development.close()

    asyncio.run(exercise())


def test_rejected_stale_build_does_not_invalidate_the_current_exact_preview(
    notebook_path: Path,
) -> None:
    from marimo_studio._views.build import publish_view
    from marimo_studio._views.revisions import capture_source_snapshot
    from marimo_studio.errors import ViewProjectError

    configured(notebook_path)
    update_notebook_config(
        notebook_path, lambda config: config.update(runtimes=["server", "wasm"])
    )
    studio = load_studio(notebook_path)
    project = studio.views["dashboard"]
    prepared = capture_source_snapshot(studio, ("dashboard",)).projects["dashboard"]
    source = project.root / "index.html"
    source.write_text(
        source.read_text().replace("</main>", "<h1>New publication</h1></main>")
    )
    with build_view_project_sync(project):
        pass
    app = marimo_app(notebook_path)
    edit_mode(app)
    with TestClient(app) as client:
        endpoint = "/_marimo-studio/views/dashboard/preview?runtime=wasm&exact=1"
        accepted = client.get(endpoint)
        assert accepted.status_code == 200, accepted.text
        with pytest.raises(ViewProjectError, match="prepared build"):
            publish_view(
                project,
                "development",
                inspection=prepared.inspection,
                input_id=prepared.input_id,
            )
        after = client.get(endpoint)
        assert after.status_code == 200, after.text
        assert after.text == accepted.text
        document = client.get(accepted.text)
    assert document.status_code == 200
    assert "New publication" in document.text


@pytest.mark.parametrize("prepared", [False, True])
def test_cancelled_cache_restore_keeps_current_exact_preview(
    notebook_path: Path, monkeypatch: pytest.MonkeyPatch, prepared: bool
) -> None:
    from marimo_studio._artifacts import publication
    from marimo_studio._processes.cancellation import (
        ProviderOperationControl,
        provider_cancellation,
    )
    from marimo_studio._views.build import publish_view
    from marimo_studio._views.revisions import capture_source_snapshot
    from marimo_studio.errors import ViewProjectError

    configured(notebook_path)
    update_notebook_config(
        notebook_path, lambda config: config.update(runtimes=["server", "wasm"])
    )
    studio = load_studio(notebook_path)
    project = studio.views["dashboard"]
    observed = capture_source_snapshot(studio, ("dashboard",)).projects["dashboard"]
    profile_path = artifact_root(project) / "development.json"
    accepted_receipt = profile_path.read_bytes()
    write = publication.write_profile_state_if_active

    def cancel_before_commit(project, state, control):
        control.cancel()
        return write(project, state, control)

    monkeypatch.setattr(
        publication, "write_profile_state_if_active", cancel_before_commit
    )
    app = marimo_app(notebook_path)
    edit_mode(app)
    with TestClient(app) as client:
        endpoint = "/_marimo-studio/views/dashboard/preview?runtime=wasm&exact=1"
        accepted = client.get(endpoint)
        assert accepted.status_code == 200
        control = ProviderOperationControl()
        with (
            provider_cancellation(control),
            pytest.raises(ViewProjectError, match="cancelled"),
        ):
            publish_view(
                project,
                "development",
                inspection=observed.inspection if prepared else None,
                input_id=observed.input_id if prepared else None,
            )
        assert profile_path.read_bytes() == accepted_receipt
        after = client.get(endpoint)
        assert after.status_code == 200, after.text
        assert after.text == accepted.text
        document = client.get(accepted.text)
    assert document.status_code == 200
