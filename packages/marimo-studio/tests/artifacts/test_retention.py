"""Exercise artifact concurrency, deletion, leases, and retention."""

from __future__ import annotations

import multiprocessing
import os
import shutil
import time
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

import pytest

import marimo_studio._artifacts.retention as retention_module
import marimo_studio._views.remove as workspace_views
from marimo_studio._artifacts.lock import acquire_file_lock, release_file_lock
from marimo_studio._artifacts.paths import artifact_root
from marimo_studio._artifacts.repository import read_build_state
from marimo_studio._artifacts.retention import (
    lease_published_artifact,
    prune_artifacts,
    prune_artifacts_locked,
)
from marimo_studio._views.api import prepare_view
from marimo_studio._views.build import publish_view as publish_artifact_lease
from marimo_studio._views.remove import delete_view
from marimo_studio._workspace import load_studio
from marimo_studio._workspace.mutation_lock import (
    view_build_lock,
    view_mutation_lock,
    workspace_catalog_lock,
)
from marimo_studio._workspace.project_manifest import load_view_project
from marimo_studio.errors import ConfigurationError, ViewInUseError
from marimo_studio.view_providers import (
    BuildProfile,
    ViewProject,
)

from ..artifact_test_support import (
    change_document as _change_document,
)
from ..artifact_test_support import (
    project as _project,
)
from ..artifact_test_support import (
    publish_artifact,
)
from ..artifact_test_support import wait_for_file as _wait_for_file


def _publish_in_process(root: str, profile: BuildProfile) -> str:
    return publish_artifact(load_view_project(Path(root)), profile).artifact_revision


def test_prune_settles_when_revisions_disappear_after_validation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _project(tmp_path)
    publish_artifact(project, "development")
    revisions = artifact_root(project) / "revisions"
    assert_path = retention_module.assert_secure_path

    def remove_after_validation(
        root: Path,
        target: Path,
        label: str,
        *,
        final_kind: str | None = None,
    ) -> None:
        assert_path(root, target, label, final_kind=final_kind)
        if target == revisions and final_kind == "directory":
            shutil.rmtree(revisions)

    monkeypatch.setattr(retention_module, "assert_secure_path", remove_after_validation)

    prune_artifacts_locked(project)

    assert not revisions.exists()


def test_prune_settles_when_project_disappears_before_pin_scan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _project(tmp_path)
    publish_artifact(project, "development")
    live_pins = retention_module._live_pin_revisions

    def remove_before_scan(
        selected: ViewProject,
        *,
        create: bool = True,
    ) -> set[str]:
        assert selected == project
        shutil.rmtree(project.root)
        return live_pins(project, create=create)

    monkeypatch.setattr(retention_module, "_live_pin_revisions", remove_before_scan)

    prune_artifacts_locked(project)

    assert not project.root.exists()


def test_prune_rejects_an_existing_non_directory_project_root(
    tmp_path: Path,
) -> None:
    project = _project(tmp_path)
    shutil.rmtree(project.root)
    project.root.write_text("not a project directory\n", encoding="utf-8")

    with pytest.raises(
        ConfigurationError, match="View project root must be a directory"
    ):
        prune_artifacts_locked(project)


def test_public_prune_does_not_recreate_a_removed_project(tmp_path: Path) -> None:
    project = _project(tmp_path)
    publish_artifact(project, "development")
    shutil.rmtree(project.root)

    prune_artifacts(project)

    assert not project.root.exists()


def test_public_prune_does_not_create_an_absent_artifact_tree(
    tmp_path: Path,
) -> None:
    project = _project(tmp_path)
    control_root = artifact_root(project)
    assert not control_root.exists()

    prune_artifacts(project)

    assert not control_root.exists()


def test_public_prune_reports_an_unavailable_lock(tmp_path: Path) -> None:
    project = _project(tmp_path)
    artifact_root(project).mkdir()

    with pytest.raises(RuntimeError, match="Blocking artifact lock was not acquired"):
        prune_artifacts(project)


@pytest.mark.parametrize(
    ("target", "message"),
    (
        ("project", "View project root must be a directory"),
        ("artifacts", "Artifact control root must be a directory"),
    ),
)
def test_public_prune_rejects_existing_non_directory_roots(
    tmp_path: Path,
    target: str,
    message: str,
) -> None:
    project = _project(tmp_path)
    selected = project.root if target == "project" else artifact_root(project)
    if selected == project.root:
        shutil.rmtree(project.root)
    selected.write_text("not a directory\n", encoding="utf-8")

    with pytest.raises(ConfigurationError, match=message):
        prune_artifacts(project)


def _publish_stale_project_in_process(root: str, started: str) -> str:
    project = load_view_project(Path(root))
    Path(started).write_text("started\n", encoding="utf-8")
    try:
        with publish_artifact_lease(project, "development") as lease:
            return lease.artifact.artifact_revision
    except Exception as error:
        return f"{type(error).__name__}: {error}"


