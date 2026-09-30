from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

import marimo_studio.authoring as studio_authoring
from marimo_studio._views.api import prepare_view
from marimo_studio._workspace import load_studio
from marimo_studio.errors import WorkspaceGenerationConflictError


def _workspace_with_report(notebook: Path) -> studio_authoring.Workspace:
    prepare_view(notebook)
    prepare_view(notebook, "report")
    return studio_authoring.open_workspace(notebook)


def test_make_default_serves_the_view_at_the_main_route(notebook_path: Path) -> None:
    workspace = _workspace_with_report(notebook_path)
    before = load_studio(notebook_path)

    report = asyncio.run(workspace.view("report").make_default())

    after = load_studio(notebook_path)
    assert after.default_view == "report"
    assert after.catalog_generation != before.catalog_generation
    assert after.view_generations == before.view_generations
    assert report.catalog_generation == after.catalog_generation
    assert report.generation == after.view_generations["report"]
    assert asyncio.run(report.inspect()).view == "report"


def test_make_default_updates_project_configuration(notebook_path: Path) -> None:
    (notebook_path.parent / "pyproject.toml").write_text(
        f'[tool.marimo-studio]\nnotebook = "{notebook_path.name}"\n'
        'default = "dashboard"\n',
        encoding="utf-8",
    )
    workspace = _workspace_with_report(notebook_path)

    asyncio.run(workspace.view("report").make_default())

    studio = load_studio(notebook_path)
    assert studio.config_source == "pyproject"
    assert studio.default_view == "report"


def test_make_default_on_the_current_default_leaves_the_configuration(
    notebook_path: Path,
) -> None:
    _workspace_with_report(notebook_path)
    before = load_studio(notebook_path)
    source = notebook_path.read_text(encoding="utf-8").replace(
        'default = "dashboard"',
        "default = 'dashboard'",
    )
    notebook_path.write_text(source, encoding="utf-8")
    workspace = studio_authoring.open_workspace(notebook_path)

    dashboard = asyncio.run(workspace.view("dashboard").make_default())

    assert notebook_path.read_text(encoding="utf-8") == source
    assert dashboard.generation == before.view_generations["dashboard"]


def test_make_default_rejects_handles_from_an_earlier_catalog(
    notebook_path: Path,
) -> None:
    workspace = _workspace_with_report(notebook_path)
    dashboard = workspace.view("dashboard")
    asyncio.run(workspace.view("report").make_default())

    with pytest.raises(WorkspaceGenerationConflictError):
        asyncio.run(dashboard.make_default())
    assert load_studio(notebook_path).default_view == "report"
