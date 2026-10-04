"""Exercise artifact candidate isolation and filesystem safety."""

from __future__ import annotations

import os
from pathlib import Path, PurePosixPath
from typing import Any

import pytest

import marimo_studio._artifacts.publication as publication_module
import marimo_studio._filesystem.files as files
from marimo_studio._artifacts.codec import read_json
from marimo_studio._artifacts.paths import (
    artifact_root,
    ensure_secure_directory,
    read_secure_bytes,
)
from marimo_studio._artifacts.repository import (
    read_artifact_revision,
    read_published_artifact,
)
from marimo_studio._artifacts.retention import lease_published_artifact
from marimo_studio._filesystem.paths import PORTABLE_PATH_COMPONENT_MAX_BYTES
from marimo_studio._views.build import publish_view as publish_artifact_lease
from marimo_studio.errors import ConfigurationError, ViewProjectError
from marimo_studio.view_providers import (
    BuildRequest,
    BuildResult,
)
from marimo_studio.view_providers._host import provider_registry

from ..artifact_test_support import (
    add_provider_outputs,
    publish_artifact,
)
from ..artifact_test_support import (
    profile_path as _profile_path,
)
from ..artifact_test_support import (
    project as _project,
)

_MAX_COMPONENT_BYTES = PORTABLE_PATH_COMPONENT_MAX_BYTES


def _swap_after_open(
    monkeypatch: pytest.MonkeyPatch,
    directory: Path,
    external: Path,
) -> list[Path]:
    """Replace ``directory`` with a symlink once an operation has opened it.

    Returns the list that receives the retired directory after the swap.
    """
    open_directory = files.open_directory
    retired: list[Path] = []

    def swap(name: str | Path, *, path: Path, parent: int | None = None) -> int:
        descriptor = open_directory(name, path=path, parent=parent)
        if path == directory and not retired:
            retired.append(directory.with_name(f"{directory.name}-retired"))
            directory.rename(retired[0])
            directory.symlink_to(external, target_is_directory=True)
        return descriptor

    monkeypatch.setattr(files, "open_directory", swap)
    return retired


