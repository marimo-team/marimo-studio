from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from marimo_studio._cli import cli
from marimo_studio._views.api import prepare_view
from marimo_studio._workspace import load_studio

from .commands_test_support import _run_cli


def test_view_remove_preserves_source_when_confirmation_is_declined(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepare_view(notebook_path)
    added = prepare_view(notebook_path, "executive")
    monkeypatch.setattr(
        "marimo_studio._cli.commands.view_create._stdin_is_interactive",
        lambda: True,
    )

    result = CliRunner().invoke(
        cli,
        ["view", "remove", "executive", "--target", str(notebook_path)],
        input="n\n",
    )

    assert result.exit_code == 0
    assert added.root.is_dir()
    assert set(load_studio(notebook_path).views) == {"dashboard", "executive"}


def test_view_remove_reports_the_updated_view_inventory(notebook_path: Path) -> None:
    dashboard = prepare_view(notebook_path).root
    prepare_view(notebook_path, "executive")

    result = CliRunner().invoke(
        cli,
        [
            "view",
            "remove",
            "dashboard",
            "--target",
            str(notebook_path),
            "--yes",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    updated = load_studio(notebook_path)
    assert json.loads(result.stdout) == {
        "catalog_generation": updated.catalog_generation,
        "default_view": "executive",
        "notebook": str(notebook_path),
        "schema": 1,
        "view": "dashboard",
        "views": ["executive"],
    }
    assert not dashboard.exists()


def test_view_remove_requires_yes_for_machine_output(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepare_view(notebook_path)
    added = prepare_view(notebook_path, "executive")
    monkeypatch.setattr(
        "marimo_studio._cli.commands.view_create._stdin_is_interactive",
        lambda: True,
    )

    result = CliRunner().invoke(
        cli,
        [
            "view",
            "remove",
            "executive",
            "--target",
            str(notebook_path),
            "--json",
        ],
    )

    assert result.exit_code == 2
    assert "Pass --yes" in result.output
    assert added.root.is_dir()


@pytest.mark.native_process
def test_view_remove_requires_yes_for_noninteractive_use(
    notebook_path: Path,
    runtime_assets: Path,
) -> None:
    prepare_view(notebook_path)
    added = prepare_view(notebook_path, "executive")

    result = _run_cli(
        runtime_assets,
        "view",
        "remove",
        "executive",
        "--target",
        str(notebook_path),
    )

    assert result.returncode == 2
    assert result.stdout == ""
    assert "Pass --yes" in result.stderr
    assert added.root.is_dir()
