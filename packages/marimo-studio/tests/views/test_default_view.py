from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

import marimo_studio.authoring as studio_authoring
from marimo_studio._workspace import load_studio
from marimo_studio.errors import WorkspaceGenerationConflictError

from ._workspace_lifecycle_support import _workspace_with_report


@pytest.mark.parametrize("project", [False, True], ids=["notebook", "pyproject"])
def test_make_default_serves_the_view_at_the_main_route(
    notebook_path: Path,
    project: bool,
) -> None:
    workspace = _workspace_with_report(notebook_path, project=project)
    before = load_studio(notebook_path)

    report = asyncio.run(workspace.view("report").make_default())

    after = load_studio(notebook_path)
    assert after.config_source == ("pyproject" if project else "notebook")
    assert after.default_view == "report"
    assert after.catalog_generation != before.catalog_generation
    assert after.view_generations == before.view_generations
    assert report.catalog_generation == after.catalog_generation
    assert report.generation == after.view_generations["report"]
    assert asyncio.run(report.inspect()).view == "report"


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
