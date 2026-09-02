"""Exercise interrupted-build recovery and project-incarnation safety."""

from __future__ import annotations

import os
import shutil
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from threading import Event
from typing import Any

import pytest

import marimo_studio._artifacts.repository as repository_module
from marimo_studio._artifacts.lock import build_lock as artifact_build_lock
from marimo_studio._artifacts.paths import artifact_root
from marimo_studio._artifacts.repository import (
    read_artifact_state,
    read_build_state,
)
from marimo_studio._artifacts.retention import lease_published_artifact
from marimo_studio._views.build import publish_view as publish_artifact_lease
from marimo_studio._workspace.project_manifest import load_view_project
from marimo_studio.errors import ViewProjectError
from marimo_studio.view_providers import (
    ViewProject,
)
from marimo_studio.view_providers._host import provider_registry

from ..artifact_test_support import (
    profile_path as _profile_path,
)
from ..artifact_test_support import (
    project as _project,
)
from ..artifact_test_support import (
    publish_artifact,
)
from ..artifact_test_support import (
    read_json as _read_json,
)
from ..artifact_test_support import (
    write_json as _write_json,
)


def _project_with_interrupted_build(tmp_path: Path) -> ViewProject:
    project = _project(tmp_path)
    publish_artifact_lease(project, "development").close()
    pointer = _profile_path(project)
    state = _read_json(pointer)
    state["build"]["phase"] = "building"
    _write_json(pointer, state)
    return project


def _replace_with_active_build(
    project: ViewProject,
    tmp_path: Path,
) -> tuple[ViewProject, Path, str]:
    retired = tmp_path / f"{project.name}-retired"
    os.replace(project.root, retired)
    shutil.copytree(retired, project.root)
    current = load_view_project(project.root)
    pointer = _profile_path(current)
    state = _read_json(pointer)
    revision = f"sha256:{'f' * 64}"
    state["build"]["phase"] = "building"
    state["build"]["project_revision"] = revision
    _write_json(pointer, state)
    sentinel = artifact_root(current) / ".staging" / "new-build" / "active.txt"
    sentinel.parent.mkdir(parents=True)
    sentinel.write_text("active\n", encoding="utf-8")
    return current, sentinel, revision


def test_interrupted_build_becomes_stale_and_cleans_staging(tmp_path: Path) -> None:
    project = _project(tmp_path)
    artifact = publish_artifact(project, "development")
    pointer = _profile_path(project)
    state = _read_json(pointer)
    state["build"]["phase"] = "building"
    _write_json(pointer, state)
    abandoned = artifact_root(project) / ".staging" / "abandoned" / "work"
    abandoned.mkdir(parents=True)
    (abandoned / "partial.js").write_text("partial", encoding="utf-8")

    recovered = read_build_state(project, "development")

    assert recovered.phase == "stale"
    assert recovered.artifact_revision == artifact.artifact_revision
    assert recovered.diagnostics[0].code == "build-interrupted"
    assert tuple((artifact_root(project) / ".staging").iterdir()) == ()


def test_build_repairs_each_replaceable_generated_state(tmp_path: Path) -> None:
    project = _project(tmp_path)
    publish_artifact_lease(project, "development").close()

    for damage in ("receipt", "missing revision", "manifest"):
        published = read_artifact_state(project, "development").artifact
        assert published is not None
        revision = published.root.parent
        if damage == "receipt":
            _profile_path(project).write_text("{", encoding="utf-8")
        elif damage == "missing revision":
            shutil.rmtree(revision)
        else:
            (revision / "artifact.json").write_text("{}\n", encoding="utf-8")

        publish_artifact_lease(project, "development").close()

        repaired = read_artifact_state(project, "development")
        assert repaired.build.phase == "published", damage
        assert repaired.artifact is not None, damage
        if damage == "receipt":
            assert [item.code for item in repaired.build.diagnostics] == [
                "artifact-state-repaired"
            ]


