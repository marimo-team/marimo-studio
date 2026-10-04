from __future__ import annotations

import asyncio
import errno
import shutil
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner

import marimo_studio._views.rename as rename_module
import marimo_studio._workspace.transactions as workspace_transactions
from marimo_studio._cli import cli
from marimo_studio._filesystem.files import FileTree
from marimo_studio._workspace import load_studio
from marimo_studio.errors import (
    ConfigurationError,
    InvalidViewNameError,
    PublicationHeldError,
    ViewExistsError,
    ViewGenerationConflictError,
    ViewNotFoundError,
    ViewRenameError,
    WorkspaceGenerationConflictError,
    WorkspaceMutationError,
)

from ._workspace_lifecycle_support import _workspace_with_report


def _catalog(notebook: Path) -> tuple[str, dict[str, str], str]:
    studio = load_studio(notebook)
    return studio.default_view, dict(studio.view_generations), studio.catalog_generation


def _fail_moving(
    monkeypatch: pytest.MonkeyPatch,
    source_name: str,
    *,
    before_move: Callable[[Path], None] | None = None,
    error: OSError | None = None,
) -> None:
    move = FileTree.publish

    def publish(tree: FileTree, source: Path, target: Path) -> None:
        if source.name == source_name:
            if before_move is not None:
                before_move(target)
            if error is not None:
                raise error
        move(tree, source, target)

    monkeypatch.setattr(FileTree, "publish", publish)


def _fail_after_moving_to(monkeypatch: pytest.MonkeyPatch, target_name: str) -> None:
    generation = rename_module.directory_generation

    def changed_after_move(path: Path) -> str:
        return "changed" if path.name == target_name else generation(path)

    monkeypatch.setattr(rename_module, "directory_generation", changed_after_move)


def _around_transaction(
    monkeypatch: pytest.MonkeyPatch,
    *,
    before_body: Callable[[], None] = lambda: None,
    after_body: Callable[[], None] = lambda: None,
) -> None:
    transaction = workspace_transactions.write_file_transaction

    @contextmanager
    def around(*args: Any, **kwargs: Any) -> Iterator[None]:
        with transaction(*args, **kwargs):
            before_body()
            yield
            after_body()

    monkeypatch.setattr(workspace_transactions, "write_file_transaction", around)


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
    assert summary.name == "summary"
    assert summary.generation == studio.view_generations["summary"]
    inspection = asyncio.run(summary.inspect())
    assert inspection.freshness == "stale"
    assert inspection.build is not None
    assert inspection.build.revision == built.revision
    with pytest.raises(ViewGenerationConflictError):
        asyncio.run(report.inspect())


@pytest.mark.parametrize("project", [False, True], ids=["notebook", "pyproject"])
def test_renaming_the_default_view_moves_the_default(
    notebook_path: Path,
    project: bool,
) -> None:
    workspace = _workspace_with_report(notebook_path, project=project)

    asyncio.run(workspace.view("dashboard").rename("overview"))

    studio = load_studio(notebook_path)
    assert studio.config_source == ("pyproject" if project else "notebook")
    assert studio.default_view == "overview"
    assert set(studio.views) == {"overview", "report"}


@pytest.mark.parametrize(
    ("new_name", "error"),
    [
        ("dashboard", ViewExistsError),
        ("report", ViewExistsError),
        ("Report", InvalidViewNameError),
        ("studio", InvalidViewNameError),
    ],
    ids=["taken", "current", "uppercase", "reserved"],
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


def test_rename_rejects_handles_from_an_earlier_catalog(notebook_path: Path) -> None:
    workspace = _workspace_with_report(notebook_path)
    report = workspace.view("report")
    asyncio.run(workspace.view("report").make_default())

    with pytest.raises(WorkspaceGenerationConflictError):
        asyncio.run(report.rename("summary"))
    assert "report" in load_studio(notebook_path).views


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


def test_a_rename_that_fails_after_the_move_restores_the_project(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = _workspace_with_report(notebook_path)
    root = load_studio(notebook_path).view_root
    before = _catalog(notebook_path)
    _fail_after_moving_to(monkeypatch, "summary")

    with pytest.raises(ConfigurationError, match="changed before its rename"):
        asyncio.run(workspace.view("report").rename("summary"))

    monkeypatch.undo()
    assert (root / "report" / "view.toml").is_file()
    assert not (root / "summary").exists()
    assert _catalog(notebook_path) == before


def test_a_notebook_save_during_the_rename_restores_the_project(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = _workspace_with_report(notebook_path)
    root = load_studio(notebook_path).view_root

    def save_the_notebook() -> None:
        source = notebook_path.read_text(encoding="utf-8")
        notebook_path.write_text(source + "\n", encoding="utf-8")

    _around_transaction(monkeypatch, after_body=save_the_notebook)

    with pytest.raises(ConfigurationError, match="changed before the transaction"):
        asyncio.run(workspace.view("report").rename("summary"))

    monkeypatch.undo()
    assert (root / "report" / "view.toml").is_file()
    assert not (root / "summary").exists()
    assert set(load_studio(notebook_path).views) == {"dashboard", "report"}


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


def test_a_view_folder_removed_before_the_move_reports_the_missing_view(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = _workspace_with_report(notebook_path)
    root = load_studio(notebook_path).view_root
    _around_transaction(
        monkeypatch,
        before_body=lambda: shutil.rmtree(root / "report"),
    )

    with pytest.raises(ViewNotFoundError):
        asyncio.run(workspace.view("report").rename("summary"))

    monkeypatch.undo()
    assert set(load_studio(notebook_path).views) == {"dashboard"}


def test_a_rename_that_cannot_move_back_is_repaired_by_selecting_the_default(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = _workspace_with_report(notebook_path)
    root = load_studio(notebook_path).view_root
    _fail_after_moving_to(monkeypatch, "overview")
    _fail_moving(monkeypatch, "overview", error=PermissionError(13, "Access denied"))

    with pytest.raises(WorkspaceMutationError) as failed:
        asyncio.run(workspace.view("dashboard").rename("overview"))

    monkeypatch.undo()
    assert failed.value.write_committed is False
    assert failed.value.recovery == root / "overview"
    with pytest.raises(ConfigurationError, match="marimo-studio view default"):
        load_studio(notebook_path)
    repaired = CliRunner().invoke(
        cli,
        ["view", "default", "overview", "--target", str(notebook_path)],
    )
    assert repaired.exit_code == 0, repaired.output
    studio = load_studio(notebook_path)
    assert studio.default_view == "overview"
    assert set(studio.views) == {"overview", "report"}
