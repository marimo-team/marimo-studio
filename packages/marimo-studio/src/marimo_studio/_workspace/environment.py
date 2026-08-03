"""Read notebook dependencies and run commands in their uv environment."""

from __future__ import annotations

import os
import sys
import tomllib
from importlib.metadata import metadata
from pathlib import Path
from typing import Protocol

from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import Version

from marimo_studio._workspace.metadata import read_notebook_metadata
from marimo_studio._workspace.models import NotebookEnvironment
from marimo_studio.errors import ConfigurationError, DependencyError

SANDBOX_ENV = "MARIMO_STUDIO_SANDBOX_BOOTSTRAPPED"


class EnvironmentTarget(Protocol):
    @property
    def root(self) -> Path: ...

    @property
    def notebook(self) -> Path: ...


def environment_root(target: EnvironmentTarget) -> Path:
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
        (environment_root(target) / "pyproject.toml").is_file()
        or bool(environment.dependencies)
        or not SpecifierSet(environment.requires_python).contains(
            current_python,
            prereleases=True,
        )
    )
