"""Discover the project that owns a notebook's Python environment.

A uv project owns it through `pyproject.toml` with `[project]` or
`[tool.uv.workspace]`. A pixi workspace owns it through `pyproject.toml` with
`[tool.pixi.workspace]` (or the older `[tool.pixi.project]`), or through a
`pixi.toml` that declares Python packages. A `pixi.toml` that installs only
system tools leaves the directory to uv.
"""

from __future__ import annotations

import os
import platform
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


def _dependency_tables(
    owners: tuple[dict[str, object], ...], platforms: frozenset[str] | None = None
) -> tuple[dict[str, object], ...]:
    """Return the owner tables and their target tables for ``platforms``.

    ``None`` selects every target table.
    """
    tables: list[dict[str, object]] = []
    for owner in owners:
        tables.append(owner)
        targets = owner.get("target")
        if isinstance(targets, dict):
            tables.extend(
                table
                for selector, table in targets.items()
                if isinstance(table, dict)
                and (platforms is None or selector in platforms)
            )
    return tuple(tables)


def _features(manifest: dict[str, object]) -> dict[str, object]:
    features = manifest.get("feature")
    return features if isinstance(features, dict) else {}


def _environment_features(
    manifest: dict[str, object], environment: str
) -> tuple[bool, tuple[str, ...]]:
    """Return whether an environment installs the default feature, and its features."""
    environments = manifest.get("environments")
    entry = environments.get(environment) if isinstance(environments, dict) else None
    if isinstance(entry, dict):
        names = entry.get("features")
        default = entry.get("no-default-feature") is not True
    else:
        names, default = entry, True
    if not isinstance(names, list):
        return default, ()
    return default, tuple(name for name in names if isinstance(name, str))


def _platform_targets() -> frozenset[str]:
    """Return the pixi target selectors that match the running platform."""
    machine = platform.machine().lower()
    arm = machine in {"arm64", "aarch64"}
    if sys.platform == "darwin":
        return frozenset({"unix", "osx", "osx-arm64" if arm else "osx-64"})
    if sys.platform == "win32":
        return frozenset({"win", "win-arm64" if arm else "win-64"})
    architecture = "64" if machine in {"x86_64", "amd64"} else machine
    return frozenset({"unix", "linux", f"linux-{architecture}"})


def _declares_python_packages(manifest: dict[str, object] | None) -> bool:
    if manifest is None:
        return False
    features = tuple(
        table for table in _features(manifest).values() if isinstance(table, dict)
    )
    for table in _dependency_tables((manifest, *features)):
        dependencies = table.get("dependencies")
        if isinstance(dependencies, dict) and "python" in dependencies:
            return True
        if table.get("pypi-dependencies"):
            return True
    return False


def _pypi_requirement(root: Path, name: str, specification: object) -> str:
    """Return the PEP 508 requirement for one pixi PyPI dependency.

    git, url, and path sources become direct references.
    """
    if not isinstance(specification, dict):
        specification = {"version": specification}
    extras = specification.get("extras")
    if isinstance(extras, list) and extras:
        name = f"{name}[{','.join(str(extra) for extra in extras)}]"
    git, url, path = (specification.get(key) for key in ("git", "url", "path"))
    if isinstance(git, str):
        reference = next(
            (
                value
                for key in ("rev", "tag", "branch")
                if isinstance(value := specification.get(key), str)
            ),
            None,
        )
        return f"{name} @ git+{git}" + (f"@{reference}" if reference else "")
    if isinstance(url, str):
        return f"{name} @ {url}"
    if isinstance(path, str):
        return f"{name} @ {(root / path).resolve().as_uri()}"
    version = specification.get("version")
    if not isinstance(version, str) or version.strip() in {"", "*"}:
        return name
    version = version.strip()
    return f"{name}=={version}" if version[0].isdigit() else f"{name}{version}"


def pixi_declarations(
    project: ProjectEnvironment,
) -> tuple[tuple[str, ...], frozenset[str]]:
    """Return the PyPI requirements and conda package names of a pixi environment.

    The environment is the activated one when Studio runs in ``project``, else
    ``default``. Its features and the target tables for the running platform
    contribute declarations. In a pyproject workspace, ``[project]``
    dependencies belong to the default feature, and a feature also selects the
    optional-dependency or dependency group of the same name.
    """
    activated = os.environ.get("PIXI_PROJECT_MANIFEST")
    environment = (
        os.environ.get("PIXI_ENVIRONMENT_NAME", "default")
        if activated and Path(activated).resolve() == project.manifest.resolve()
        else "default"
    )
    data = _read_manifest(project.manifest) or {}
    pyproject = project.manifest.name == "pyproject.toml"
    manifest = (_pyproject_pixi(data) if pyproject else data) or {}
    declared = data.get("project") if pyproject else None
    declared = declared if isinstance(declared, dict) else {}
    groups: dict[str, object] = {}
    if pyproject:
        for table in (
            data.get("dependency-groups"),
            declared.get("optional-dependencies"),
        ):
            if isinstance(table, dict):
                groups.update(table)
    default, names = _environment_features(manifest, environment)
    owners: list[dict[str, object]] = [manifest] if default else []
    values: list[object] = list(declared.get("dependencies") or ()) if default else []
    for name in names:
        feature = _features(manifest).get(name)
        if isinstance(feature, dict):
            owners.append(feature)
        group = groups.get(name)
        if isinstance(group, list):
            values.extend(group)
    requirements = [value for value in values if isinstance(value, str)]
    conda: set[str] = set()
    for table in _dependency_tables(tuple(owners), _platform_targets()):
        pypi = table.get("pypi-dependencies")
        if isinstance(pypi, dict):
            requirements.extend(
                _pypi_requirement(project.root, str(name), specification)
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