def test_provider_api_change_preserves_last_good_until_the_next_build(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _project(tmp_path)
    provider = provider_registry().get(project.provider)
    build = provider.build
    with publish_artifact_lease(project, "development") as first_lease:
        first = first_lease.artifact
        expected_document = first_lease.read_text(first.document)
    pointer = _profile_path(project)
    state = _read_json(pointer)
    state["published"]["provider"]["api_version"] = 2
    previous_project_revision = f"sha256:{'f' * 64}"
    state["published"]["project_revision"] = previous_project_revision
    state["build"]["project_revision"] = previous_project_revision
    _write_json(pointer, state)

    retained = read_artifact_state(project, "development")
    assert retained.artifact is not None
    assert retained.artifact.artifact_revision == first.artifact_revision
    assert retained.artifact.provider.api_version == 2
    assert retained.build.phase == "published"
    last_good = lease_published_artifact(project, "development")
    assert last_good is not None
    with last_good:
        assert last_good.read_text(last_good.artifact.document) == expected_document

    def fail_rebuild(_request: object) -> None:
        raise RuntimeError("provider API rebuild failed")

    monkeypatch.setattr(provider, "build", fail_rebuild)
    with pytest.raises(ViewProjectError, match="provider API rebuild failed"):
        publish_artifact_lease(project, "development")

    failed = read_artifact_state(project, "development")
    assert failed.artifact is not None
    assert failed.artifact.provider.api_version == 2
    assert failed.build.phase == "failed"
    assert failed.build.artifact_revision == first.artifact_revision
    last_good = lease_published_artifact(project, "development")
    assert last_good is not None
    with last_good:
        assert last_good.read_text(last_good.artifact.document) == expected_document

    monkeypatch.setattr(provider, "build", build)
    publish_artifact_lease(project, "development").close()
    rebuilt = read_artifact_state(project, "development")
    assert rebuilt.artifact is not None
    assert rebuilt.artifact.provider.api_version == 1
    assert rebuilt.build.phase == "published"
    assert rebuilt.build.diagnostics == ()


def test_artifact_state_settles_when_its_view_is_removed_during_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _project(tmp_path)
    publish_artifact_lease(project, "development").close()

    def removed_revision(*_args: object, **_kwargs: object) -> object:
        shutil.rmtree(project.root)
        raise FileNotFoundError("view removed")

    monkeypatch.setattr(repository_module, "read_artifact_revision", removed_revision)

    state = read_artifact_state(project, "development")

    assert state.artifact is None
    assert state.build.phase == "unbuilt"


def test_build_repairs_a_revision_while_its_previous_lease_is_live(
    tmp_path: Path,
) -> None:
    project = _project(tmp_path)
    first = publish_artifact_lease(project, "development")
    document = first.artifact.document
    expected = first.read_text(document)
    (first.artifact.root.parent / "artifact.json").write_text(
        "{}\n",
        encoding="utf-8",
    )

    rebuilt = publish_artifact_lease(project, "development")
    try:
        assert rebuilt.read_text(document) == expected
        assert first.read_text(document) == expected
    finally:
        rebuilt.close()
        first.close()

    state = read_build_state(project, "development")
    assert state.phase == "published"
    assert any(item.code == "artifact-state-repaired" for item in state.diagnostics)


@pytest.mark.parametrize("reader", ("build", "artifact"))
def test_state_read_does_not_recreate_project_deleted_before_read_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    reader: str,
) -> None:
    project = _project_with_interrupted_build(tmp_path)
    artifact_lock = repository_module.artifact_lock
    ready = Event()
    release = Event()

    @contextmanager
    def paused_artifact_lock(*args: Any, **kwargs: Any):
        ready.set()
        if not release.wait(timeout=2):
            raise RuntimeError("state read was not released")
        with artifact_lock(*args, **kwargs) as acquired:
            yield acquired

    monkeypatch.setattr(repository_module, "artifact_lock", paused_artifact_lock)

    def read() -> str:
        state = (
            read_build_state(project, "development")
            if reader == "build"
            else read_artifact_state(project, "development").build
        )
        return state.phase

    with ThreadPoolExecutor(max_workers=1) as executor:
        pending = executor.submit(read)
        assert ready.wait(timeout=2)
        shutil.rmtree(project.root)
        release.set()
        assert pending.result(timeout=2) == "unbuilt"

    assert not project.root.exists()


@pytest.mark.parametrize("reader", ("build", "artifact"))
def test_state_recovery_rejects_recreated_project_after_old_build_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    reader: str,
) -> None:
    project = _project_with_interrupted_build(tmp_path)
    build_lock = repository_module.build_lock
    ready = Event()
    release = Event()

    @contextmanager
    def paused_build_lock(*args: Any, **kwargs: Any):
        with build_lock(*args, **kwargs) as acquired:
            if acquired:
                ready.set()
                if not release.wait(timeout=2):
                    raise RuntimeError("ABA state read was not released")
            yield acquired

    monkeypatch.setattr(repository_module, "build_lock", paused_build_lock)

    def read() -> str:
        state = (
            read_build_state(project, "development")
            if reader == "build"
            else read_artifact_state(project, "development").build
        )
        return state.phase

    with ThreadPoolExecutor(max_workers=1) as executor:
        pending = executor.submit(read)
        assert ready.wait(timeout=2)
        if os.name == "nt":
            # The open build-lock directory handles prevent project replacement
            # until the active reader releases its ownership.
            try:
                with pytest.raises(PermissionError):
                    _replace_with_active_build(project, tmp_path)
            finally:
                release.set()
            assert pending.result(timeout=2) == "stale"
            return
        current, sentinel, revision = _replace_with_active_build(project, tmp_path)
        with artifact_build_lock(current) as acquired:
            assert acquired
            release.set()
            assert pending.result(timeout=2) == "unbuilt"

    state = _read_json(_profile_path(current))
    assert state["build"]["phase"] == "building"
    assert state["build"]["project_revision"] == revision
    assert sentinel.read_text(encoding="utf-8") == "active\n"
