from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from marimo_studio._cli import cli
from marimo_studio._views.api import prepare_view
from marimo_studio._workspace import load_studio
from marimo_studio.errors import ConfigurationError, ViewNotFoundError


def test_view_default_reports_the_updated_catalog(notebook_path: Path) -> None:
    prepare_view(notebook_path)
    prepare_view(notebook_path, "report")

    result = CliRunner().invoke(
        cli,
        ["view", "default", "report", "--target", str(notebook_path), "--json"],
    )

    assert result.exit_code == 0, result.output
    studio = load_studio(notebook_path)
    assert json.loads(result.stdout) == {
        "schema": 1,
        "notebook": str(notebook_path),
        "view": "report",
        "default_view": "report",
        "views": [
            {"name": name, "generation": studio.view_generations[name]}
            for name in studio.views
        ],
        "catalog_generation": studio.catalog_generation,
    }


def test_view_default_rejects_an_unknown_view(notebook_path: Path) -> None:
    prepare_view(notebook_path)

    result = CliRunner().invoke(
        cli,
        ["view", "default", "report", "--target", str(notebook_path)],
    )

    assert isinstance(result.exception, ViewNotFoundError)
    assert load_studio(notebook_path).default_view == "dashboard"


def test_view_default_repairs_a_default_that_names_a_missing_view(
    notebook_path: Path,
) -> None:
    prepare_view(notebook_path)
    prepare_view(notebook_path, "report")
    notebook_path.write_text(
        notebook_path.read_text(encoding="utf-8").replace(
            'default = "dashboard"',
            'default = "summary"',
        ),
        encoding="utf-8",
    )
    with pytest.raises(ConfigurationError, match="marimo-studio view default"):
        load_studio(notebook_path)

    result = CliRunner().invoke(
        cli,
        ["view", "default", "report", "--target", str(notebook_path)],
    )

    assert result.exit_code == 0, result.output
    assert load_studio(notebook_path).default_view == "report"
