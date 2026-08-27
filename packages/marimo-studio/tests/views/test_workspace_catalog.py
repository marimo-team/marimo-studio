from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

import marimo_studio._filesystem.secure as secure_files
import marimo_studio._workspace.config as workspace_config
from marimo_studio._views.api import prepare_view
from marimo_studio._views.inspection import inspection_request
from marimo_studio._views.resolve import resolve_studio
from marimo_studio._workspace import load_studio
from marimo_studio._workspace.mutation_lock import (
    view_mutation_lock,
    workspace_catalog_lock,
)
from marimo_studio.errors import (
    ConfigurationError,
)
from marimo_studio.view_providers._host import provider_registry


def test_view_inventory_ignores_a_project_removed_during_load(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "views"
    for name in ("gone", "stable"):
        directory = root / name
        directory.mkdir(parents=True)
        (directory / "view.toml").write_text(
            'schema = 1\nprovider = "marimo-studio/vanilla"\n',
            encoding="utf-8",
        )
        (directory / "index.html").write_text(
            '<main id="app-shell"></main>',
            encoding="utf-8",
        )
    native_load = workspace_config.load_view_project

    def load(directory: Path):
        if directory.name == "gone":
            shutil.rmtree(directory)
            raise ConfigurationError(f"View project manifest is missing: {directory}")
        return native_load(directory)

    monkeypatch.setattr(workspace_config, "load_view_project", load)

    assert set(workspace_config.discover_views(root)) == {"stable"}


def test_explicit_mounts_resolve_without_provider_inspection(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepare_view(notebook_path)
    studio = load_studio(notebook_path)
    project = studio.views["dashboard"]
    provider = provider_registry().get(project.provider)
    inspection = provider.inspect(inspection_request(project))

    def unexpected_inspection(_project):
        raise AssertionError("explicit projection sites triggered inspection")

    monkeypatch.setattr(provider, "inspect", unexpected_inspection)

    resolved = resolve_studio(
        studio,
        view_name="dashboard",
        published_mounts={"dashboard": inspection.mounts},
    )

    assert resolved.view("dashboard").mounts == inspection.mounts


def test_view_mutation_lock_is_reentrant_for_nested_same_thread_owners(
    tmp_path: Path,
) -> None:
    view_root = tmp_path / "views"

    with (
        view_mutation_lock(view_root, "dashboard"),
        view_mutation_lock(view_root, "dashboard"),
    ):
        assert (view_root / ".locks" / "dashboard.lock").is_file()


def test_workspace_catalog_lock_rejects_view_to_catalog_order_inversion(
    tmp_path: Path,
) -> None:
    view_root = tmp_path / "views"

    with (
        view_mutation_lock(view_root, "dashboard"),
        pytest.raises(RuntimeError, match="catalog lock before view locks"),
        workspace_catalog_lock(view_root),
    ):
        pytest.fail("catalog lock must reject inverted ordering")


@pytest.mark.skipif(
    os.name == "nt", reason="symlink creation needs elevated Windows access"
)
def test_workspace_catalog_lock_rejects_a_symlinked_lock_file(
    tmp_path: Path,
) -> None:
    view_root = tmp_path / "views"
    control = view_root / ".locks"
    control.mkdir(parents=True)
    external = tmp_path / "external.lock"
    external.write_text("external", encoding="utf-8")
    (control / ".catalog.lock").symlink_to(external)

    with (
        pytest.raises(ConfigurationError, match="symlink"),
        workspace_catalog_lock(view_root),
    ):
        pytest.fail("catalog lock must reject symlinks")

    assert external.read_text(encoding="utf-8") == "external"


@pytest.mark.skipif(
    os.name == "nt", reason="symlink creation needs elevated Windows access"
)
def test_workspace_lock_creation_cannot_follow_a_raced_view_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    view_root = tmp_path / "views"
    external = tmp_path / "external"
    external.mkdir()
    ensure = secure_files.SecureDirectory.ensure_directory
    raced = False

    def replace_root_then_create(
        filesystem: secure_files.SecureDirectory,
        path: Path,
    ) -> tuple[Path, ...]:
        nonlocal raced
        if path == view_root and not raced:
            raced = True
            view_root.symlink_to(external, target_is_directory=True)
        return ensure(filesystem, path)

    monkeypatch.setattr(
        secure_files.SecureDirectory,
        "ensure_directory",
        replace_root_then_create,
    )

    with (
        pytest.raises(ConfigurationError, match="mutation lock"),
        workspace_catalog_lock(view_root),
    ):
        pytest.fail("raced workspace lock must not be acquired")

    assert raced
    assert tuple(external.iterdir()) == ()
