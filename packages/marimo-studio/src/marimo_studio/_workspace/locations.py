"""Place a notebook's authored view catalog and its generated view state.

Authored view projects live in the catalog, ``studio/<notebook-stem>/`` beside
the notebook unless ``view_root`` selects another folder. Studio keeps each
view's replaceable build state in marimo's output directory for the notebook::

    analysis.py
    studio/analysis/dashboard/view.toml
    __marimo__/studio/analysis/dashboard/.artifacts/

The output directory moves under ``PYTHONPYCACHEPREFIX`` as marimo's session
snapshots and caches do, so a host can keep generated notebook output outside
its users' working trees.

Catalogs created by Studio 0.3.0 and earlier live at
``__marimo__/studio/<notebook-stem>/``. Studio keeps opening them there, and
their state paths are unchanged because each view's ``.artifacts/`` directory
already sits at the state location.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

from marimo_studio._filesystem.names import is_temporary_name
from marimo_studio._filesystem.paths import (
    PORTABLE_PATH_COMPONENT_MAX_BYTES,
    validate_portable_path_component,
)
from marimo_studio.errors import ConfigurationError

MARIMO_DIRECTORY = "__marimo__"
STUDIO_DIRECTORY = "studio"
ARTIFACT_DIRECTORY = ".artifacts"
VIEW_MANIFEST = "view.toml"
_NOTEBOOK_STEM_MAX_BYTES = PORTABLE_PATH_COMPONENT_MAX_BYTES - len(".py")


def _stem(notebook: Path) -> str:
    try:
        validate_portable_path_component(
            notebook.stem,
            field="Notebook filename stem",
            max_bytes=_NOTEBOOK_STEM_MAX_BYTES,
        )
    except ValueError as error:
        raise ConfigurationError(str(error)) from error
    return notebook.stem


def holds_views(directory: Path) -> bool:
    """Return whether ``directory`` contains at least one view project."""
    try:
        return any(
            not is_temporary_name(child.name) and (child / VIEW_MANIFEST).is_file()
            for child in directory.iterdir()
        )
    except (FileNotFoundError, NotADirectoryError):
        return False
    except OSError as error:
        raise ConfigurationError(f"View folder is unavailable: {directory}") from error


def default_view_root(notebook: Path) -> Path:
    """Return the catalog Studio uses when configuration sets no ``view_root``.

    New catalogs go to ``studio/<stem>/``. A catalog that already holds views
    at the Studio 0.3.0 location, ``__marimo__/studio/<stem>/``, stays there.
    Views in both folders are ambiguous, so Studio asks the person to choose.
    """
    path = notebook.expanduser().resolve()
    stem = _stem(path)
    current = path.parent / STUDIO_DIRECTORY / stem
    legacy = path.parent / MARIMO_DIRECTORY / STUDIO_DIRECTORY / stem
    if not holds_views(legacy):
        return current
    if holds_views(current):
        raise ConfigurationError(
            f"Views for {path.name} exist in both {current} and {legacy}. "
            f"Move the views you keep into {current}, then remove {legacy}."
        )
    return legacy


def is_legacy_view_root(view_root: Path) -> bool:
    """Return whether ``view_root`` uses the Studio 0.3.0 default location.

    Processes that run without a cache prefix keep using the state inside
    each view of such a catalog.
    """
    return (
        view_root.parent.name == STUDIO_DIRECTORY
        and view_root.parent.parent.name == MARIMO_DIRECTORY
    )


def notebook_output_directory(notebook: Path) -> Path:
    """Return the ``__marimo__`` directory where marimo writes notebook output.

    The directory sits beside the notebook. When ``sys.pycache_prefix`` is
    set, for example through ``PYTHONPYCACHEPREFIX``, marimo mirrors the
    notebook's directory under that prefix, as Python does for
    ``__pycache__``. Studio follows that rule with resolved paths: it mirrors
    the resolved notebook folder under the resolved prefix and resolves a
    link at ``__marimo__``. Build tools that require resolved cache paths
    then accept the state, and the working directory never changes it.
    """
    directory = notebook.expanduser().resolve().parent
    prefix = sys.pycache_prefix
    if prefix is None:
        return Path(os.path.realpath(directory / MARIMO_DIRECTORY))
    return Path(os.path.realpath(prefix), *directory.parts[1:], MARIMO_DIRECTORY)


def view_state_root(notebook: Path) -> Path:
    """Return the directory holding generated state for a notebook's views."""
    return notebook_output_directory(notebook) / STUDIO_DIRECTORY / _stem(notebook)


def notebook_output_directory_of(state_root: Path) -> Path:
    """Return the marimo output directory that holds a catalog's state root."""
    return state_root.parent.parent


def state_anchor(artifacts: Path) -> Path:
    """Return the directory below which view state paths must not cross links.

    ``CatalogLocations`` places state at
    ``<output>/studio/<stem>/<view>/.artifacts``, where ``<output>`` is the
    resolved marimo output directory. Studio opens ``<output>`` and refuses
    links at ``studio`` and below.
    """
    return artifacts.parents[3]


@dataclass(frozen=True)
class CatalogLocations:
    """Where one notebook's view projects and their generated state live."""

    view_root: Path
    """Authored view projects, one directory per view."""
    state_root: Path
    """Replaceable view build state under marimo's output directory."""

    @classmethod
    def default(cls, notebook: Path) -> CatalogLocations:
        """Return the locations for a notebook whose configuration sets no root."""
        return cls(default_view_root(notebook), view_state_root(notebook))

    def artifacts(self, view: str) -> Path:
        """Return the generated-state directory for one named view."""
        return self.state_root / view / ARTIFACT_DIRECTORY
