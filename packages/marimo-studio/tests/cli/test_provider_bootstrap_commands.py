from __future__ import annotations

import json
from importlib.metadata import version
from pathlib import Path

import pytest
from click.testing import CliRunner

from marimo_studio._cli import cli
from marimo_studio._cli.targets import NotebookTarget
from marimo_studio._views.api import prepare_view
from marimo_studio._workspace import load_studio


@pytest.mark.parametrize(
    ("arguments", "module"),
    (
        (["status"], "marimo_studio._cli.commands.status"),
        (
            ["view", "create", "appendix"],
            "marimo_studio._cli.commands.view_create",
        ),
        (
            ["view", "inspect", "dashboard"],
            "marimo_studio._cli.commands.view_source",
        ),
        (
            ["view", "read", "dashboard", "index.html"],
            "marimo_studio._cli.commands.view_source",
        ),
        (["view", "build", "dashboard"], "marimo_studio._cli.commands.view_delivery"),
        (
            ["view", "export", "dashboard", "--output", "static"],
            "marimo_studio._cli.commands.view_delivery",
        ),
        (
            ["validate", "--level", "static"],
            "marimo_studio._cli.commands.validate",
        ),
    ),
)
def test_provider_commands_reenter_before_loading_the_workspace(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    arguments: list[str],
    module: str,
) -> None:
    captured: list[NotebookTarget] = []

    def requires_bootstrap(target: NotebookTarget) -> bool:
        captured.append(target)
        return True

    monkeypatch.setattr(f"{module}.provider_bootstrap_required", requires_bootstrap)
    monkeypatch.setattr(f"{module}.run_in_environment", lambda _target, _args: 19)

    result = CliRunner().invoke(
        cli,
        [*arguments, "--target", str(notebook_path)],
    )

    assert result.exit_code == 19, result.output
    assert len(captured) == 1
    assert captured[0].notebook == notebook_path.resolve()


def test_view_write_admits_its_owner_before_provider_reentry(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepare_view(notebook_path)
    studio = load_studio(notebook_path)
    captured: list[NotebookTarget] = []

    def requires_bootstrap(target: NotebookTarget) -> bool:
        captured.append(target)
        return True

    monkeypatch.setattr(
        "marimo_studio._cli.commands.view_source.provider_bootstrap_required",
        requires_bootstrap,
    )
    monkeypatch.setattr(
        "marimo_studio._cli.commands.view_source.run_in_environment",
        lambda _target, _args: 19,
    )

    result = CliRunner().invoke(
        cli,
        [
            "view",
            "write",
            "dashboard",
            "index.html",
            "--expected-revision",
            "revision",
            "--catalog-generation",
            studio.catalog_generation,
            "--view-generation",
            studio.view_generations["dashboard"],
            "--from",
            "-",
            "--target",
            str(notebook_path),
        ],
    )

    assert result.exit_code == 19, result.output
    assert len(captured) == 1


def test_first_vanilla_view_create_uses_the_base_studio_environment(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "marimo_studio._cli.commands.view_create.run_in_environment",
        lambda _target, _args: pytest.fail("first Vanilla view re-entered"),
    )

    result = CliRunner().invoke(
        cli,
        [
            "view",
            "create",
            "dashboard",
            "--target",
            str(notebook_path),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["launch_requirements"] == [
        f"marimo-studio=={version('marimo-studio')}"
    ]
