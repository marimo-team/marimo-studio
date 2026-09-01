from __future__ import annotations

import multiprocessing
import os
import shutil
from collections.abc import Iterator
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from threading import Barrier
from typing import Any

import pytest

import marimo_studio._filesystem.secure as secure_files
import marimo_studio._views.remove as workspace_views
import marimo_studio._workspace.generation as workspace_generation
from marimo_studio._views.api import prepare_view
from marimo_studio._views.remove import delete_view
from marimo_studio._workspace import load_studio
from marimo_studio._workspace.models import StudioWorkspace
from marimo_studio._workspace.view_owners import load_view_owner, view_owner_path
from marimo_studio.errors import (
    ConfigurationError,
    LastViewError,
    ViewDeletionError,
    ViewGenerationConflictError,
    ViewNotFoundError,
    WorkspaceGenerationConflictError,
)

from ._workspace_lifecycle_support import (
    _project_configuration,
    _write_before_transaction,
)
from .workspace_test_support import (
    _delete_view_in_process,
)


def test_concurrent_thread_deletion_keeps_one_final_view(
    notebook_path: Path,
) -> None:
    prepare_view(notebook_path)
    prepare_view(notebook_path, "executive")
    studio = load_studio(notebook_path)
    start = Barrier(2)

    def remove(name: str) -> str:
        start.wait()
        try:
            delete_view(studio, name)
        except (
            LastViewError,
            ViewGenerationConflictError,
            WorkspaceGenerationConflictError,
        ):
            return "conflict"
        return "deleted"

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = tuple(
            future.result()
            for future in (
                executor.submit(remove, "dashboard"),
                executor.submit(remove, "executive"),
            )
        )

    updated = load_studio(notebook_path)
    assert sorted(results) == ["conflict", "deleted"]
    assert len(updated.views) == 1
    assert updated.default_view in updated.views


@pytest.mark.native_process
def test_spawn_process_deletion_preserves_default_for_remaining_view(
    notebook_path: Path,
    tmp_path: Path,
) -> None:
    prepare_view(notebook_path)
    prepare_view(notebook_path, "executive")
    prepare_view(notebook_path, "operations")
    signals = tmp_path / "delete-signals"
    signals.mkdir()
    context = multiprocessing.get_context("spawn")

    with ProcessPoolExecutor(max_workers=2, mp_context=context) as executor:
        results = tuple(
            future.result()
            for future in (
                executor.submit(
                    _delete_view_in_process,
                    str(notebook_path),
                    "dashboard",
                    str(signals),
                    2,
                ),
                executor.submit(
                    _delete_view_in_process,
                    str(notebook_path),
                    "executive",
                    str(signals),
                    2,
                ),
            )
        )

    updated = load_studio(notebook_path)
    assert results == ("deleted", "deleted")
    assert tuple(updated.views) == ("operations",)
    assert updated.default_view == "operations"
    assert load_view_owner(updated.view_root, "dashboard").present is False
    assert load_view_owner(updated.view_root, "executive").present is False
    assert load_view_owner(updated.view_root, "operations").present is True


