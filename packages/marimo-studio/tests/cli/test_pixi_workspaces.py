from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest
from click.testing import CliRunner

import marimo_studio._cli.environment as environment_module
from marimo_studio._cli import cli
from marimo_studio._cli.environment import EnvironmentRunResult, shell_command
from marimo_studio._cli.targets import NotebookTarget
from marimo_studio._workspace.metadata import read_notebook_metadata
from marimo_studio._workspace.python_project import project_environment
from marimo_studio.errors import DependencyError

PIXI_TOML = """[workspace]
name = "analysis"
channels = ["conda-forge"]
platforms = ["linux-64", "osx-arm64", "win-64"]

[dependencies]
python = "3.12.*"
quarto = ">=1.9.38"

[pypi-dependencies]
marimo-studio = "*"
"""
TOOLS_PIXI_TOML = """[workspace]
name = "tools"
channels = ["conda-forge"]
platforms = ["linux-64"]

[dependencies]
quarto = ">=1.9.38"
"""
PIXI_PYPROJECT = """[project]
name = "analysis"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = ["marimo-studio"]

[tool.pixi.workspace]
channels = ["conda-forge"]
platforms = ["linux-64", "osx-arm64", "win-64"]
"""
UV_WORKSPACE = """[tool.uv.workspace]
members = []
"""


@pytest.mark.parametrize(
    ("files", "notebook", "owner"),
    (
        (
            {"pyproject.toml": PIXI_PYPROJECT},
            "analysis.py",
            ("pixi", ".", "pyproject.toml"),
        ),
        (
            {"pixi.toml": TOOLS_PIXI_TOML, "pyproject.toml": UV_WORKSPACE},
            "examples/analysis.py",
            ("uv", ".", "pyproject.toml"),
        ),
        ({"pixi.toml": PIXI_TOML}, "notebooks/analysis.py", ("pixi", ".", "pixi.toml")),
        ({"pixi.toml": TOOLS_PIXI_TOML}, "analysis.py", None),
        (
            {"pixi.toml": PIXI_TOML, "notebooks/pyproject.toml": "[tool.ruff]\n"},
            "notebooks/analysis.py",
            None,
        ),
    ),
)
def test_the_nearest_python_declaring_manifest_owns_the_notebook_environment(
    tmp_path: Path,
    files: dict[str, str],
    notebook: str,
    owner: tuple[str, str, str] | None,
) -> None:
    for relative, content in files.items():
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    project = project_environment(tmp_path / notebook)

    if owner is None:
        assert project is None
    else:
        manager, root, manifest = owner
        assert project is not None
        assert (project.manager, project.root, project.manifest) == (
            manager,
            tmp_path / root,
            tmp_path / manifest,
        )


def _pixi_notebook(notebook_path: Path) -> Path:
    manifest = notebook_path.parent / "pixi.toml"
    manifest.write_text(PIXI_TOML, encoding="utf-8")
    return manifest


def test_studio_runs_in_the_activated_pixi_workspace(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = _pixi_notebook(notebook_path)
    monkeypatch.setenv("PIXI_PROJECT_MANIFEST", str(manifest))
    monkeypatch.setenv("CONDA_PREFIX", sys.prefix)
    monkeypatch.setattr(
        "marimo_studio._cli.commands.view_catalog.run_in_environment",
        lambda _target, _args: pytest.fail("a pixi workspace re-entered"),
    )

    result = CliRunner().invoke(
        cli,
        ["view", "create", "dashboard", "--target", str(notebook_path)],
    )

    assert result.exit_code == 0, result.output
    assert "dependencies" not in (read_notebook_metadata(notebook_path) or {})
    command = shell_command(
        [
            "pixi",
            "run",
            "--manifest-path",
            str(manifest),
            "-x",
            "marimo",
            "edit",
            str(notebook_path.resolve()),
            "--no-sandbox",
            "--watch",
        ]
    )
    assert command in result.stderr


def test_studio_outside_the_pixi_workspace_names_the_command_to_run(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = _pixi_notebook(notebook_path)
    monkeypatch.delenv("PIXI_PROJECT_MANIFEST", raising=False)
    monkeypatch.setattr(sys, "argv", ["marimo-studio", "view", "build", "dashboard"])

    result = CliRunner().invoke(
        cli,
        ["view", "build", "dashboard", "--target", str(notebook_path)],
    )

    assert isinstance(result.exception, DependencyError)
    command = shell_command(
        [
            "pixi",
            "run",
            "--manifest-path",
            str(manifest),
            "-x",
            "marimo-studio",
            "view",
            "build",
            "dashboard",
        ]
    )
    assert command in str(result.exception)


@pytest.mark.skipif(shutil.which("uv") is None, reason="uv is unavailable")
def test_uv_reentry_leaves_an_enclosing_pixi_environment_behind(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    activation = {
        "CONDA_DEFAULT_ENV": "default",
        "CONDA_PREFIX": "/opt/pixi/envs/default",
        "PIXI_ENVIRONMENT_NAME": "default",
        "PIXI_PROJECT_MANIFEST": "/opt/pixi/pixi.toml",
        "PIXI_PROJECT_ROOT": "/opt/pixi",
        "VIRTUAL_ENV": "/opt/pixi/envs/default",
    }
    for name, value in activation.items():
        monkeypatch.setenv(name, value)
    captured: dict[str, str] = {}

    def capture(_command, child_env, *_streams) -> EnvironmentRunResult:
        captured.update(child_env)
        return EnvironmentRunResult(0)

    monkeypatch.setattr(environment_module, "_run_command", capture)

    environment_module.run_in_notebook_environment(
        NotebookTarget(notebook_path.parent, notebook_path),
        ["status"],
    )

    assert activation.keys().isdisjoint(captured)
