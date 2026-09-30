from __future__ import annotations

import asyncio
import errno
from pathlib import Path

import pytest

import marimo_studio._views.rename as rename_module
import marimo_studio.authoring as studio_authoring
from marimo_studio._filesystem.secure import SecureDirectory
from marimo_studio._views.api import prepare_view
from marimo_studio._workspace import load_studio
from marimo_studio._workspace.view_owners import view_owner_snapshot
from marimo_studio.errors import (
    ConfigurationError,
    InvalidViewNameError,
    PublicationHeldError,
    ViewExistsError,
    ViewGenerationConflictError,
    ViewRenameError,
    WorkspaceGenerationConflictError,
    WorkspaceMutationError,
)


def _workspace_with_report(notebook: Path) -> studio_authoring.Workspace:
    prepare_view(notebook)
    prepare_view(notebook, "report")
    return studio_authoring.open_workspace(notebook)


def _catalog(notebook: Path) -> tuple[str, dict[str, str], str]:
    studio = load_studio(notebook)
    return studio.default_view, dict(studio.view_generations), studio.catalog_generation


def test_rename_moves_the_project_and_returns_its_new_handle(
    notebook_path: Path,
) -> None:
    workspace = _workspace_with_report(notebook_path)
    report = workspace.view("report")
    root = load_studio(notebook_path).view_root
    (root / "report" / "notes.md").write_text("kept", encoding="utf-8")
    built = asyncio.run(report.build())

    summary = asyncio.run(report.rename("summary"))

    studio = load_studio(notebook_path)
    assert list(studio.views) == ["dashboard", "summary"]
    assert (root / "summary" / "notes.md").read_text(encoding="utf-8") == "kept"
    assert not (root / "report").exists()
    retired, _identity = view_owner_snapshot(root, "report")
    assert retired is not None and retired.present is False
    assert summary.name == "summary"
    assert summary.generation == studio.view_generations["summary"]
    inspection = asyncio.run(summary.inspect())
    assert inspection.build is not None
    assert inspection.build.revision == built.revision
    with pytest.raises(ViewGenerationConflictError):
        asyncio.run(report.inspect())


def test_renaming_the_default_view_moves_the_default(notebook_path: Path) -> None:
    workspace = _workspace_with_report(notebook_path)

    asyncio.run(workspace.view("dashboard").rename("overview"))

    studio = load_studio(notebook_path)
    assert studio.default_view == "overview"
    assert set(studio.views) == {"overview", "report"}


def test_renaming_the_default_view_updates_project_configuration(
    notebook_path: Path,
) -> None:
    (notebook_path.parent / "pyproject.toml").write_text(
        f'[tool.marimo-studio]\nnotebook = "{notebook_path.name}"\n'
        'default = "dashboard"\n',
        encoding="utf-8",
    )
    workspace = _workspace_with_report(notebook_path)

    asyncio.run(workspace.view("dashboard").rename("overview"))

    studio = load_studio(notebook_path)
    assert studio.config_source == "pyproject"
    assert studio.default_view == "overview"


@pytest.mark.parametrize(
    ("new_name", "error"),
    [
        ("dashboard", ViewExistsError),
        ("Report", InvalidViewNameError),
        ("studio", InvalidViewNameError),
    ],
)
def test_rename_rejects_names_it_cannot_take(
    notebook_path: Path,
    new_name: str,
    error: type[Exception],
) -> None:
    workspace = _workspace_with_report(notebook_path)
    before = _catalog(notebook_path)

    with pytest.raises(error):
        asyncio.run(workspace.view("report").rename(new_name))

    assert _catalog(notebook_path) == before


def test_rename_is_blocked_by_an_active_publication_hold(notebook_path: Path) -> None:
    workspace = _workspace_with_report(notebook_path)
    report = workspace.view("report")
    hold = asyncio.run(report.hold_publication(owner="multi-file edit"))
    before = _catalog(notebook_path)

    with pytest.raises(PublicationHeldError, match="Release that hold"):
        asyncio.run(report.rename("summary"))
    assert _catalog(notebook_path) == before

    asyncio.run(report.release_publication(hold.token))
    asyncio.run(report.rename("summary"))
    assert "summary" in load_studio(notebook_path).views


def test_rename_to_its_current_name_keeps_the_catalog(notebook_path: Path) -> None:
    workspace = _workspace_with_report(notebook_path)
    before = _catalog(notebook_path)

    report = asyncio.run(workspace.view("report").rename("report"))

    assert _catalog(notebook_path) == before
    assert report.generation == before[1]["report"]


def _fail_loading_once_moved(monkeypatch: pytest.MonkeyPatch, target: Path) -> None:
    load = rename_module.load_studio

    def load_studio(path: Path):
        if target.exists():
            raise RuntimeError("catalog reload failed")
        return load(path)

    monkeypatch.setattr(rename_module, "load_studio", load_studio)