def _delete_view_in_process(
    notebook: str,
    view_name: str,
    acquired: str,
    release: str,
) -> str:
    studio = load_studio(Path(notebook))
    with (
        workspace_catalog_lock(studio.view_root),
        view_build_lock(studio.view_root, view_name),
        view_mutation_lock(studio.view_root, view_name),
    ):
        Path(acquired).write_text("acquired\n", encoding="utf-8")
        deadline = time.monotonic() + 5
        release_path = Path(release)
        while not release_path.exists():
            if time.monotonic() >= deadline:
                raise TimeoutError("Deletion release signal was not written")
            time.sleep(0.01)
        delete_view(studio, view_name)
    return "deleted"


def _hold_artifact_lease_in_process(root: str, ready: str, release: str) -> str:
    project = load_view_project(Path(root))
    lease = lease_published_artifact(project, "development")
    if lease is None:
        return "missing"
    Path(ready).write_text("ready\n", encoding="utf-8")
    deadline = time.monotonic() + 5
    release_path = Path(release)
    while not release_path.exists():
        if time.monotonic() >= deadline:
            raise TimeoutError("Lease release signal was not written")
        time.sleep(0.01)
    lease.close()
    return "released"


def test_concurrent_profiles_publish_one_verified_revision(tmp_path: Path) -> None:
    project = _project(tmp_path)

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(publish_artifact, project, profile)
            for profile in ("development", "production")
        ]
    artifacts = [future.result() for future in futures]

    assert artifacts[0].artifact_revision == artifacts[1].artifact_revision
    assert len(tuple((artifact_root(project) / "revisions").iterdir())) == 1
    assert read_build_state(project, "development").phase == "published"
    assert read_build_state(project, "production").phase == "published"


@pytest.mark.native_process
def test_concurrent_processes_publish_one_verified_revision(tmp_path: Path) -> None:
    project = _project(tmp_path)
    context = multiprocessing.get_context("spawn")

    with ProcessPoolExecutor(max_workers=2, mp_context=context) as executor:
        futures = [
            executor.submit(_publish_in_process, str(project.root), profile)
            for profile in ("development", "production")
        ]
    revisions = [future.result() for future in futures]

    assert revisions[0] == revisions[1]
    assert len(tuple((artifact_root(project) / "revisions").iterdir())) == 1


def test_external_publication_cannot_recreate_a_deleted_view(
    notebook_path: Path,
) -> None:
    prepare_view(notebook_path)
    prepare_view(notebook_path, "operations")
    studio = load_studio(notebook_path)
    project = studio.views["operations"]
    signals = notebook_path.parent / "mutation-signals"
    signals.mkdir()
    deletion_acquired = signals / "deletion-acquired"
    release_deletion = signals / "release-deletion"
    publication_started = signals / "publication-started"
    context = multiprocessing.get_context("spawn")

    with ProcessPoolExecutor(max_workers=2, mp_context=context) as executor:
        deletion = executor.submit(
            _delete_view_in_process,
            str(notebook_path),
            project.name,
            str(deletion_acquired),
            str(release_deletion),
        )
        _wait_for_file(deletion_acquired)
        publication = executor.submit(
            _publish_stale_project_in_process,
            str(project.root),
            str(publication_started),
        )
        _wait_for_file(publication_started)
        release_deletion.write_text("release\n", encoding="utf-8")
        assert deletion.result(timeout=5) == "deleted"
        publication_result = publication.result(timeout=5)

    assert publication_result.startswith("ConfigurationError:")
    assert not project.root.exists()
    assert project.name not in load_studio(notebook_path).views


@pytest.mark.native_process
def test_deletion_rejects_artifact_lease_owned_by_another_process(
    notebook_path: Path,
) -> None:
    prepare_view(notebook_path)
    prepare_view(notebook_path, "operations")
    project = load_studio(notebook_path).views["operations"]
    with publish_artifact_lease(project, "development"):
        pass
    signals = notebook_path.parent / "lease-signals"
    signals.mkdir()
    ready = signals / "ready"
    release = signals / "release"
    context = multiprocessing.get_context("spawn")

    with ProcessPoolExecutor(max_workers=1, mp_context=context) as executor:
        holder = executor.submit(
            _hold_artifact_lease_in_process,
            str(project.root),
            str(ready),
            str(release),
        )
        _wait_for_file(ready)
        with pytest.raises(ViewInUseError, match="open in another process"):
            delete_view(load_studio(notebook_path), "operations")
        assert project.root.is_dir()
        release.write_text("release\n", encoding="utf-8")
        assert holder.result(timeout=5) == "released"

    delete_view(load_studio(notebook_path), "operations")
    assert not project.root.exists()


