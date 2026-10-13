"""Where Studio keeps authored view projects and their generated build state."""

from __future__ import annotations

import errno
import json
import os
import shutil
import subprocess
import sys
from contextlib import ExitStack
from dataclasses import replace
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import pytest
from click.testing import CliRunner
from starlette.testclient import TestClient

import marimo_studio._artifacts.store as store_module
import marimo_studio._views.create as create_module
from marimo_studio._artifacts.lock import build_lock
from marimo_studio._artifacts.repository import read_artifact_state
from marimo_studio._artifacts.retention import lease_published_artifact
from marimo_studio._artifacts.store import move_artifact_state, remove_artifact_state
from marimo_studio._cli import cli
from marimo_studio._filesystem.files import FileTree
from marimo_studio._validation.dependencies import diagnose_dependencies
from marimo_studio._views.api import prepare_view
from marimo_studio._views.build import build_view_project_sync
from marimo_studio._views.remove import delete_view
from marimo_studio._views.rename import rename_view
from marimo_studio._workspace import load_studio
from marimo_studio._workspace.project_manifest import CatalogProject
from marimo_studio.errors import ConfigurationError, WorkspaceGenerationConflictError
from marimo_studio.view_providers import BuildRequest, BuildResult
from marimo_studio.view_providers._host import provider_registry

from ..app_helpers import created_one_view, edit_mode, marimo_app
from ..helpers import update_notebook_config

requires_git = pytest.mark.skipif(
    shutil.which("git") is None, reason="needs the git command"
)


def _build(project: CatalogProject) -> str:
    with build_view_project_sync(project) as lease:
        return lease.artifact.artifact_revision


def _count_provider_builds(
    monkeypatch: pytest.MonkeyPatch,
    project: CatalogProject,
) -> list[str]:
    provider = provider_registry().get(project.provider)
    build = provider.build
    calls: list[str] = []

    def counted(request: BuildRequest) -> BuildResult:
        calls.append(request.project.name)
        return build(request)

    monkeypatch.setattr(provider, "build", counted)
    return calls


def _configure(notebook: Path, view_root: str) -> None:
    notebook.parent.joinpath("pyproject.toml").write_text(
        "[tool.marimo-studio]\n"
        f'notebook = "{notebook.name}"\n'
        f'view_root = "{view_root}"\n'
        'default = "dashboard"\n',
        encoding="utf-8",
    )


def _legacy_catalog(notebook: Path) -> Path:
    return notebook.parent / "__marimo__" / "studio" / notebook.stem


def _move_to_legacy_catalog(notebook: Path) -> Path:
    """Arrange the Studio 0.3 layout: views and their state in one folder."""
    studio = load_studio(notebook)
    legacy = _legacy_catalog(notebook)
    shutil.copytree(studio.view_root, legacy, dirs_exist_ok=True)
    shutil.rmtree(studio.view_root)
    return legacy


def _remove_configuration(notebook: Path) -> None:
    source = notebook.read_text(encoding="utf-8")
    notebook.write_text(source[source.index("import marimo") :], encoding="utf-8")


def _status(notebook: Path) -> dict[str, object]:
    result = CliRunner().invoke(cli, ["status", "--target", str(notebook), "--json"])
    assert result.exit_code == 0, result.output
    return json.loads(result.stdout)


def _git(repository: Path, *args: str) -> str:
    # The developer's own ignore rules and repository variables would decide
    # which files git reports.
    environment = {
        name: value for name, value in os.environ.items() if not name.startswith("GIT_")
    }
    return subprocess.run(
        ["git", *args],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
        env={
            **environment,
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
        },
    ).stdout


def _git_paths(repository: Path) -> set[str]:
    output = _git(repository, "status", "--porcelain", "--untracked-files=all")
    return {line[3:] for line in output.splitlines()}


def test_first_view_is_created_in_the_studio_folder_beside_the_notebook(
    notebook_path: Path,
) -> None:
    studio = created_one_view(notebook_path)
    project = studio.view("dashboard")

    assert project.root == notebook_path.parent / "studio" / "analysis" / "dashboard"
    assert project.artifacts == (
        notebook_path.parent
        / "__marimo__"
        / "studio"
        / "analysis"
        / "dashboard"
        / ".artifacts"
    )
    assert "view_root" not in notebook_path.read_text(encoding="utf-8")


