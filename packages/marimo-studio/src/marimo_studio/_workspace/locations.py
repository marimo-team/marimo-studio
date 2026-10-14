"""Place a notebook's authored view catalog and its generated view state.

Authored view projects live in the catalog, ``studio/<notebook-stem>/`` beside
the notebook unless ``view_root`` selects another folder. Each view keeps its
replaceable build state in ``<state_root>/<view>/.artifacts/``::

    analysis.py
    studio/analysis/dashboard/view.toml
    __marimo__/studio/analysis/dashboard/.artifacts/

The notebook's state root is one folder in a state directory. Studio takes
the state directory from the first setting that is present:

1. ``MARIMO_STUDIO_STATE_DIR``, which a host sets for every notebook.
2. ``state_dir`` in the notebook's Studio configuration.

Either directory holds one folder per notebook, named by a hash of the
resolved notebook path, so notebooks and checkouts never share state. Without
either setting, the state root is ``studio/<notebook-stem>/`` in marimo's
output directory for the notebook.

Catalogs created by Studio 0.3.0 and earlier live at
``__marimo__/studio/<notebook-stem>/``. That is also their default state root,
so each view keeps its state inside its project.
"""

from __future__ import annotations

import hashlib
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
STATE_DIR_ENV = "MARIMO_STUDIO_STATE_DIR"
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


def _is_view_project(directory: Path) -> bool:
    # Discovery refuses links, so a linked folder or manifest names no view.
    manifest = directory / VIEW_MANIFEST
    return (
        not is_temporary_name(directory.name)
        and not directory.is_symlink()
        and not manifest.is_symlink()
        and manifest.is_file()
    )


def holds_views(directory: Path) -> bool:
    """Return whether ``directory`` contains at least one view project."""
    try:
        return any(_is_view_project(child) for child in directory.iterdir())
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


def notebook_output_directory(notebook: Path) -> Path:
    """Return the ``__marimo__`` directory where marimo writes notebook output.

    The directory sits beside the notebook. When ``sys.pycache_prefix`` is
    set, for example through ``PYTHONPYCACHEPREFIX``, marimo mirrors the
    notebook's directory under that prefix, as Python does for
    ``__pycache__``. Studio follows that rule with resolved paths: it mirrors
    the resolved notebook folder under the prefix and resolves links in the
    result, including one at ``__marimo__``, so build tools that require
    resolved cache paths accept the state. A relative prefix resolves against
    the working directory, as it does for marimo.
    """
    directory = notebook.expanduser().resolve().parent
    prefix = sys.pycache_prefix
    if prefix is None:
        return Path(os.path.realpath(directory / MARIMO_DIRECTORY))
    mirrored = Path(prefix, *directory.parts[1:], MARIMO_DIRECTORY)
    return Path(os.path.realpath(mirrored))


def _host_state_directory() -> Path | None:
    value = os.environ.get(STATE_DIR_ENV, "")
    if not value:
        return None
    if not Path(value).is_absolute():
        raise ConfigurationError(
            f"{STATE_DIR_ENV} must be an absolute path, received {value!r}"
        )
    return Path(value)


@dataclass(frozen=True)
class CatalogLocations:
    """Where one notebook's view projects and their generated state live."""

    view_root: Path
    """Authored view projects, one directory per view."""
    state_root: Path
    """Replaceable view build state, one directory per view."""
    state_base: Path
    """The directory below which generated-state paths must not cross links."""

    @classmethod
    def default(cls, notebook: Path) -> CatalogLocations:
        """Return the locations for a notebook whose configuration sets no root."""
        return cls.resolve(notebook, default_view_root(notebook))

    @classmethod
    def resolve(
        cls,
        notebook: Path,
        view_root: Path,
        state_dir: Path | None = None,
    ) -> CatalogLocations:
        """Return the locations for a catalog, choosing its state root.

        ``state_dir`` is the configured state directory, if any. The host
        setting replaces it, and marimo's output directory supplies the
        default.
        """
        notebook = notebook.expanduser().resolve()
        directory = _host_state_directory() or state_dir
        if directory is not None:
            base = Path(os.path.realpath(directory))
            digest = hashlib.sha256(os.fsencode(notebook)).hexdigest()[:32]
            return cls(view_root, base / digest, base)
        base = notebook_output_directory(notebook)
        root = base / STUDIO_DIRECTORY / _stem(notebook)
        if os.path.realpath(root) == os.path.realpath(view_root):
            return cls.inside_views(view_root)
        return cls(view_root, root, base)

    @classmethod
    def inside_views(cls, view_root: Path) -> CatalogLocations:
        """Return locations that keep each view's state inside its project."""
        return cls(view_root, view_root, view_root)

    @property
    def keeps_state_in_views(self) -> bool:
        return self.state_root == self.view_root

    def artifacts(self, view: str) -> Path:
        """Return the generated-state directory for one named view."""
        return self.state_root / view / ARTIFACT_DIRECTORY

    def artifact_base(self, project: Path) -> Path:
        """Return the directory that bounds a view project's generated state.

        State inside the project stays bounded by the project directory, so a
        removed project cannot be recreated through its state.
        """
        return project if self.keeps_state_in_views else self.state_base
