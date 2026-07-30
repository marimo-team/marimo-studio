"""Read notebook dependencies and run commands in their uv environment."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tomllib
from collections.abc import Callable
from importlib.metadata import metadata, version
from pathlib import Path
from typing import Protocol

from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import Version

from marimo_studio._compat.environment import inline_environment_flags
from marimo_studio._workspace.metadata import read_notebook_metadata
from marimo_studio._workspace.models import NotebookEnvironment
from marimo_studio.errors import ConfigurationError, DependencyError

SANDBOX_ENV = "MARIMO_STUDIO_SANDBOX_BOOTSTRAPPED"


class EnvironmentTarget(Protocol):
    @property
    def root(self) -> Path: ...

    @property
    def notebook(self) -> Path: ...


def _environment_root(target: EnvironmentTarget) -> Path:
    if getattr(target, "config_source", None) == "pyproject":
        return target.root
    return next(
        (
            parent
            for parent in target.notebook.parents
            if (parent / "pyproject.toml").is_file()
        ),
        target.root,
    )


def parse_notebook_environment(path: Path) -> NotebookEnvironment:
    data = read_notebook_metadata(path)
    if data is None:
        return NotebookEnvironment(
            requires_python=_package_python_requirement(),
            dependencies=(),
        )

    dependencies = data.get("dependencies", [])
    if not isinstance(dependencies, list) or not all(
        isinstance(item, str) for item in dependencies
    ):
        raise ConfigurationError("PEP 723 dependencies must be an array of strings")
    requires_python = data.get(
        "requires-python",
        _package_python_requirement(),
    )
    if not isinstance(requires_python, str):
        raise ConfigurationError("PEP 723 requires-python must be a string")
    try:
        SpecifierSet(requires_python)
    except InvalidSpecifier as error:
        raise ConfigurationError(
            f"Invalid requires-python constraint: {error}"
        ) from error
    return NotebookEnvironment(
        requires_python=requires_python,
        dependencies=tuple(dependencies),
    )


def _package_python_requirement() -> str:
    try:
        requirement = metadata("marimo-studio")["Requires-Python"]
    except KeyError as error:
        raise DependencyError(
            "marimo-studio package metadata has no Requires-Python"
        ) from error
    if requirement is None:
        raise DependencyError("marimo-studio package metadata has no Requires-Python")
    return requirement


def package_source_root() -> Path | None:
    candidate = Path(__file__).resolve().parents[3]
    pyproject = candidate / "pyproject.toml"
    if not pyproject.is_file():
        return None
    try:
        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError:
        return None
    if data.get("project", {}).get("name") != "marimo-studio":
        return None
    return candidate


def should_reenter(target: EnvironmentTarget, requested: bool | None) -> bool:
    if os.environ.get(SANDBOX_ENV) == "1":
        return False
    if requested is not None:
        return requested
    environment = parse_notebook_environment(target.notebook)
    current_python = Version(
        f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    )
    return (
        (_environment_root(target) / "pyproject.toml").is_file()
        or bool(environment.dependencies)
        or not SpecifierSet(environment.requires_python).contains(
            current_python,
            prereleases=True,
        )
    )


def _run_command(
    command: list[str],
    child_env: dict[str, str],
    diagnostic_line: Callable[[str], None] | None,
) -> int:
    result = subprocess.run(
        command,
        env=child_env,
        check=False,
        stderr=subprocess.PIPE if diagnostic_line is not None else None,
        encoding="utf-8" if diagnostic_line is not None else None,
        errors="replace" if diagnostic_line is not None else None,
    )
    if diagnostic_line is not None and result.stderr is not None:
        for line in result.stderr.splitlines():
            diagnostic_line(line)
    return result.returncode


def environment_command(
    target: EnvironmentTarget,
    args: list[str],
    *,
    quiet: bool = False,
) -> list[str]:
    """Build the uv command for a notebook environment."""
    uv = shutil.which("uv")
    if uv is None:
        raise DependencyError("uv is required for notebook environment execution")

    command = [uv, "run"]
    if quiet:
        command.append("--quiet")
    root = _environment_root(target)
    pyproject = root / "pyproject.toml"
    compose_project = pyproject.is_file()
    if compose_project:
        command.extend(["--project", str(root)])
        if (root / "uv.lock").is_file():
            command.append("--frozen")
    source_root = package_source_root()
    package_requirement = (
        None
        if source_root is not None
        else f"marimo-studio=={version('marimo-studio')}"
    )
    command.extend(
        inline_environment_flags(
            target.notebook,
            package_requirement,
            compose_project=compose_project,
        )
    )
    if source_root is not None:
        command.extend(["--with-editable", str(source_root)])
    command.extend(["--", *args])
    return command


def run_in_notebook_environment(
    target: EnvironmentTarget,
    args: list[str],
    *,
    diagnostic_line: Callable[[str], None] | None = None,
) -> int:
    """Re-enter the CLI through the notebook's Python environment."""
    child_env = os.environ.copy()
    child_env[SANDBOX_ENV] = "1"
    child_env.pop("VIRTUAL_ENV", None)
    command = environment_command(
        target,
        ["marimo-studio", *args],
        quiet=diagnostic_line is not None,
    )
    return _run_command(command, child_env, diagnostic_line)