def test_a_failed_rename_restores_the_project_and_catalog(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = _workspace_with_report(notebook_path)
    root = load_studio(notebook_path).view_root
    before = _catalog(notebook_path)
    _fail_loading_once_moved(monkeypatch, root / "summary")

    with pytest.raises(RuntimeError, match="catalog reload failed"):
        asyncio.run(workspace.view("report").rename("summary"))

    monkeypatch.undo()
    assert (root / "report" / "view.toml").is_file()
    assert not (root / "summary").exists()
    assert _catalog(notebook_path) == before


def _fail_moving(
    monkeypatch: pytest.MonkeyPatch,
    source_name: str,
    before_move=None,
    error: OSError | None = None,
) -> None:
    move = SecureDirectory.rename_if_absent

    def rename_if_absent(filesystem: SecureDirectory, source: Path, target: Path):
        if source.name == source_name:
            if before_move is not None:
                before_move(target)
            if error is not None:
                raise error
        return move(filesystem, source, target)

    monkeypatch.setattr(SecureDirectory, "rename_if_absent", rename_if_absent)


@pytest.mark.parametrize(
    ("error", "busy", "next_step"),
    [
        (OSError(errno.EBUSY, "Device or resource busy"), True, "Close programs"),
        (PermissionError(errno.EACCES, "Permission denied"), False, "Resolve"),
    ],
    ids=["busy", "denied"],
)
def test_a_rename_that_cannot_move_the_folder_keeps_the_old_name(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    error: OSError,
    busy: bool,
    next_step: str,
) -> None:
    workspace = _workspace_with_report(notebook_path)
    before = _catalog(notebook_path)
    _fail_moving(monkeypatch, "report", error=error)

    with pytest.raises(ViewRenameError, match="keeps its old name") as failed:
        asyncio.run(workspace.view("report").rename("summary"))

    monkeypatch.undo()
    assert failed.value.transient is busy
    assert next_step in str(failed.value)
    assert _catalog(notebook_path) == before


def test_a_folder_created_under_the_new_name_mid_rename_survives(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = _workspace_with_report(notebook_path)
    before = _catalog(notebook_path)

    def create_external(target: Path) -> None:
        target.mkdir()
        (target / "external.txt").write_text("keep", encoding="utf-8")

    _fail_moving(monkeypatch, "report", before_move=create_external)

    with pytest.raises(ViewExistsError):
        asyncio.run(workspace.view("report").rename("summary"))

    monkeypatch.undo()
    root = load_studio(notebook_path).view_root
    assert (root / "summary" / "external.txt").read_text(encoding="utf-8") == "keep"
    assert _catalog(notebook_path) == before


def test_a_rename_that_cannot_move_back_keeps_the_new_name(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = _workspace_with_report(notebook_path)
    root = load_studio(notebook_path).view_root
    _fail_loading_once_moved(monkeypatch, root / "overview")
    _fail_moving(monkeypatch, "overview", error=PermissionError(13, "Access denied"))

    with pytest.raises(WorkspaceMutationError) as failed:
        asyncio.run(workspace.view("dashboard").rename("overview"))

    monkeypatch.undo()
    assert failed.value.write_committed is True
    studio = load_studio(notebook_path)
    assert studio.default_view == "overview"
    assert set(studio.views) == {"overview", "report"}


def test_a_notebook_save_during_the_rename_restores_the_project(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = _workspace_with_report(notebook_path)
    root = load_studio(notebook_path).view_root
    load = rename_module.load_studio

    def save_the_notebook_while_loading(path: Path):
        studio = load(path)
        if (root / "summary").exists():
            source = notebook_path.read_text(encoding="utf-8")
            notebook_path.write_text(source + "\n", encoding="utf-8")
        return studio

    monkeypatch.setattr(rename_module, "load_studio", save_the_notebook_while_loading)

    with pytest.raises(ConfigurationError, match="changed before the transaction"):
        asyncio.run(workspace.view("report").rename("summary"))

    monkeypatch.undo()
    assert (root / "report" / "view.toml").is_file()
    assert not (root / "summary").exists()
    assert set(load_studio(notebook_path).views) == {"dashboard", "report"}


def test_a_failed_sync_after_moving_back_keeps_the_old_name(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = _workspace_with_report(notebook_path)
    root = load_studio(notebook_path).view_root
    before = _catalog(notebook_path)
    _fail_loading_once_moved(monkeypatch, root / "summary")
    sync = SecureDirectory.sync_parent

    def sync_parent(filesystem: SecureDirectory, path: Path) -> None:
        if path == root / "report":
            raise OSError(errno.EIO, "Input/output error")
        sync(filesystem, path)

    monkeypatch.setattr(SecureDirectory, "sync_parent", sync_parent)

    with pytest.raises(RuntimeError, match="catalog reload failed"):
        asyncio.run(workspace.view("report").rename("summary"))

    monkeypatch.undo()
    assert (root / "report" / "view.toml").is_file()
    assert _catalog(notebook_path) == before


def test_rename_rejects_handles_from_an_earlier_catalog(notebook_path: Path) -> None:
    workspace = _workspace_with_report(notebook_path)
    report = workspace.view("report")
    asyncio.run(workspace.view("report").make_default())

    with pytest.raises(WorkspaceGenerationConflictError):
        asyncio.run(report.rename("summary"))
    assert "report" in load_studio(notebook_path).views
