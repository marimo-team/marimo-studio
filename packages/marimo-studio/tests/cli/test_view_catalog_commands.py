from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from marimo_studio._cli import cli
from marimo_studio._views.api import prepare_view
from marimo_studio._workspace import load_studio
from marimo_studio.errors import (
    ConfigurationError,
    ViewExistsError,
    ViewNotFoundError,
)

from .commands_test_support import _run_cli


def _with_report(notebook: Path) -> None:
    prepare_view(notebook)
    prepare_view(notebook, "report")


def _invoke(notebook: Path, *args: str):
    return CliRunner().invoke(cli, ["view", *args, "--target", str(notebook)])


@pytest.mark.parametrize(
    ("args", "view", "default_view", "views"),
    [
        (("remove", "dashboard", "--yes"), "dashboard", "report", ["report"]),
        (
            ("rename", "report", "summary"),
            "summary",
            "dashboard",
            ["dashboard", "summary"],
        ),
        (("default", "report"), "report", "report", ["dashboard", "report"]),
    ],
    ids=["remove", "rename", "default"],
)
def test_catalog_commands_report_the_committed_catalog(
    notebook_path: Path,
    args: tuple[str, ...],
    view: str,
    default_view: str,
    views: list[str],
) -> None:
    _with_report(notebook_path)

    result = _invoke(notebook_path, *args, "--json")

    assert result.exit_code == 0, result.output
    studio = load_studio(notebook_path)
    assert json.loads(result.stdout) == {
        "schema": 1,
        "notebook": str(notebook_path),
        "view": view,
        "default_view": default_view,
        "views": [
            {"name": name, "generation": studio.view_generations[name]}
            for name in views
        ],
        "catalog_generation": studio.catalog_generation,
    }


@pytest.mark.parametrize(
    ("args", "summary"),
    [
        (("remove", "report", "--yes"), "Removed view report"),
        (("rename", "report", "summary"), "Renamed view report to summary"),
        (("default", "report"), "Selected default view report"),
    ],
    ids=["remove", "rename", "default"],
)
def test_catalog_commands_summarize_the_change(
    notebook_path: Path,
    args: tuple[str, ...],
    summary: str,
) -> None:
    _with_report(notebook_path)

    result = _invoke(notebook_path, *args)

    assert result.exit_code == 0, result.output
    assert summary in result.output


@pytest.mark.parametrize(
    ("args", "error"),
    [
        (("rename", "report", "dashboard"), ViewExistsError),
        (("rename", "missing", "summary"), ViewNotFoundError),
        (("default", "missing"), ViewNotFoundError),
    ],
    ids=["rename-taken-name", "rename-unknown-view", "default-unknown-view"],
)
def test_catalog_command_rejection_keeps_the_catalog(
    notebook_path: Path,
    args: tuple[str, ...],
    error: type[Exception],
) -> None:
    _with_report(notebook_path)
    before = load_studio(notebook_path)

    result = _invoke(notebook_path, *args)

    assert isinstance(result.exception, error)
    after = load_studio(notebook_path)
    assert after.default_view == before.default_view
    assert after.view_generations == before.view_generations


def test_view_default_repairs_a_default_that_names_a_missing_view(
    notebook_path: Path,
) -> None:
    _with_report(notebook_path)
    notebook_path.write_text(
        notebook_path.read_text(encoding="utf-8").replace(
            'default = "dashboard"',
            'default = "summary"',
        ),
        encoding="utf-8",
    )
    with pytest.raises(ConfigurationError, match="marimo-studio view default"):
        load_studio(notebook_path)

    result = _invoke(notebook_path, "default", "report")

    assert result.exit_code == 0, result.output
    assert load_studio(notebook_path).default_view == "report"


def test_view_remove_preserves_source_when_confirmation_is_declined(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _with_report(notebook_path)
    monkeypatch.setattr(
        "marimo_studio._cli.commands.view_catalog._stdin_is_interactive",
        lambda: True,
    )

    result = CliRunner().invoke(
        cli,
        ["view", "remove", "report", "--target", str(notebook_path)],
        input="n\n",
    )

    assert result.exit_code == 0
    assert set(load_studio(notebook_path).views) == {"dashboard", "report"}


def test_view_remove_requires_yes_for_machine_output(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _with_report(notebook_path)
    monkeypatch.setattr(
        "marimo_studio._cli.commands.view_catalog._stdin_is_interactive",
        lambda: True,
    )

    result = _invoke(notebook_path, "remove", "report", "--json")

    assert result.exit_code == 2
    assert "Pass --yes" in result.output
    assert "report" in load_studio(notebook_path).views


@pytest.mark.native_process
def test_view_remove_requires_yes_for_noninteractive_use(
    notebook_path: Path,
    runtime_assets: Path,
) -> None:
    _with_report(notebook_path)

    result = _run_cli(
        runtime_assets,
        "view",
        "remove",
        "report",
        "--target",
        str(notebook_path),
    )

    assert result.returncode == 2
    assert result.stdout == ""
    assert "Pass --yes" in result.stderr
    assert "report" in load_studio(notebook_path).views