def test_deletion_closes_view_local_lock_before_rename(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepare_view(notebook_path)
    prepare_view(notebook_path, "operations")
    project = load_studio(notebook_path).views["operations"]
    with publish_artifact_lease(project, "development"):
        pass
    lock_path = artifact_root(project) / ".publication.lock"
    replace = workspace_views.SecureDirectory.replace
    observed = False

    def checked_replace(
        filesystem: workspace_views.SecureDirectory,
        source: Path,
        destination: Path,
    ) -> None:
        nonlocal observed
        if Path(source) == project.root:
            descriptor = os.open(lock_path, os.O_RDWR)
            acquired = False
            try:
                acquired = acquire_file_lock(descriptor, blocking=False)
                assert acquired
                observed = True
            finally:
                if acquired:
                    release_file_lock(descriptor)
                os.close(descriptor)
        replace(filesystem, source, destination)

    monkeypatch.setattr(
        workspace_views.SecureDirectory,
        "replace",
        checked_replace,
    )

    delete_view(load_studio(notebook_path), project.name)

    assert observed
    assert not project.root.exists()


def test_stale_artifact_lease_does_not_recreate_removed_project(
    tmp_path: Path,
) -> None:
    project = _project(tmp_path)
    lease = publish_artifact_lease(project, "development")
    missing = tmp_path / "removed" / "view"
    stale_project = replace(project, root=missing)
    lease.project = stale_project
    lease.artifact = replace(
        lease.artifact,
        root=missing / ".artifacts" / "revisions" / "removed" / "files",
    )

    with pytest.raises(ConfigurationError, match="removed"):
        lease.share()
    with pytest.raises(ConfigurationError, match="removed"):
        lease.read_bytes(lease.artifact.document)
    assert lease_published_artifact(stale_project, "development") is None
    assert not missing.exists()

    lease.close()


def test_artifact_lease_close_is_idempotent_after_project_removal(
    tmp_path: Path,
) -> None:
    project = _project(tmp_path)
    lease = publish_artifact_lease(project, "development")
    owner = lease._owner
    assert owner is not None
    owner.current()._release()
    shutil.rmtree(project.root)

    lease.close()
    lease.close()

    assert not project.root.exists()


def test_artifact_lease_close_rejects_an_existing_non_directory_root(
    tmp_path: Path,
) -> None:
    project = _project(tmp_path)
    lease = publish_artifact_lease(project, "development")
    owner = lease._owner
    assert owner is not None
    pin = owner.current()
    invalid_root = tmp_path / "invalid-view-root"
    invalid_root.write_text("not a project directory\n", encoding="utf-8")
    pin.project = replace(project, root=invalid_root)

    with pytest.raises(
        ConfigurationError, match="View project root must be a directory"
    ):
        lease.close()

    lease.close()


@pytest.mark.native_process
def test_child_leases_share_one_cross_process_pin(tmp_path: Path) -> None:
    project = _project(tmp_path)
    lease = publish_artifact_lease(project, "development")
    digest = lease.artifact.artifact_revision.removeprefix("sha256:")
    pin_directory = artifact_root(project) / ".pins" / digest

    children = tuple(lease.share() for _index in range(2))

    assert len(tuple(pin_directory.iterdir())) == 1
    lease.close()
    assert pin_directory.is_dir()
    for child in children[:-1]:
        child.close()
        assert pin_directory.is_dir()
    children[-1].close()
    assert not pin_directory.exists()


def test_profile_publications_and_live_pins_own_revision_retention(
    tmp_path: Path,
) -> None:
    project = _project(tmp_path)
    pin = publish_artifact_lease(project, "development")
    first = pin.artifact
    _change_document(project, "production")
    production = publish_artifact(project, "production")
    _change_document(project, "new development")
    development = publish_artifact(project, "development")

    assert first.root.parent.is_dir()
    assert production.root.parent.is_dir()
    assert development.root.parent.is_dir()

    pin.close()

    assert not first.root.parent.exists()
    assert production.root.parent.is_dir()
    assert development.root.parent.is_dir()


@pytest.mark.native_process
def test_dead_process_pins_are_removed_during_publication(tmp_path: Path) -> None:
    project = _project(tmp_path)
    with publish_artifact_lease(project, "development") as lease:
        first = lease.artifact
    digest = first.artifact_revision.removeprefix("sha256:")
    pin_directory = artifact_root(project) / ".pins" / digest
    pin_directory.mkdir(parents=True)
    dead_pid = 2_000_000_000
    (pin_directory / f"{dead_pid}-{'0' * 32}").write_text(
        f"{dead_pid}\n",
        encoding="utf-8",
    )
    _change_document(project, "next")

    publish_artifact(project, "development")

    assert not first.root.parent.exists()
    assert not pin_directory.exists()
