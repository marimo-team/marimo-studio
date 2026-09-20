"""Discover the Python project that owns a notebook environment."""

from __future__ import annotations

import sys
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

from marimo_studio.errors import DependencyError


def project_metadata(root: Path) -> dict[str, object] | None:
    pyproject = root / "pyproject.toml"
    try:
        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except OSError as error:
        raise DependencyError(
            f"Could not read project metadata: {pyproject}"
        ) from error
    except UnicodeError as error:
        raise DependencyError(
            f"Project metadata must be UTF-8 text: {pyproject}"
        ) from error
    except tomllib.TOMLDecodeError as error:
        raise DependencyError(
            f"Invalid project metadata in {pyproject}: {error}"
        ) from error
    return data


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


def owning_project(notebook: Path) -> Path | None:
    """Return the nearest Python project, stopping at a pyproject boundary."""
    for parent in notebook.parents:
        if (parent / "pyproject.toml").is_file():
            return parent if has_project_environment(parent) else None
    return None
