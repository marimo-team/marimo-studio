"""Exercise artifact candidate isolation and filesystem safety."""

from __future__ import annotations

import os
import shutil
from pathlib import Path, PurePosixPath
from typing import Any

import pytest

import marimo_studio._artifacts.publication as publication_module
import marimo_studio._filesystem.secure as secure_files
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


def test_publication_rejects_a_hardlink_added_after_detachment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _project(tmp_path)
    detach = publication_module.detach_public_files
    external_source = tmp_path / "late-artifact-source.html"
    linked = False

    def detach_then_link(files_root: Path) -> None:
        nonlocal linked
        detach(files_root)
        candidate = files_root / "index.html"
        external_source.write_bytes(candidate.read_bytes())
        candidate.unlink()
        try:
            os.link(external_source, candidate)
        except OSError as error:
            pytest.skip(f"Hard links are unavailable: {error}")
        linked = True

    monkeypatch.setattr(
        publication_module,
        "detach_public_files",
        detach_then_link,
    )

    with pytest.raises(ViewProjectError, match="revision-owned inode"):
        publish_artifact(project, "development")

    assert linked
    assert read_published_artifact(project, "development") is None


@pytest.mark.skipif(
    os.name == "nt", reason="symlink creation needs elevated Windows access"
)
def test_detachment_cannot_mutate_a_raced_external_files_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _project(tmp_path)
    external = tmp_path / "external"
    external.mkdir()
    external_file = external / "index.html"
    external_file.write_text("external", encoding="utf-8")
    inventory = secure_files.SecureDirectory.regular_file_sizes
    raced = False

    def replace_files_root_after_inventory(
        filesystem: secure_files.SecureDirectory,
        *,
        max_entries: int,
    ) -> tuple[tuple[Path, int], ...]:
        nonlocal raced
        files = inventory(filesystem, max_entries=max_entries)
        if filesystem.root.name == "files" and not raced:
            raced = True
            retired = filesystem.root.with_name("provider-files")
            filesystem.root.rename(retired)
            filesystem.root.symlink_to(external, target_is_directory=True)
        return files

    monkeypatch.setattr(
        secure_files.SecureDirectory,
        "regular_file_sizes",
        replace_files_root_after_inventory,
    )

    with pytest.raises(ViewProjectError, match="Could not open Artifact document"):
        publish_artifact(project, "development")

    assert raced
    assert external_file.read_text(encoding="utf-8") == "external"


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
def test_cache_creation_cannot_follow_a_raced_artifact_symlink(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _project(tmp_path)
    control = artifact_root(project)
    control.mkdir()
    external = tmp_path / "external"
    external.mkdir()
    ensure = secure_files.SecureDirectory.ensure_directory
    raced = False

    def replace_control_then_create(
        filesystem: secure_files.SecureDirectory,
        path: Path,
    ) -> tuple[Path, ...]:
        nonlocal raced
        if not raced:
            raced = True
            control.rmdir()
            control.symlink_to(external, target_is_directory=True)
        return ensure(filesystem, path)

    monkeypatch.setattr(
        secure_files.SecureDirectory,
        "ensure_directory",
        replace_control_then_create,
    )

    with pytest.raises(ConfigurationError, match="Could not create"):
        ensure_secure_directory(
            project.root,
            control / ".cache",
            "Artifact provider cache",
        )

    assert raced
    assert tuple(external.iterdir()) == ()


@pytest.mark.skipif(
    os.name == "nt", reason="symlink creation needs elevated Windows access"
)
def test_artifact_lock_creation_cannot_follow_a_raced_control_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _project(tmp_path)
    control = artifact_root(project)
    external = tmp_path / "external"
    external.mkdir()
    open_lock = secure_files.SecureDirectory.open_or_create_file
    raced = False

    def replace_control_then_open(
        filesystem: secure_files.SecureDirectory,
        path: Path,
        mode: int = 0o600,
    ) -> int:
        nonlocal raced
        if path.parent == control and not raced:
            raced = True
            shutil.rmtree(control)
            control.symlink_to(external, target_is_directory=True)
        return open_lock(filesystem, path, mode)

    monkeypatch.setattr(
        secure_files.SecureDirectory,
        "open_or_create_file",
        replace_control_then_open,
    )

    with pytest.raises((ConfigurationError, ViewProjectError)):
        publish_artifact(project, "development")

    assert raced
    assert tuple(external.iterdir()) == ()


@pytest.mark.skipif(
    os.name == "nt", reason="symlink creation needs elevated Windows access"
)
def test_artifact_pin_creation_cannot_follow_a_raced_revision_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _project(tmp_path)
    publish_artifact(project, "development")
    external = tmp_path / "external"
    external.mkdir()
    create_pin = secure_files.SecureDirectory.create_file
    raced = False

    def replace_revision_then_create(
        filesystem: secure_files.SecureDirectory,
        path: Path,
        mode: int = 0o600,
    ) -> int:
        nonlocal raced
        if ".pins" in path.parts and not raced:
            raced = True
            path.parent.rmdir()
            path.parent.symlink_to(external, target_is_directory=True)
        return create_pin(filesystem, path, mode)

    monkeypatch.setattr(
        secure_files.SecureDirectory,
        "create_file",
        replace_revision_then_create,
    )

    with pytest.raises(ConfigurationError, match="artifact pin"):
        lease_published_artifact(project, "development")

    assert raced
    assert tuple(external.iterdir()) == ()


@pytest.mark.skipif(
    os.name == "nt", reason="symlink creation needs elevated Windows access"
)
def test_artifact_install_cannot_follow_a_raced_revisions_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _project(tmp_path)
    revisions = artifact_root(project) / "revisions"
    external = tmp_path / "external"
    external.mkdir()
    replace = secure_files.SecureDirectory.replace
    raced = False

    def replace_revisions_then_install(
        filesystem: secure_files.SecureDirectory,
        source: Path,
        destination: Path,
    ) -> None:
        nonlocal raced
        if destination.parent == revisions and not raced:
            raced = True
            revisions.rmdir()
            revisions.symlink_to(external, target_is_directory=True)
        replace(filesystem, source, destination)

    monkeypatch.setattr(
        secure_files.SecureDirectory,
        "replace",
        replace_revisions_then_install,
    )

    with pytest.raises((ConfigurationError, ViewProjectError)):
        publish_artifact(project, "development")

    assert raced
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
    open_file = secure_files.os.open
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

    monkeypatch.setattr(secure_files.os, "open", replace_root_then_open)

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
    open_file = secure_files.os.open
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

    monkeypatch.setattr(secure_files.os, "open", replace_root_then_open)

    value = read_json(project.root, path, f"artifact {control}")

    assert value == expected
