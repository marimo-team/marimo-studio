from __future__ import annotations

import multiprocessing
import os
import shutil
from collections.abc import MutableMapping
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest

import marimo_studio._filesystem.secure as secure_files
import marimo_studio._views.remove as workspace_views
from marimo_studio._views.api import prepare_view
from marimo_studio._views.remove import delete_view
from marimo_studio._workspace import load_studio
from marimo_studio._workspace.config import load_studio_definition
from marimo_studio._workspace.metadata import (
    update_notebook_config,
)
from marimo_studio._workspace.models import StudioWorkspace
from marimo_studio.errors import ConfigurationError, LastViewError, ViewNotFoundError
from marimo_studio.errors._internal import ViewDeletionError

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
        except LastViewError:
            return "last-view"
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
    assert sorted(results) == ["deleted", "last-view"]
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


def test_view_deletion_rolls_back_when_updated_workspace_cannot_load(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepare_view(notebook_path)
    prepare_view(notebook_path, "executive")
    studio = load_studio(notebook_path)
    original_notebook = notebook_path.read_bytes()
    original_document = (studio.views["dashboard"].root / "index.html").read_bytes()
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
    assert calls == 2
    assert notebook_path.read_bytes() == original_notebook
    assert restored.default_view == "dashboard"
    assert tuple(restored.views) == ("dashboard", "executive")
    assert (
        restored.views["dashboard"].root / "index.html"
    ).read_bytes() == original_document


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

    assert edited
    assert document.read_text(encoding="utf-8") == changed
    assert "executive" in load_studio(notebook_path).views


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

    assert removed
    assert tuple(load_studio(notebook_path).views) == ("dashboard",)


def test_view_deletion_keeps_partial_cleanup_outside_the_workspace(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepare_view(notebook_path)
    prepare_view(notebook_path, "executive")
    studio = load_studio(notebook_path)

    def fail_cleanup(
        filesystem: workspace_views.SecureDirectory,
        path: Path,
    ) -> None:
        filesystem.unlink(path / "dashboard" / "src" / "index.html")
        raise PermissionError("simulated Windows handle")

    monkeypatch.setattr(workspace_views.SecureDirectory, "remove_tree", fail_cleanup)

    with pytest.raises(ViewDeletionError, match="cleanup is incomplete") as captured:
        delete_view(studio, "dashboard")

    updated = load_studio(notebook_path)
    assert updated.default_view == "executive"
    assert tuple(updated.views) == ("executive",)
    assert not (studio.view_root / "dashboard").exists()
    cleanup = captured.value.cleanup
    assert cleanup is not None and cleanup.is_dir()
    assert not cleanup.joinpath("dashboard", "src", "index.html").exists()


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
    assert raced
    assert actual == expected


def test_notebooks_with_the_same_parent_have_independent_presentations(
    notebook_path: Path,
) -> None:
    second = notebook_path.with_name("forecast.py")
    second.write_text(notebook_path.read_text(encoding="utf-8"), encoding="utf-8")

    prepare_view(notebook_path, "dashboard")
    prepare_view(second, "forecast")

    first_studio = load_studio(notebook_path)
    second_studio = load_studio(second)
    assert first_studio.view_root != second_studio.view_root
    assert set(first_studio.views) == {"dashboard"}
    assert set(second_studio.views) == {"forecast"}


def test_directory_discovery_requires_an_explicit_notebook_on_conflict(
    notebook_path: Path,
) -> None:
    inline = notebook_path.with_name("inline.py")
    inline.write_text(notebook_path.read_text(encoding="utf-8"), encoding="utf-8")
    prepare_view(inline)
    (notebook_path.parent / "pyproject.toml").write_text(
        f"""\
[tool.marimo-studio]
notebook = "{notebook_path.name}"
default = "dashboard"
""",
        encoding="utf-8",
    )

    with pytest.raises(ConfigurationError, match="Pass a notebook path"):
        load_studio_definition(notebook_path.parent)

    assert load_studio_definition(inline).notebook == inline


def test_notebook_configuration_controls_presentation_options(
    notebook_path: Path,
) -> None:
    prepare_view(notebook_path)

    def configure(config: MutableMapping[str, object]) -> None:
        config["preserve_session"] = True
        config["show_cell_logs"] = False
        config["runtime"] = "wasm"
        config["runtimes"] = ["server", "wasm"]

    update_notebook_config(notebook_path, configure)
    studio = load_studio(notebook_path)
    assert studio.preserve_session is True
    assert studio.show_cell_logs is False
    assert studio.default_runtime == "wasm"
    assert studio.runtimes == ("server", "wasm")

    def invalidate_session(config: MutableMapping[str, object]) -> None:
        config["preserve_session"] = "yes"

    update_notebook_config(notebook_path, invalidate_session)
    with pytest.raises(ConfigurationError, match="preserve_session must be a boolean"):
        load_studio(notebook_path)

    def invalidate_logs(config: MutableMapping[str, object]) -> None:
        config["preserve_session"] = True
        config["show_cell_logs"] = "no"

    update_notebook_config(notebook_path, invalidate_logs)
    with pytest.raises(ConfigurationError, match="show_cell_logs must be a boolean"):
        load_studio(notebook_path)

    def remove_default(config: MutableMapping[str, object]) -> None:
        config["show_cell_logs"] = False
        config["runtimes"] = ["server"]

    update_notebook_config(notebook_path, remove_default)
    with pytest.raises(ConfigurationError, match="runtime must be present"):
        load_studio(notebook_path)
