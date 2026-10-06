"""Discover the project that owns a notebook's Python environment.

A uv project owns it through `pyproject.toml` with `[project]` or
`[tool.uv.workspace]`. A pixi workspace owns it through `pyproject.toml` with
`[tool.pixi.workspace]` (or the older `[tool.pixi.project]`), or through a
`pixi.toml` that declares Python packages. A `pixi.toml` that installs only
system tools leaves the directory to uv.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

from marimo_studio.errors import DependencyError


@dataclass(frozen=True)
class ProjectEnvironment:
    """The project whose environment manager owns a notebook's environment."""

    manager: Literal["uv", "pixi"]
    root: Path
    manifest: Path


def _read_manifest(path: Path) -> dict[str, object] | None:
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except OSError as error:
        raise DependencyError(f"Could not read project metadata: {path}") from error
    except UnicodeError as error:
        raise DependencyError(f"Project metadata must be UTF-8 text: {path}") from error
    except tomllib.TOMLDecodeError as error:
        raise DependencyError(f"Invalid project metadata in {path}: {error}") from error
    return data


def project_metadata(root: Path) -> dict[str, object] | None:
    return _read_manifest(root / "pyproject.toml")


def declares_project_environment(data: dict[str, object] | None) -> bool:
    if data is None:
        return False
    project = data.get("project")
    tool = data.get("tool")
    uv = tool.get("uv") if isinstance(tool, dict) else None
    return isinstance(project, dict) or (
        isinstance(uv, dict) and isinstance(uv.get("workspace"), dict)
    )


def has_project_environment(root: Path) -> bool:
    """Return whether ``root`` declares a Python project or uv workspace."""
    return declares_project_environment(project_metadata(root))


def _pyproject_pixi(data: dict[str, object] | None) -> dict[str, object] | None:
    tool = data.get("tool") if data is not None else None
    pixi = tool.get("pixi") if isinstance(tool, dict) else None
    if not isinstance(pixi, dict):
        return None
    workspace = pixi.get("workspace", pixi.get("project"))
    return pixi if isinstance(workspace, dict) else None


def _dependency_tables(manifest: dict[str, object]) -> tuple[dict[str, object], ...]:
    """Return the manifest's top-level, feature, and platform target tables."""
    features = manifest.get("feature")
    owners = (
        manifest,
        *(
            table
            for table in (features.values() if isinstance(features, dict) else ())
            if isinstance(table, dict)
        ),
    )
    tables: list[dict[str, object]] = []
    for owner in owners:
        tables.append(owner)
        targets = owner.get("target")
        if isinstance(targets, dict):
            tables.extend(
                table for table in targets.values() if isinstance(table, dict)
            )
    return tuple(tables)


def _declares_python_packages(manifest: dict[str, object] | None) -> bool:
    if manifest is None:
        return False
    for table in _dependency_tables(manifest):
        dependencies = table.get("dependencies")
        if isinstance(dependencies, dict) and "python" in dependencies:
            return True
        if table.get("pypi-dependencies"):
            return True
    return False


def _pypi_requirement(name: str, specification: object) -> str:
    if isinstance(specification, dict):
        extras = specification.get("extras")
        if isinstance(extras, list) and extras:
            name = f"{name}[{','.join(str(extra) for extra in extras)}]"
        specification = specification.get("version")
    if not isinstance(specification, str) or specification.strip() in {"", "*"}:
        return name
    version = specification.strip()
    return f"{name}=={version}" if version[0].isdigit() else f"{name}{version}"


def pixi_declarations(
    project: ProjectEnvironment,
) -> tuple[tuple[str, ...], frozenset[str]]:
    """Return the PyPI requirements and conda package names a workspace declares."""
    data = _read_manifest(project.manifest) or {}
    manifest = data if project.manifest.name == "pixi.toml" else _pyproject_pixi(data)
    requirements: list[str] = []
    if project.manifest.name == "pyproject.toml":
        declared = data.get("project")
        values = declared.get("dependencies") if isinstance(declared, dict) else None
        if isinstance(values, list):
            requirements.extend(value for value in values if isinstance(value, str))
    conda: set[str] = set()
    for table in _dependency_tables(manifest or {}):
        pypi = table.get("pypi-dependencies")
        if isinstance(pypi, dict):
            requirements.extend(
                _pypi_requirement(str(name), specification)
                for name, specification in pypi.items()
            )
        dependencies = table.get("dependencies")
        if isinstance(dependencies, dict):
            conda.update(str(name) for name in dependencies)
    return tuple(requirements), frozenset(conda)


def project_environment(notebook: Path) -> ProjectEnvironment | None:
    """Return the nearest project that owns the notebook's Python environment.

    In one directory, a `pixi.toml` that declares Python packages comes first,
    then a pyproject pixi workspace, then a uv project. Any
    `pyproject.toml` ends the search, so a notebook below a non-project
    `pyproject.toml` has no owning project.
    """
    for parent in notebook.parents:
        pixi_manifest = parent / "pixi.toml"
        if _declares_python_packages(_read_manifest(pixi_manifest)):
            return ProjectEnvironment("pixi", parent, pixi_manifest)
        pyproject = parent / "pyproject.toml"
        if not pyproject.is_file():
            continue
        data = project_metadata(parent)
        if _pyproject_pixi(data) is not None:
            return ProjectEnvironment("pixi", parent, pyproject)
        if declares_project_environment(data):
            return ProjectEnvironment("uv", parent, pyproject)
        return None
    return None
