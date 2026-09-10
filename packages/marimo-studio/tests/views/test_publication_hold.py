from __future__ import annotations

import json
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event
from types import SimpleNamespace

import pytest

import marimo_studio._views.publication_hold as hold_module
from marimo_studio._artifacts.repository import read_build_state
from marimo_studio._artifacts.retention import lease_published_artifact
from marimo_studio._views.build import publish_view
from marimo_studio._views.publication_hold import (
    acquire_publication_hold,
    publication_hold_path,
    read_publication_hold,
    release_publication_hold,
)
from marimo_studio._workspace.generation import view_generation
from marimo_studio.errors import (
    ConfigurationError,
    ViewGenerationConflictError,
    ViewProjectError,
)
from marimo_studio.view_providers import BuildRequest, BuildResult
from marimo_studio.view_providers._host import provider_registry

from ..app_helpers import created_one_view
from ..artifact_test_support import change_document


def test_hold_token_owns_release_and_repeated_release_is_idempotent(
    notebook_path: Path,
) -> None:
    project = created_one_view(notebook_path).views["dashboard"]
    hold = acquire_publication_hold(project.root, owner="layout agent")

    with pytest.raises(ConfigurationError, match="held by 'layout agent'"):
        acquire_publication_hold(project.root, owner="another agent")
    with pytest.raises(ConfigurationError, match="another owner"):
        release_publication_hold(project.root, "wrong token")
    assert read_publication_hold(project.root) == hold

    released = release_publication_hold(project.root, hold.token)
    assert released is not None
    assert released.status == "released"
    assert release_publication_hold(project.root, hold.token) == released

    next_hold = acquire_publication_hold(project.root, owner="another agent")
    with pytest.raises(ConfigurationError, match="another owner"):
        release_publication_hold(project.root, hold.token)
    assert read_publication_hold(project.root) == next_hold


@pytest.mark.parametrize("ttl", [0, float("inf"), float("nan"), 3_601])
def test_hold_requires_a_bounded_finite_lifetime(
    notebook_path: Path,
    ttl: float,
) -> None:
    project = created_one_view(notebook_path).views["dashboard"]
    with pytest.raises(ValueError, match="ttl"):
        acquire_publication_hold(project.root, owner="agent", ttl=ttl)


def test_expired_hold_preserves_source_and_admits_new_owner(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = created_one_view(notebook_path).views["dashboard"]
    now = 1_000.0
    monkeypatch.setattr(hold_module, "time", SimpleNamespace(time=lambda: now))
    hold = acquire_publication_hold(project.root, owner="agent", ttl=10)
    change_document(project, "unfinished edit")
    source = (project.root / "index.html").read_bytes()

    now = 1_010.0
    assert hold.status == "expired"
    observed = read_publication_hold(project.root)
    assert observed is not None
    assert observed.to_dict()["status"] == "expired"
    next_hold = acquire_publication_hold(project.root, owner="repair agent", ttl=20)
    assert next_hold.status == "active"
    assert (project.root / "index.html").read_bytes() == source


def test_hold_does_not_follow_a_replaced_view_incarnation(notebook_path: Path) -> None:
    project = created_one_view(notebook_path).views["dashboard"]
    generation = view_generation(project)
    hold = acquire_publication_hold(project.root, owner="agent")
    previous = project.root.with_name("previous")
    project.root.rename(previous)
    shutil.copytree(previous, project.root)

    assert read_publication_hold(project.root) is None
    with pytest.raises(ViewGenerationConflictError):
        release_publication_hold(
            project.root, hold.token, expected_generation=generation
        )
    current = acquire_publication_hold(project.root, owner="replacement agent")
    assert current.generation != generation


def test_hold_preserves_current_publication_while_source_is_edited(
    notebook_path: Path,
) -> None:
    project = created_one_view(notebook_path).views["dashboard"]
    with publish_view(project, "development") as initial:
        revision = initial.artifact.artifact_revision
    hold = acquire_publication_hold(project.root, owner="layout agent")

    with publish_view(project, "development") as cached:
        assert cached.artifact.artifact_revision == revision
    change_document(project, "new chapter")
    with pytest.raises(ViewProjectError, match="held by 'layout agent'"):
        publish_view(project, "development")
    state = read_build_state(project, "development")
    assert state.diagnostics[0].code == "publication-held"
    published = lease_published_artifact(project, "development")
    assert published is not None
    with published as current:
        assert current.artifact.artifact_revision == revision

    release_publication_hold(project.root, hold.token)
    with publish_view(project, "development") as updated:
        assert updated.artifact.artifact_revision != revision
        assert "new chapter" in updated.read_text(updated.artifact.document)


def test_hold_acquired_during_build_prevents_candidate_publication(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = created_one_view(notebook_path).views["dashboard"]
    with publish_view(project, "development") as initial:
        revision = initial.artifact.artifact_revision
    change_document(project, "new chapter")
    provider = provider_registry().get(project.provider)
    build = provider.build
    entered = Event()
    proceed = Event()

    def blocked_build(request: BuildRequest) -> BuildResult:
        entered.set()
        assert proceed.wait(5), "Provider was not released"
        return build(request)

    monkeypatch.setattr(provider, "build", blocked_build)
    with ThreadPoolExecutor(max_workers=1) as executor:
        candidate = executor.submit(publish_view, project, "development")
        try:
            assert entered.wait(5), "Provider did not begin"
            acquire_publication_hold(project.root, owner="editing agent")
        finally:
            proceed.set()
        with pytest.raises(ViewProjectError, match="held by 'editing agent'"):
            candidate.result(timeout=5)

    published = lease_published_artifact(project, "development")
    assert published is not None
    with published as current:
        assert current.artifact.artifact_revision == revision


@pytest.mark.native_process
def test_hold_created_by_an_exited_process_still_coordinates_publication(
    notebook_path: Path,
) -> None:
    project = created_one_view(notebook_path).views["dashboard"]
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import json, sys\n"
            "from pathlib import Path\n"
            "from marimo_studio._workspace.project_manifest import load_view_project\n"
            "from marimo_studio._views.publication_hold import "
            "acquire_publication_hold\n"
            "project = load_view_project(Path(sys.argv[1]))\n"
            "hold = acquire_publication_hold(project.root, owner='shell agent')\n"
            "print(json.dumps(hold.to_dict()))\n",
            str(project.root),
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    receipt = json.loads(result.stdout)
    hold = read_publication_hold(project.root)
    assert hold is not None
    assert hold.token == receipt["token"]
    assert hold.status == "active"
    with pytest.raises(ViewProjectError, match="held by 'shell agent'"):
        publish_view(project, "development")
    released = release_publication_hold(project.root, receipt["token"])
    assert released is not None
    assert released.status == "released"


def test_hold_rejects_a_control_record_symlink(notebook_path: Path) -> None:
    project = created_one_view(notebook_path).views["dashboard"]
    outside = notebook_path.parent / "outside.txt"
    outside.write_text("preserve me", encoding="utf-8")
    publication_hold_path(project.root).symlink_to(outside)

    with pytest.raises(ConfigurationError):
        acquire_publication_hold(project.root, owner="agent")
    assert outside.read_text(encoding="utf-8") == "preserve me"
