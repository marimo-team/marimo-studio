"""Resolve CLI targets to notebook and Studio workspace objects."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from marimo_studio._workspace.config import load_studio
from marimo_studio._workspace.models import StudioConfig


@dataclass(frozen=True)
class NotebookTarget:
    """Notebook location used before a Studio configuration is loaded."""

    root: Path
    notebook: Path


def load_studio_target(target: str | Path | None) -> StudioConfig:
    """Load the Studio configuration selected by a CLI target."""
    return load_studio(target or ".")


def resolve_notebook(target: str | Path | None) -> Path:
    """Resolve a notebook path, project path, or implicit current workspace."""
    if target is None:
        return load_studio_target(None).notebook
    path = Path(target).expanduser()
    if path.is_dir() or path.suffix == ".toml":
        return load_studio_target(path).notebook
    return path.resolve()


def resolve_environment_target(
    target: str | Path | None,
    notebook: Path,
) -> StudioConfig | NotebookTarget:
    """Return the project root and notebook used for uv composition."""
    if target is None:
        return load_studio_target(None)
    path = Path(target).expanduser()
    if path.is_dir() or path.suffix == ".toml":
        return load_studio_target(path)
    root = next(
        (
            parent
            for parent in notebook.parents
            if (parent / "pyproject.toml").is_file()
        ),
        notebook.parent,
    )
    return NotebookTarget(root=root, notebook=notebook)
