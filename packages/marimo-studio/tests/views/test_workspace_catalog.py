from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

import marimo_studio._filesystem.files as files
import marimo_studio._workspace.config as workspace_config
from marimo_studio._views.api import prepare_view
from marimo_studio._views.inspection import inspection_request
from marimo_studio._views.resolve import resolve_studio
from marimo_studio._workspace import load_studio
from marimo_studio._workspace.mutation_lock import (
    view_mutation_lock,
    workspace_catalog_lock,
)
from marimo_studio._workspace.view_owners import view_owner_path
from marimo_studio.errors import (
    ConfigurationError,
    WorkspaceGenerationConflictError,
)
from marimo_studio.view_providers import ViewProject
from marimo_studio.view_providers._artifact_sites import artifact_sites
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


def test_a_misnamed_view_folder_is_a_configuration_error(notebook_path: Path) -> None:
    prepare_view(notebook_path)
    view_root = load_studio(notebook_path).view_root
    shutil.copytree(view_root / "dashboard", view_root / "Report")

    with pytest.raises(ConfigurationError) as failed:
        load_studio(notebook_path)

    assert failed.value.code == "configuration-error"
    assert "Report" in str(failed.value)


def test_an_invalid_default_view_is_a_configuration_error(notebook_path: Path) -> None:
    prepare_view(notebook_path)
    source = notebook_path.read_text(encoding="utf-8")
    notebook_path.write_text(
        source.replace('default = "dashboard"', 'default = "Dashboard"'),
        encoding="utf-8",
    )

    with pytest.raises(ConfigurationError) as failed:
        load_studio(notebook_path)

    assert failed.value.code == "configuration-error"
    assert notebook_path.name in str(failed.value)


@pytest.mark.parametrize("disappearance", ("owner", "directory"))
def test_workspace_materialization_reports_a_disappearing_view_as_a_conflict(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    disappearance: str,
) -> None:
    prepare_view(notebook_path)
    definition = workspace_config.load_studio_definition(notebook_path)
    generation = workspace_config.view_generation
    raced = False

    def disappear(project: ViewProject) -> str:
        nonlocal raced
        result = generation(project)
        if not raced:
            raced = True
            if disappearance == "owner":
                view_owner_path(definition.view_root, project.name).unlink()
            else:
                shutil.rmtree(project.root)
        return result

    monkeypatch.setattr(workspace_config, "view_generation", disappear)

    with pytest.raises(WorkspaceGenerationConflictError):
        workspace_config.materialize_studio_workspace(definition)


def test_locked_workspace_materialization_reaches_a_fixed_point(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepare_view(notebook_path)
    definition = workspace_config.load_studio_definition(notebook_path)
    materialize = workspace_config.materialize_studio_workspace
    attempts = 0

    def transient_materialization(selected):
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise WorkspaceGenerationConflictError()
        return materialize(selected)

    monkeypatch.setattr(
        workspace_config,
        "materialize_studio_workspace",
        transient_materialization,
    )

    workspace = workspace_config.materialize_studio_workspace_after_conflict(definition)

    assert workspace.default_view == "dashboard"


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
        published_sites={"dashboard": artifact_sites(inspection.sites)},
    )

    assert resolved.view("dashboard").sites == artifact_sites(inspection.sites)


def test_view_mutation_lock_is_reentrant_for_nested_same_thread_owners(
    tmp_path: Path,
) -> None:
    view_root = tmp_path / "views"

    with (
        view_mutation_lock(view_root, "dashboard"),
        view_mutation_lock(view_root, "dashboard"),
    ):
        pass


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
    open_directory = files.open_directory
    raced = False

    def swap_root_after_open(
        name: str | Path, *, path: Path, parent: int | None = None
    ) -> int:
        nonlocal raced
        descriptor = open_directory(name, path=path, parent=parent)
        if path == view_root and not raced:
            raced = True
            view_root.rename(tmp_path / "views-retired")
            view_root.symlink_to(external, target_is_directory=True)
        return descriptor

    monkeypatch.setattr(files, "open_directory", swap_root_after_open)

    with (
        pytest.raises(ConfigurationError, match="symlink"),
        workspace_catalog_lock(view_root),
    ):
        pytest.fail("raced workspace lock must not be acquired")

    assert raced
    assert tuple(external.iterdir()) == ()


def test_workspace_lock_reports_a_removed_control_directory_while_held(
    tmp_path: Path,
) -> None:
    view_root = tmp_path / "views"

    with (
        pytest.raises(ConfigurationError, match="changed while held"),
        workspace_catalog_lock(view_root),
    ):
        shutil.rmtree(view_root / ".locks")
