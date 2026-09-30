from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from marimo_studio._cli import cli
from marimo_studio._views.api import prepare_view
from marimo_studio._workspace import load_studio


def test_view_rename_reports_the_updated_catalog(notebook_path: Path) -> None:
    prepare_view(notebook_path)
    report = prepare_view(notebook_path, "report").root

    result = CliRunner().invoke(
        cli,
        [
            "view",
            "rename",
            "report",
            "summary",
            "--target",
            str(notebook_path),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    studio = load_studio(notebook_path)
    assert json.loads(result.stdout) == {
        "schema": 1,
        "notebook": str(notebook_path),
        "view": "summary",
        "default_view": "dashboard",
        "views": [
            {"name": name, "generation": studio.view_generations[name]}
            for name in studio.views
        ],
        "catalog_generation": studio.catalog_generation,
    }
    assert list(studio.views) == ["dashboard", "summary"]
    assert not report.exists()


def test_view_rename_names_both_views_in_human_output(notebook_path: Path) -> None:
    prepare_view(notebook_path)
    prepare_view(notebook_path, "report")

    result = CliRunner().invoke(
        cli,
        ["view", "rename", "report", "summary", "--target", str(notebook_path)],
    )

    assert result.exit_code == 0, result.output
    assert "Renamed view report to summary" in result.output
