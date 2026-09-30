from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

import marimo_studio._views.rename as rename_module
import marimo_studio.authoring as studio_authoring
from marimo_studio._views.api import prepare_view
from marimo_studio._workspace import load_studio
from marimo_studio._workspace.view_owners import view_owner_snapshot
from marimo_studio.errors import (
    ConfigurationError,
    ViewExistsError,
    ViewGenerationConflictError,
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
        ("Report", ConfigurationError),
        ("studio", ConfigurationError),
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


def test_rename_waits_for_a_publication_hold_to_end(notebook_path: Path) -> None:
    workspace = _workspace_with_report(notebook_path)
    report = workspace.view("report")
    hold = asyncio.run(report.hold_publication(owner="multi-file edit"))
    before = _catalog(notebook_path)

    with pytest.raises(ConfigurationError, match="Release that hold"):
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


def test_a_failed_rename_restores_the_project_and_catalog(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = _workspace_with_report(notebook_path)
    root = load_studio(notebook_path).view_root
    before = _catalog(notebook_path)
    load = rename_module.load_studio

    def fail_after_the_move(path: Path):
        if (root / "summary").exists():
            raise RuntimeError("catalog reload failed")
        return load(path)

    monkeypatch.setattr(rename_module, "load_studio", fail_after_the_move)

    with pytest.raises(RuntimeError, match="catalog reload failed"):
        asyncio.run(workspace.view("report").rename("summary"))

    monkeypatch.undo()
    assert (root / "report" / "view.toml").is_file()
    assert not (root / "summary").exists()
    assert _catalog(notebook_path) == before