@pytest.mark.supported_python
def test_publication_builds_a_max_component_asset(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _project(tmp_path)
    relative = PurePosixPath("a" * _MAX_COMPONENT_BYTES)
    add_provider_outputs(monkeypatch, project, {relative: b"max component"})

    artifact = publish_artifact(project, "development")

    assert artifact.root.joinpath(*relative.parts).read_bytes() == b"max component"
    assert relative in {item.path for item in artifact.files}


@pytest.mark.skipif(
    os.name == "nt", reason="symlink creation needs elevated Windows access"
)
def test_provider_scratch_symlinks_are_discarded_before_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _project(tmp_path)
    provider = provider_registry().get(project.provider)
    build = provider.build

    def build_with_scratch(request: Any) -> Any:
        dependency = request.staging_root.parent / "work" / "node_modules" / "provider"
        dependency.parent.mkdir(parents=True)
        dependency.symlink_to(project.root, target_is_directory=True)
        return build(request)

    monkeypatch.setattr(provider, "build", build_with_scratch)

    artifact = publish_artifact(project, "development")

    assert {path.name for path in artifact.root.parent.iterdir()} == {
        "artifact.json",
        "files",
    }


def test_publication_detaches_provider_hardlinks_from_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _project(tmp_path)
    provider = provider_registry().get(project.provider)
    build = provider.build
    cache_file: Path | None = None

    def build_with_cache_alias(request: BuildRequest) -> BuildResult:
        nonlocal cache_file
        report = build(request)
        output = request.staging_root / "index.html"
        cache_file = request.cache_root / "hardlink-source.html"
        cache_file.write_bytes(output.read_bytes())
        output.unlink()
        os.link(cache_file, output)
        return report

    monkeypatch.setattr(provider, "build", build_with_cache_alias)

    with publish_artifact_lease(project, "development") as lease:
        artifact_file = lease.artifact.root / "index.html"
        expected = artifact_file.read_bytes()
        assert cache_file is not None
        assert not os.path.samestat(artifact_file.stat(), cache_file.stat())
        cache_file.write_bytes(b"mutated cache alias")
        assert artifact_file.read_bytes() == expected


def test_provider_output_changed_after_ingestion_does_not_reach_the_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _project(tmp_path)
    ingest = publication_module.ingest_publication_files
    changed = False

    def ingest_then_change(*arguments: Any) -> Any:
        nonlocal changed
        ingested = ingest(*arguments)
        _project_view, files_root, _destination = arguments
        (files_root / "index.html").write_text("changed later", encoding="utf-8")
        changed = True
        return ingested

    monkeypatch.setattr(
        publication_module, "ingest_publication_files", ingest_then_change
    )

    with publish_artifact_lease(project, "development") as lease:
        published = (lease.artifact.root / "index.html").read_text(encoding="utf-8")
        lease.verify()

    assert changed
    assert published != "changed later"


@pytest.mark.skipif(
    os.name == "nt", reason="symlink creation needs elevated Windows access"
)
def test_ingestion_copies_the_files_root_it_opened(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _project(tmp_path)
    external = tmp_path / "external"
    external.mkdir()
    (external / "index.html").write_text("external", encoding="utf-8")
    copy_tree = files.copy_tree
    roots: list[Path] = []

    def swap_files_root_then_copy(source: Any, destination: Any, **options: Any) -> Any:
        files_root = next(project.root.rglob("build/files"))
        files_root.rename(files_root.with_name("provider-files"))
        files_root.symlink_to(external, target_is_directory=True)
        roots.append(files_root)
        return copy_tree(source, destination, **options)

    monkeypatch.setattr(files, "copy_tree", swap_files_root_then_copy)

    artifact = publish_artifact(project, "development")

    assert roots
    assert (artifact.root / "index.html").read_text(encoding="utf-8") != "external"
    assert (external / "index.html").read_text(encoding="utf-8") == "external"


@pytest.mark.skipif(
    os.name == "nt", reason="symlink creation needs elevated Windows access"
)
@pytest.mark.parametrize(
    "control",
    (".artifacts", "revisions", ".staging", ".cache"),
)
def test_artifact_publication_rejects_symlinked_control_directories(
    tmp_path: Path,
    control: str,
) -> None:
    project = _project(tmp_path)
    external = tmp_path / "external"
    external.mkdir()
    if control == ".artifacts":
        artifact_root(project).symlink_to(external, target_is_directory=True)
    else:
        artifact_root(project).mkdir()
        (artifact_root(project) / control).symlink_to(
            external, target_is_directory=True
        )

    with pytest.raises(ConfigurationError, match="symlink"):
        publish_artifact(project, "development")
    assert tuple(external.iterdir()) == ()


@pytest.mark.skipif(
    os.name == "nt", reason="symlink creation needs elevated Windows access"
)
def test_cache_creation_stays_in_the_control_root_it_opened(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _project(tmp_path)
    control = artifact_root(project)
    control.mkdir()
    external = tmp_path / "external"
    external.mkdir()
    retired = _swap_after_open(monkeypatch, control, external)

    ensure_secure_directory(project.root, control / ".cache", "Artifact provider cache")

    assert retired
    assert (retired[0] / ".cache").is_dir()
    assert tuple(external.iterdir()) == ()


@pytest.mark.skipif(
    os.name == "nt", reason="symlink creation needs elevated Windows access"
)
def test_artifact_lock_creation_cannot_follow_a_raced_control_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _project(tmp_path)
    external = tmp_path / "external"
    external.mkdir()
    retired = _swap_after_open(monkeypatch, artifact_root(project), external)

    with pytest.raises((ConfigurationError, ViewProjectError)):
        publish_artifact(project, "development")

    assert retired
    assert tuple(external.iterdir()) == ()


@pytest.mark.skipif(
    os.name == "nt", reason="symlink creation needs elevated Windows access"
)
def test_artifact_pin_creation_cannot_follow_a_raced_revision_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _project(tmp_path)
    artifact = publish_artifact(project, "development")
    external = tmp_path / "external"
    external.mkdir()
    pins = (
        artifact_root(project)
        / ".pins"
        / artifact.artifact_revision.removeprefix("sha256:")
    )
    retired = _swap_after_open(monkeypatch, pins, external)

    with pytest.raises(ConfigurationError, match="symlink"):
        lease_published_artifact(project, "development")

    assert retired
    assert tuple(external.iterdir()) == ()


@pytest.mark.skipif(
    os.name == "nt", reason="symlink creation needs elevated Windows access"
)
def test_artifact_install_cannot_follow_a_raced_revisions_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _project(tmp_path)
    external = tmp_path / "external"
    external.mkdir()
    retired = _swap_after_open(
        monkeypatch, artifact_root(project) / "revisions", external
    )

    with pytest.raises((ConfigurationError, ViewProjectError)):
        publish_artifact(project, "development")

    assert retired
    assert tuple(external.iterdir()) == ()


@pytest.mark.skipif(
    os.name == "nt", reason="symlink creation needs elevated Windows access"
)
@pytest.mark.parametrize("lock_name", (".publication.lock", ".build.lock"))
def test_artifact_publication_rejects_a_symlinked_lock_file(
    tmp_path: Path,
    lock_name: str,
) -> None:
    project = _project(tmp_path)
    artifact_root(project).mkdir()
    external = tmp_path / "external.lock"
    external.write_text("", encoding="utf-8")
    (artifact_root(project) / lock_name).symlink_to(external)

    with pytest.raises(ConfigurationError, match="symlink"):
        publish_artifact(project, "development")


@pytest.mark.skipif(
    os.name == "nt", reason="symlink creation needs elevated Windows access"
)
def test_artifact_read_rejects_a_symlinked_profile_receipt(tmp_path: Path) -> None:
    project = _project(tmp_path)
    publish_artifact(project, "development")
    pointer = _profile_path(project)
    external = tmp_path / "external-profile.json"
    pointer.replace(external)
    pointer.symlink_to(external)

    with pytest.raises(ConfigurationError, match="symlink"):
        read_published_artifact(project, "development")


@pytest.mark.skipif(
    os.name == "nt", reason="symlink creation needs elevated Windows access"
)
def test_artifact_read_rejects_symlinked_revision_files(tmp_path: Path) -> None:
    project = _project(tmp_path)
    artifact = publish_artifact(project, "development")
    path = artifact.root / artifact.document
    external = tmp_path / "external.html"
    external.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    path.unlink()
    path.symlink_to(external)

    with pytest.raises(ConfigurationError, match="symlink"):
        read_artifact_revision(project, artifact.artifact_revision)


@pytest.mark.skipif(
    os.name == "nt", reason="symlink creation needs elevated Windows access"
)
def test_artifact_input_read_keeps_an_open_parent_when_project_root_is_swapped(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _project(tmp_path)
    source = project.root / "index.html"
    expected = source.read_bytes()
    retired = project.root.with_name("view-retired")
    external = tmp_path / "external-view"
    external.mkdir()
    (external / "index.html").write_text("SECRET", encoding="utf-8")
    open_file = files.os.open
    swapped = False

    def replace_root_then_open(
        path: os.PathLike[str] | str,
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        nonlocal swapped
        if Path(path).name == source.name and dir_fd is not None and not swapped:
            swapped = True
            project.root.rename(retired)
            project.root.symlink_to(external, target_is_directory=True)
        return open_file(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(files.os, "open", replace_root_then_open)

    payload = read_secure_bytes(project.root, source, "View project input")

    assert payload == expected
    assert (external / "index.html").read_text(encoding="utf-8") == "SECRET"


@pytest.mark.skipif(
    os.name == "nt", reason="symlink creation needs elevated Windows access"
)
@pytest.mark.parametrize("control", ("receipt", "manifest"))
def test_artifact_control_read_keeps_its_parent_when_project_root_is_swapped(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    control: str,
) -> None:
    project = _project(tmp_path)
    artifact = publish_artifact(project, "development")
    path = (
        _profile_path(project)
        if control == "receipt"
        else artifact.root.parent / "artifact.json"
    )
    expected = read_json(project.root, path, f"artifact {control}")
    relative = path.relative_to(project.root)
    retired = project.root.with_name("view-retired")
    external = tmp_path / "external-view"
    replacement = external / relative
    replacement.parent.mkdir(parents=True)
    replacement.write_text('{"secret":true}', encoding="utf-8")
    open_file = files.os.open
    swapped = False

    def replace_root_then_open(
        selected: os.PathLike[str] | str,
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        nonlocal swapped
        if Path(selected).name == path.name and dir_fd is not None and not swapped:
            swapped = True
            project.root.rename(retired)
            project.root.symlink_to(external, target_is_directory=True)
        return open_file(selected, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(files.os, "open", replace_root_then_open)

    value = read_json(project.root, path, f"artifact {control}")

    assert value == expected