def test_view_deletion_rolls_back_when_updated_workspace_cannot_load(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepare_view(notebook_path)
    prepare_view(notebook_path, "executive")
    studio = load_studio(notebook_path)
    original_notebook = notebook_path.read_bytes()
    original_document = (studio.views["dashboard"].root / "index.html").read_bytes()
    owner_path = view_owner_path(studio.view_root, "dashboard")
    original_owner = owner_path.read_bytes()
    load = workspace_views.load_studio
    calls = 0

    def fail_updated_workspace(path: Path) -> StudioWorkspace:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise ConfigurationError("forced updated workspace load failure")
        return load(path)

    monkeypatch.setattr(workspace_views, "load_studio", fail_updated_workspace)

    with pytest.raises(ConfigurationError, match="forced updated workspace"):
        delete_view(studio, "dashboard")

    restored = load_studio(notebook_path)
    assert notebook_path.read_bytes() == original_notebook
    assert restored.default_view == "dashboard"
    assert tuple(restored.views) == ("dashboard", "executive")
    assert owner_path.read_bytes() == original_owner
    assert (
        restored.views["dashboard"].root / "index.html"
    ).read_bytes() == original_document


def test_view_deletion_reports_recovery_when_tombstone_cleanup_fails(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepare_view(notebook_path)
    prepare_view(notebook_path, "executive")
    studio = load_studio(notebook_path)
    load = workspace_views.load_studio
    remove_tree = workspace_views.SecureDirectory.remove_tree
    calls = 0

    def fail_updated_workspace(path: Path) -> StudioWorkspace:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise ConfigurationError("forced updated workspace load failure")
        return load(path)

    def fail_tombstone_cleanup(
        filesystem: workspace_views.SecureDirectory,
        path: Path,
    ) -> None:
        if path.joinpath(".marimo-studio-tombstone").is_file():
            raise PermissionError("simulated Windows handle")
        remove_tree(filesystem, path)

    monkeypatch.setattr(workspace_views, "load_studio", fail_updated_workspace)
    monkeypatch.setattr(
        workspace_views.SecureDirectory,
        "remove_tree",
        fail_tombstone_cleanup,
    )

    with pytest.raises(ViewDeletionError) as captured:
        delete_view(studio, "dashboard")

    recovery = captured.value.recovery
    assert recovery is not None
    assert recovery.joinpath("view.toml").is_file()


def test_view_deletion_restores_before_candidate_cleanup(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepare_view(notebook_path)
    prepare_view(notebook_path, "executive")
    studio = load_studio(notebook_path)
    target = studio.views["executive"].root
    rename = workspace_views.SecureDirectory.rename_if_absent
    remove_tree = workspace_views.SecureDirectory.remove_tree

    def fail_tombstone_publication(
        filesystem: workspace_views.SecureDirectory,
        source: Path,
        destination: Path,
    ) -> None:
        if source.name == ".tombstone" and destination == target:
            raise PermissionError("simulated tombstone publication failure")
        rename(filesystem, source, destination)

    def fail_candidate_cleanup(
        filesystem: workspace_views.SecureDirectory,
        path: Path,
    ) -> None:
        if path.name == ".tombstone":
            raise PermissionError("simulated candidate cleanup failure")
        remove_tree(filesystem, path)

    monkeypatch.setattr(
        workspace_views.SecureDirectory,
        "rename_if_absent",
        fail_tombstone_publication,
    )
    monkeypatch.setattr(
        workspace_views.SecureDirectory,
        "remove_tree",
        fail_candidate_cleanup,
    )

    with pytest.raises(ViewDeletionError):
        delete_view(studio, "executive")

    assert target.joinpath("view.toml").is_file()
    assert tuple(load_studio(notebook_path).views) == ("dashboard", "executive")


def test_view_deletion_preserves_a_source_edit_at_the_commit_boundary(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepare_view(notebook_path)
    prepare_view(notebook_path, "executive")
    studio = load_studio(notebook_path)
    target = studio.views["executive"].root
    document = target / "index.html"
    changed = "<!doctype html><title>concurrent edit</title>\n"
    replace = secure_files.SecureDirectory.replace
    edited = False

    def edit_then_replace(
        filesystem: secure_files.SecureDirectory,
        source: Path,
        destination: Path,
    ) -> None:
        nonlocal edited
        if source == target and not edited:
            edited = True
            document.write_text(changed, encoding="utf-8")
        replace(filesystem, source, destination)

    monkeypatch.setattr(secure_files.SecureDirectory, "replace", edit_then_replace)

    with pytest.raises(ConfigurationError, match="changed before deletion"):
        delete_view(studio, "executive")

    assert document.read_text(encoding="utf-8") == changed
    assert "executive" in load_studio(notebook_path).views


def test_stale_view_generation_cannot_delete_a_replacement(
    notebook_path: Path,
) -> None:
    prepare_view(notebook_path)
    prepare_view(notebook_path, "executive")
    observed = load_studio(notebook_path)
    target = observed.views["executive"].root
    replacement = "<!doctype html><title>replacement</title>"
    shutil.rmtree(target)
    target.mkdir()
    target.joinpath("view.toml").write_text(
        'schema = 1\nprovider = "marimo-studio/vanilla"\n',
        encoding="utf-8",
    )
    target.joinpath("index.html").write_text(
        replacement,
        encoding="utf-8",
    )

    current = load_studio(notebook_path)
    with pytest.raises(ViewGenerationConflictError):
        delete_view(
            observed,
            "executive",
            expected_catalog_generation=current.catalog_generation,
            expected_generation=observed.view_generations["executive"],
        )

    assert target.joinpath("index.html").read_text(encoding="utf-8") == replacement
    delete_view(
        current,
        "executive",
        expected_catalog_generation=current.catalog_generation,
        expected_generation=current.view_generations["executive"],
    )
    assert tuple(load_studio(notebook_path).views) == ("dashboard",)


def test_deleted_name_gets_a_fresh_owner_when_directory_identity_is_reused(
    notebook_path: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepare_view(notebook_path)
    prepare_view(notebook_path, "executive")
    monkeypatch.setattr(
        workspace_generation,
        "directory_generation",
        lambda _path: "forced-reused-directory-owner",
    )
    observed = load_studio(notebook_path)
    target = observed.views["executive"].root
    replacement = tmp_path / "byte-identical-replacement"
    shutil.copytree(target, replacement)

    delete_view(observed, "executive")
    assert load_view_owner(observed.view_root, "executive").present is False
    shutil.copytree(replacement, target)
    current = load_studio(notebook_path)

    assert (
        current.view_generations["executive"]
        != (observed.view_generations["executive"])
    )
    with pytest.raises(ViewGenerationConflictError):
        delete_view(
            current,
            "executive",
            expected_catalog_generation=current.catalog_generation,
            expected_generation=observed.view_generations["executive"],
        )


def test_view_deletion_reports_a_target_removed_before_its_claim(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepare_view(notebook_path)
    prepare_view(notebook_path, "executive")
    studio = load_studio(notebook_path)
    target = studio.views["executive"].root
    identity = secure_files.SecureDirectory.directory_tree_identity
    removed = False

    def remove_then_identify(
        filesystem: secure_files.SecureDirectory,
        path: Path,
        *,
        max_entries: int,
    ) -> tuple[tuple[object, ...], ...] | None:
        nonlocal removed
        if path == target and not removed:
            removed = True
            shutil.rmtree(target)
        return identity(filesystem, path, max_entries=max_entries)

    monkeypatch.setattr(
        secure_files.SecureDirectory,
        "directory_tree_identity",
        remove_then_identify,
    )

    with pytest.raises(ViewNotFoundError):
        delete_view(studio, "executive")

    assert tuple(load_studio(notebook_path).views) == ("dashboard",)


def test_view_deletion_keeps_partial_cleanup_outside_the_workspace(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepare_view(notebook_path)
    prepare_view(notebook_path, "executive")
    studio = load_studio(notebook_path)
    remove_tree = workspace_views.SecureDirectory.remove_tree
    removed: list[Path] = []

    def fail_cleanup(
        filesystem: workspace_views.SecureDirectory,
        path: Path,
    ) -> None:
        if any(child.name == "view.toml" for child in path.rglob("*")):
            victim = next(child for child in path.rglob("*") if child.is_file())
            removed.append(victim)
            filesystem.unlink(victim)
            raise PermissionError("simulated Windows handle")
        remove_tree(filesystem, path)

    monkeypatch.setattr(workspace_views.SecureDirectory, "remove_tree", fail_cleanup)

    with pytest.raises(ViewDeletionError, match="cleanup is incomplete") as captured:
        delete_view(studio, "dashboard")

    updated = load_studio(notebook_path)
    assert updated.default_view == "executive"
    assert tuple(updated.views) == ("executive",)
    assert not (studio.view_root / "dashboard").exists()
    cleanup = captured.value.cleanup
    assert cleanup is not None and cleanup.is_dir()
    assert removed and not removed[0].exists()


def test_view_deletion_rejects_a_symlinked_view_directory(
    notebook_path: Path,
) -> None:
    prepare_view(notebook_path)
    prepare_view(notebook_path, "executive")
    studio = load_studio(notebook_path)
    external = notebook_path.parent / "external-view"
    external.mkdir()
    (external / "index.html").write_text("external", encoding="utf-8")
    target = studio.view_root / "executive"
    shutil.rmtree(target)
    target.symlink_to(external, target_is_directory=True)

    with pytest.raises(ConfigurationError, match="symlink"):
        delete_view(studio, "executive")

    assert (external / "index.html").read_text(encoding="utf-8") == "external"


@pytest.mark.skipif(
    os.name == "nt", reason="symlink creation needs elevated Windows access"
)
def test_view_deletion_cannot_follow_a_raced_workspace_root(
    notebook_path: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepare_view(notebook_path)
    prepare_view(notebook_path, "executive")
    studio = load_studio(notebook_path)
    target = studio.view_root / "executive"
    external = tmp_path / "external"
    shutil.copytree(target, external / "executive")
    expected = {
        path.relative_to(external).as_posix(): path.read_bytes()
        for path in external.rglob("*")
        if path.is_file()
    }
    retired = studio.view_root.with_name(f"{studio.view_root.name}-retired")
    identity = secure_files.SecureDirectory.directory_tree_identity
    raced = False

    def replace_workspace_then_identify(
        filesystem: secure_files.SecureDirectory,
        path: Path,
        *,
        max_entries: int,
    ) -> tuple[tuple[object, ...], ...] | None:
        nonlocal raced
        if path == target and not raced:
            raced = True
            studio.view_root.rename(retired)
            studio.view_root.symlink_to(external, target_is_directory=True)
        return identity(filesystem, path, max_entries=max_entries)

    monkeypatch.setattr(
        secure_files.SecureDirectory,
        "directory_tree_identity",
        replace_workspace_then_identify,
    )

    try:
        with pytest.raises((ConfigurationError, OSError)):
            delete_view(studio, "executive")
    finally:
        if studio.view_root.is_symlink():
            studio.view_root.unlink()
        if retired.is_dir():
            retired.rename(studio.view_root)

    actual = {
        path.relative_to(external).as_posix(): path.read_bytes()
        for path in external.rglob("*")
        if path.is_file()
    }
    assert actual == expected


def test_view_deletion_rejects_a_concurrent_notebook_save(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepare_view(notebook_path)
    prepare_view(notebook_path, "executive")
    studio = load_studio(notebook_path)
    transaction = workspace_views.write_file_transaction
    changed = notebook_path.read_text(encoding="utf-8") + "# concurrent save\n"

    monkeypatch.setattr(
        workspace_views,
        "write_file_transaction",
        _write_before_transaction(transaction, notebook_path, changed),
    )

    with pytest.raises(ConfigurationError, match="changed"):
        delete_view(studio, "executive")

    assert notebook_path.read_text(encoding="utf-8") == changed
    restored = load_studio(notebook_path)
    assert restored.default_view == "dashboard"
    assert tuple(restored.views) == ("dashboard", "executive")


def test_view_deletion_rejects_a_concurrent_project_configuration_edit(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pyproject = _project_configuration(notebook_path)
    prepare_view(notebook_path)
    prepare_view(notebook_path, "executive")
    studio = load_studio(pyproject)
    transaction = workspace_views.write_file_transaction
    changed = pyproject.read_text(encoding="utf-8") + "# concurrent edit\n"

    monkeypatch.setattr(
        workspace_views,
        "write_file_transaction",
        _write_before_transaction(transaction, pyproject, changed),
    )

    with pytest.raises(ConfigurationError, match="changed"):
        delete_view(studio, "executive")

    assert pyproject.read_text(encoding="utf-8") == changed
    restored = load_studio(pyproject)
    assert restored.default_view == "dashboard"
    assert tuple(restored.views) == ("dashboard", "executive")


@pytest.mark.parametrize("timing", ("before", "during"))
def test_view_deletion_preserves_a_recreated_target_and_original_recovery(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    timing: str,
) -> None:
    prepare_view(notebook_path)
    prepare_view(notebook_path, "executive")
    studio = load_studio(notebook_path)
    target = studio.views["executive"].root
    original = target.joinpath("index.html").read_bytes()
    replacement = "<!doctype html><title>replacement</title>"
    transaction = workspace_views.write_file_transaction

    def recreate() -> None:
        if target.exists():
            shutil.rmtree(target)
        target.mkdir()
        target.joinpath("view.toml").write_text(
            'schema = 1\nprovider = "marimo-studio/vanilla"\n',
            encoding="utf-8",
        )
        target.joinpath("index.html").write_text(
            replacement,
            encoding="utf-8",
        )

    @contextmanager
    def recreate_around_transaction(*args: Any, **kwargs: Any) -> Iterator[None]:
        if timing == "before":
            recreate()
        with transaction(*args, **kwargs):
            yield
            if timing == "during":
                recreate()

    monkeypatch.setattr(
        workspace_views,
        "write_file_transaction",
        recreate_around_transaction,
    )

    with pytest.raises(ViewDeletionError, match="original project") as captured:
        delete_view(studio, "executive")

    assert target.joinpath("index.html").read_text(encoding="utf-8") == replacement
    assert captured.value.recovery is not None
    assert captured.value.recovery.joinpath("index.html").read_bytes() == original


def test_project_view_deletion_preserves_a_concurrent_notebook_edit(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pyproject = _project_configuration(notebook_path)
    prepare_view(notebook_path)
    prepare_view(notebook_path, "executive")
    studio = load_studio(pyproject)
    transaction = workspace_views.write_file_transaction
    changed = notebook_path.read_text(encoding="utf-8") + "# concurrent save\n"

    monkeypatch.setattr(
        workspace_views,
        "write_file_transaction",
        _write_before_transaction(transaction, notebook_path, changed),
    )

    updated = delete_view(studio, "executive")

    assert notebook_path.read_text(encoding="utf-8") == changed
    assert updated.default_view == "dashboard"
    assert tuple(updated.views) == ("dashboard",)