@requires_git
@pytest.mark.parametrize("ignored", ("", "__marimo__/\n"), ids=("bare", "ignored"))
def test_git_sees_view_sources_and_skips_build_state(
    notebook_path: Path,
    ignored: str,
) -> None:
    repository = notebook_path.parent
    _git(repository, "init", "-q")
    if ignored:
        repository.joinpath(".gitignore").write_text(ignored, encoding="utf-8")
    studio = created_one_view(notebook_path)
    project = studio.view("dashboard")

    _build(project)

    assert (project.artifacts / "development.json").is_file()
    paths = _git_paths(repository)
    assert "studio/analysis/dashboard/view.toml" in paths
    assert "studio/analysis/.owners/dashboard.toml" in paths
    assert not any(
        part in {"__marimo__", ".artifacts", ".locks"}
        for path in paths
        for part in path.split("/")
    )


def test_build_state_moves_with_the_python_cache_prefix(
    notebook_path: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prefix = tmp_path / "output"
    monkeypatch.setattr(sys, "pycache_prefix", str(prefix))
    studio = created_one_view(notebook_path)
    project = studio.view("dashboard")

    _build(project)

    assert project.artifacts.is_relative_to(prefix)
    assert (project.artifacts / "development.json").is_file()
    assert not notebook_path.parent.joinpath("__marimo__").exists()


def test_a_configured_view_root_keeps_build_state_in_the_output_directory(
    notebook_path: Path,
) -> None:
    _configure(notebook_path, "views")
    prepare_view(notebook_path)
    project = load_studio(notebook_path).view("dashboard")

    _build(project)

    assert project.root == notebook_path.parent / "views" / "dashboard"
    assert project.artifacts.is_relative_to(_legacy_catalog(notebook_path))
    assert (project.artifacts / "development.json").is_file()
    assert not project.root.joinpath(".artifacts").exists()


def test_a_studio_03_catalog_keeps_its_views_and_builds(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    revision = _build(created_one_view(notebook_path).view("dashboard"))
    legacy = _move_to_legacy_catalog(notebook_path)

    studio = load_studio(notebook_path)
    project = studio.view("dashboard")
    builds = _count_provider_builds(monkeypatch, project)

    assert studio.view_root == legacy
    assert project.artifacts == legacy / "dashboard" / ".artifacts"
    assert _build(project) == revision
    assert builds == []

    prepare_view(notebook_path, "report")

    assert legacy.joinpath("report", "view.toml").is_file()
    assert not notebook_path.parent.joinpath("studio", "analysis").exists()


def test_moving_a_studio_03_catalog_into_studio_keeps_its_builds(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    revision = _build(created_one_view(notebook_path).view("dashboard"))
    legacy = _move_to_legacy_catalog(notebook_path)
    current = notebook_path.parent / "studio" / "analysis"
    shutil.move(legacy, current)

    project = load_studio(notebook_path).view("dashboard")
    builds = _count_provider_builds(monkeypatch, project)

    assert project.root == current / "dashboard"
    assert _build(project) == revision
    assert builds == []
    assert not project.root.joinpath(".artifacts").exists()


def test_status_reports_a_studio_03_catalog_before_configuration(
    notebook_path: Path,
) -> None:
    created_one_view(notebook_path)
    legacy = _move_to_legacy_catalog(notebook_path)
    _remove_configuration(notebook_path)

    status = _status(notebook_path)

    assert status["state"] == "unconfigured"
    assert status["view_root"] == str(legacy)


def test_views_in_both_default_folders_ask_which_folder_to_keep(
    notebook_path: Path,
) -> None:
    studio = created_one_view(notebook_path)
    shutil.copytree(studio.view_root, _legacy_catalog(notebook_path))

    with pytest.raises(ConfigurationError, match="exist in both"):
        load_studio(notebook_path)


def test_status_reports_the_view_root_and_build_state_root(
    notebook_path: Path,
) -> None:
    unconfigured = _status(notebook_path)
    created_one_view(notebook_path)
    configured = _status(notebook_path)

    expected = {
        "view_root": str(notebook_path.parent / "studio" / "analysis"),
        "state_root": str(_legacy_catalog(notebook_path)),
    }
    assert {key: unconfigured[key] for key in expected} == expected
    assert {key: configured[key] for key in expected} == expected


def test_first_build_moves_state_left_inside_a_configured_view(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure(notebook_path, "views")
    prepare_view(notebook_path)
    project = load_studio(notebook_path).view("dashboard")
    revision = _build(project)
    # Studio 0.3 kept this state inside each view of a configured catalog.
    shutil.move(project.artifacts, project.root / ".artifacts")
    builds = _count_provider_builds(monkeypatch, project)

    assert read_artifact_state(project, "development").artifact is None
    assert _build(project) == revision
    assert builds == []
    assert (project.artifacts / "development.json").is_file()
    assert not project.root.joinpath(".artifacts").exists()


def test_removing_a_view_removes_its_build_state(notebook_path: Path) -> None:
    created_one_view(notebook_path)
    prepare_view(notebook_path, "report")
    project = load_studio(notebook_path).view("report")
    _build(project)

    delete_view(load_studio(notebook_path), "report")

    assert not project.root.exists()
    assert not project.artifacts.parent.exists()


def test_renaming_a_view_carries_its_build_state(notebook_path: Path) -> None:
    created_one_view(notebook_path)
    prepare_view(notebook_path, "report")
    project = load_studio(notebook_path).view("report")
    _build(project)
    receipt = (project.artifacts / "development.json").read_bytes()
    stale = project.artifacts.parent.with_name("summary") / ".artifacts"
    stale.mkdir(parents=True)
    stale.joinpath("development.json").write_text("{}", encoding="utf-8")

    renamed = rename_view(load_studio(notebook_path), "report", "summary")

    moved = renamed.view("summary").artifacts / "development.json"
    assert moved.read_bytes() == receipt
    assert not project.artifacts.parent.exists()


def test_a_new_view_discards_state_left_under_its_name(notebook_path: Path) -> None:
    studio = created_one_view(notebook_path)
    leftover = studio.artifacts("report") / "development.json"
    leftover.parent.mkdir(parents=True)
    leftover.write_text("{}", encoding="utf-8")

    prepare_view(notebook_path, "report")
    project = load_studio(notebook_path).view("report")

    assert not leftover.exists()
    assert read_artifact_state(project, "development").state is None


def test_a_lease_reports_a_view_removed_outside_studio(notebook_path: Path) -> None:
    project = created_one_view(notebook_path).view("dashboard")
    _build(project)
    lease = lease_published_artifact(project, "development")
    assert lease is not None
    shutil.rmtree(project.root)

    with pytest.raises(ConfigurationError, match="removed"):
        lease.share()
    lease.close()


def test_a_view_root_inside_the_build_state_is_rejected(notebook_path: Path) -> None:
    _configure(notebook_path, "__marimo__/studio/analysis/views")

    with pytest.raises(ConfigurationError, match="inside Studio's generated"):
        prepare_view(notebook_path)


def test_a_view_that_would_contain_build_state_is_rejected(
    notebook_path: Path,
) -> None:
    _configure(notebook_path, "__marimo__/studio")
    view = _legacy_catalog(notebook_path)
    view.mkdir(parents=True)
    view.joinpath("view.toml").write_text(
        'schema = 1\nprovider = "marimo-studio/vanilla"\n', encoding="utf-8"
    )

    with pytest.raises(ConfigurationError, match="contains Studio's generated"):
        load_studio(notebook_path)


def test_a_configured_view_root_rejects_a_studio_03_view_with_the_same_name(
    notebook_path: Path,
) -> None:
    studio = created_one_view(notebook_path)
    configured = notebook_path.parent / "views"
    shutil.copytree(studio.view_root, configured)
    legacy = _move_to_legacy_catalog(notebook_path)
    update_notebook_config(
        notebook_path, lambda config: config.update(view_root="views")
    )

    with pytest.raises(ConfigurationError, match="also exists in"):
        load_studio(notebook_path)

    assert legacy.joinpath("dashboard", "view.toml").is_file()


def test_a_configured_view_root_ignores_other_studio_03_views(
    notebook_path: Path,
) -> None:
    studio = created_one_view(notebook_path)
    configured = notebook_path.parent / "views"
    shutil.copytree(studio.view_root, configured)
    legacy = _move_to_legacy_catalog(notebook_path)
    legacy.joinpath("dashboard").rename(legacy / "report")
    update_notebook_config(
        notebook_path, lambda config: config.update(view_root="views")
    )

    assert set(load_studio(notebook_path).views) == {"dashboard"}
    assert legacy.joinpath("report", "view.toml").is_file()


@pytest.mark.skipif(
    sys.platform == "win32", reason="symlink creation needs elevated Windows access"
)
def test_a_linked_build_state_path_is_rejected_before_any_write(
    notebook_path: Path,
    tmp_path: Path,
) -> None:
    created_one_view(notebook_path)
    outside = tmp_path / "outside"
    outside.joinpath("analysis", "dashboard").mkdir(parents=True)
    output = notebook_path.parent / "__marimo__"
    output.mkdir()
    output.joinpath("studio").symlink_to(outside, target_is_directory=True)

    with pytest.raises(ConfigurationError, match="cannot keep view build state"):
        load_studio(notebook_path)

    assert sorted(path.relative_to(outside) for path in outside.rglob("*")) == [
        Path("analysis"),
        Path("analysis/dashboard"),
    ]


def test_state_cleanup_keeps_a_directory_that_holds_a_view(
    notebook_path: Path,
) -> None:
    studio = created_one_view(notebook_path)
    # A state path that spells an authored view, as a case-insensitive file
    # system can make two different spellings name one directory.
    authored = studio.artifacts("report").parent
    authored.mkdir(parents=True)
    authored.joinpath("view.toml").write_text("schema = 1\n", encoding="utf-8")
    elsewhere = studio.view("dashboard")
    misplaced = replace(elsewhere, artifacts=authored / ".artifacts")

    remove_artifact_state(misplaced)
    move_artifact_state(misplaced, replace(elsewhere, artifacts=studio.artifacts("x")))

    assert authored.joinpath("view.toml").is_file()


def test_a_cache_prefix_leaves_state_inside_a_studio_03_view_in_place(
    notebook_path: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    revision = _build(created_one_view(notebook_path).view("dashboard"))
    legacy = _move_to_legacy_catalog(notebook_path)
    in_place = legacy / "dashboard" / ".artifacts"
    monkeypatch.setattr(sys, "pycache_prefix", str(tmp_path / "output"))
    prefixed = load_studio(notebook_path).view("dashboard")

    _build(prefixed)

    assert (in_place / "development.json").is_file()
    monkeypatch.setattr(sys, "pycache_prefix", None)
    assert _build(load_studio(notebook_path).view("dashboard")) == revision


def test_doctor_reports_views_in_both_default_folders(notebook_path: Path) -> None:
    studio = created_one_view(notebook_path)
    shutil.copytree(studio.view_root, _legacy_catalog(notebook_path))

    report = diagnose_dependencies(notebook_path)

    assert any("exist in both" in issue.message for issue in report.issues)


def test_a_late_writer_cannot_recreate_state_for_a_removed_view(
    notebook_path: Path,
) -> None:
    created_one_view(notebook_path)
    prepare_view(notebook_path, "report")
    project = load_studio(notebook_path).view("report")
    _build(project)
    delete_view(load_studio(notebook_path), "report")

    with pytest.raises(FileNotFoundError), build_lock(project):
        pass

    assert not project.artifacts.parent.exists()


@pytest.mark.parametrize(
    "holder", ("publication-lock", "build-lock", "pin", "other-file-system")
)
def test_a_build_keeps_earlier_state_that_is_still_in_use(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    holder: str,
) -> None:
    _configure(notebook_path, "views")
    prepare_view(notebook_path)
    project = load_studio(notebook_path).view("dashboard")
    _build(project)
    legacy = project.root / ".artifacts"
    shutil.move(project.artifacts, legacy)
    builds = _count_provider_builds(monkeypatch, project)

    with ExitStack() as held:
        if holder in {"publication-lock", "build-lock"}:
            name = (
                ".publication.lock" if holder == "publication-lock" else ".build.lock"
            )
            held.enter_context(FileTree(project.root).lock(legacy / name))
        elif holder == "pin":
            pin = legacy / ".pins" / ("0" * 64) / f"{os.getpid()}-{'0' * 32}"
            pin.parent.mkdir(parents=True)
            held.enter_context(FileTree(project.root).lock(pin))
        else:
            monkeypatch.setattr(
                store_module,
                "_move_directory",
                Mock(side_effect=OSError(errno.EXDEV, "Cross-device link")),
            )
        _build(project)

    assert builds == ["dashboard"]
    assert (legacy / "development.json").is_file()
    assert (project.artifacts / "development.json").is_file()


def test_studio_03_views_keep_their_state_through_rename_and_removal(
    notebook_path: Path,
) -> None:
    created_one_view(notebook_path)
    prepare_view(notebook_path, "report")
    _build(load_studio(notebook_path).view("report"))
    legacy = _move_to_legacy_catalog(notebook_path)

    renamed = rename_view(load_studio(notebook_path), "report", "summary")
    summary = legacy / "summary"

    assert (summary / "view.toml").is_file()
    assert (summary / ".artifacts" / "development.json").is_file()
    delete_view(renamed, "summary")
    assert not summary.exists()
    assert (legacy / "dashboard" / "view.toml").is_file()


def test_the_first_view_inventory_names_a_studio_03_catalog(
    notebook_path: Path,
) -> None:
    created_one_view(notebook_path)
    _move_to_legacy_catalog(notebook_path)
    _remove_configuration(notebook_path)
    app = marimo_app(notebook_path)
    edit_mode(app)

    with TestClient(app) as client:
        payload = client.get("/_marimo-studio/views").json()

    assert payload["view_root"] == "__marimo__/studio/analysis"


def test_view_creation_rejects_a_catalog_that_moved_before_its_lock(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    validate = create_module._validate_view_creation
    calls = 0

    def validate_after_a_studio_03_view_appears(*args: Any, **kwargs: Any) -> Any:
        nonlocal calls
        calls += 1
        if calls == 2:
            view = _legacy_catalog(notebook_path) / "report"
            view.mkdir(parents=True)
            view.joinpath("view.toml").write_text(
                'schema = 1\nprovider = "marimo-studio/vanilla"\n', encoding="utf-8"
            )
        return validate(*args, **kwargs)

    monkeypatch.setattr(
        create_module,
        "_validate_view_creation",
        validate_after_a_studio_03_view_appears,
    )

    original = notebook_path.read_bytes()

    with pytest.raises(WorkspaceGenerationConflictError):
        prepare_view(notebook_path)

    assert notebook_path.read_bytes() == original
    assert not tuple(notebook_path.parent.joinpath("studio").glob("*/*/view.toml"))


def test_a_build_adopts_earlier_state_with_only_stale_pins(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure(notebook_path, "views")
    prepare_view(notebook_path)
    project = load_studio(notebook_path).view("dashboard")
    revision = _build(project)
    legacy = project.root / ".artifacts"
    shutil.move(project.artifacts, legacy)
    # A pin whose process exited holds no lock.
    pin = legacy / ".pins" / revision.removeprefix("sha256:") / f"1-{'0' * 32}"
    pin.parent.mkdir(parents=True)
    pin.write_text("", encoding="utf-8")
    builds = _count_provider_builds(monkeypatch, project)

    assert _build(project) == revision
    assert builds == []
    assert not legacy.exists()


def test_a_view_recreated_outside_studio_starts_unbuilt(notebook_path: Path) -> None:
    created_one_view(notebook_path)
    prepare_view(notebook_path, "report")
    old = load_studio(notebook_path).view("report")
    revision = _build(old)
    shutil.rmtree(old.root)
    load_studio(notebook_path)
    shutil.copytree(old.root.with_name("dashboard"), old.root)

    recreated = load_studio(notebook_path).view("report")

    assert read_artifact_state(recreated, "development").state is None
    assert lease_published_artifact(recreated, "development") is None
    assert _build(recreated) != revision


def test_removing_a_view_keeps_other_files_beside_its_build_state(
    notebook_path: Path,
) -> None:
    created_one_view(notebook_path)
    prepare_view(notebook_path, "report")
    project = load_studio(notebook_path).view("report")
    _build(project)
    notes = project.artifacts.parent / "notes.md"
    notes.write_text("kept", encoding="utf-8")

    delete_view(load_studio(notebook_path), "report")

    assert not project.artifacts.exists()
    assert notes.read_text(encoding="utf-8") == "kept"


@pytest.mark.skipif(
    sys.platform == "win32", reason="symlink creation needs elevated Windows access"
)
def test_build_state_follows_a_linked_marimo_output_directory(
    notebook_path: Path,
    tmp_path: Path,
) -> None:
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    notebook_path.parent.joinpath("__marimo__").symlink_to(
        scratch, target_is_directory=True
    )
    project = created_one_view(notebook_path).view("dashboard")

    _build(project)

    assert (scratch / "studio" / "analysis" / "dashboard" / ".artifacts").is_dir()


@pytest.mark.skipif(
    sys.platform == "win32", reason="symlink creation needs elevated Windows access"
)
def test_a_relative_linked_cache_prefix_gives_a_resolved_state_root(
    notebook_path: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "target"
    target.mkdir()
    tmp_path.joinpath("linked").symlink_to(target, target_is_directory=True)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "pycache_prefix", "linked")
    project = created_one_view(notebook_path).view("dashboard")

    _build(project)

    assert project.artifacts.is_relative_to(target.resolve())
    assert (project.artifacts / "development.json").is_file()


def test_a_file_on_the_build_state_path_is_reported(notebook_path: Path) -> None:
    created_one_view(notebook_path)
    output = notebook_path.parent / "__marimo__"
    output.mkdir()
    output.joinpath("studio").write_text("", encoding="utf-8")

    with pytest.raises(ConfigurationError, match="cannot keep view build state"):
        load_studio(notebook_path)
