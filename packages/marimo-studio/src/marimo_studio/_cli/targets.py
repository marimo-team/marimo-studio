"""Resolve CLI targets to notebook and Studio workspace objects."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from marimo_studio._workspace.config import load_studio, load_studio_definition
from marimo_studio._workspace.models import StudioWorkspace
from marimo_studio.errors import ConfigurationError


@dataclass(frozen=True)
class NotebookTarget:
    """Notebook location used before a Studio configuration is loaded."""

    root: Path
    notebook: Path


def load_studio_target(target: str | Path | None) -> StudioWorkspace:
    """Load the Studio configuration selected by a CLI target."""
    return load_studio(target or ".")


def resolve_notebook(target: str | Path | None) -> Path:
    """Resolve a notebook path, project path, or implicit current configuration."""
    if target is None:
        return load_studio_definition(".").notebook
    path = Path(target).expanduser()
    if path.is_dir() or path.suffix == ".toml":
        return load_studio_definition(path).notebook
    return path.resolve()


def resolve_environment_target(
    target: str | Path | None,
    notebook: Path,
) -> NotebookTarget:
    """Return the project root and notebook used for uv composition."""
    if not notebook.exists():
        raise ConfigurationError(f"Target does not exist: {notebook}")
    if not notebook.is_file() or notebook.suffix != ".py":
        raise ConfigurationError(f"Expected a Python Marimo notebook: {notebook}")
    path = Path(target).expanduser().resolve() if target is not None else notebook
    if path.is_dir():
        root = path
    elif path.suffix == ".toml":
        root = path.parent
    else:
        root = next(
            (
                parent
                for parent in notebook.parents
                if (parent / "pyproject.toml").is_file()
            ),
            notebook.parent,
        )
    return NotebookTarget(root=root, notebook=notebook)
