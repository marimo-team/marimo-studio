"""Own the directory that holds one view's generated state.

Each catalog view keeps receipts, revisions, pins, and provider caches in
``artifact_root(project)``. The directory ignores itself in Git and can be
deleted to force a clean rebuild.

A catalog that keeps state inside its views lets each project directory own
its state's lifetime. State outside the project is named after its view, so it
records the view incarnation it belongs to: the generation in the catalog's
``.owners/`` record. State with no record of the current incarnation, such as
state left by a view that was deleted and recreated, reads as unbuilt, and the
next build discards its receipts. The record travels with copies and survives
remounts, so a copied project reuses its builds. Freshness checks rebuild a
view whose sources changed.
"""

from __future__ import annotations

import logging
import os
from contextlib import suppress
from pathlib import Path

from marimo_studio._artifacts.paths import (
    artifact_base,
    artifact_root,
    ensure_secure_directory,
)
from marimo_studio._filesystem.errors import FileTooLargeError, UnsafePathError
from marimo_studio._filesystem.files import FileTree
from marimo_studio._filesystem.ignore import ignore_generated_directory
from marimo_studio._filesystem.names import temporary_name
from marimo_studio._workspace.locations import (
    STATE_DIR_ENV,
    VIEW_MANIFEST,
    CatalogLocations,
)
from marimo_studio._workspace.project_manifest import CatalogProject
from marimo_studio._workspace.view_owners import view_owner_snapshot
from marimo_studio.errors import ConfigurationError

_LOGGER = logging.getLogger("marimo.studio")
_OWNER_FILE = "owner"
_OWNER_MAX_BYTES = 128
_RECEIPTS = ("development.json", "production.json")


def _outside_project(project: CatalogProject) -> bool:
    return not project.locations.keeps_state_in_views


def _holds_project(tree: FileTree, directory: Path) -> bool:
    # A view manifest marks authored files that generated-state cleanup must
    # never remove, whatever path spelling led here.
    return tree.exists(directory / VIEW_MANIFEST)


def _incarnation(locations: CatalogLocations, view: str) -> str | None:
    owner, _identity = view_owner_snapshot(locations.view_root, view)
    return owner.generation if owner is not None else None


def _stamp(locations: CatalogLocations, view: str) -> str | None:
    tree = FileTree(locations.state_base)
    try:
        content = tree.read(
            locations.artifacts(view) / _OWNER_FILE, max_bytes=_OWNER_MAX_BYTES
        ).content
    except FileNotFoundError:
        return None
    except (UnsafePathError, FileTooLargeError):
        # A stamp that is not a small regular file names no incarnation, so
        # the state reads as foreign and the next build replaces the stamp.
        return ""
    return content.decode("ascii", errors="replace").strip()


def _write_stamp(locations: CatalogLocations, view: str, incarnation: str) -> None:
    FileTree(locations.state_base).write(
        locations.artifacts(view) / _OWNER_FILE, incarnation.encode("ascii")
    )


def owns_view_state(locations: CatalogLocations, view: str) -> bool:
    """Return whether a view's state belongs to its current incarnation.

    A project without an owner record, outside any catalog, owns its state.
    """
    if locations.keeps_state_in_views:
        return True
    incarnation = _incarnation(locations, view)
    return incarnation is None or _stamp(locations, view) == incarnation


def owns_artifact_state(project: CatalogProject) -> bool:
    """Return whether the project's state belongs to its current incarnation."""
    return owns_view_state(project.locations, project.name)


def claim_artifact_state(project: CatalogProject) -> None:
    """Bind the view's state to its current incarnation.

    Call this while holding the view's publication lock. State that another
    incarnation left under the view's name loses its receipts, so revisions
    without a receipt or pin get pruned.
    """
    if not _outside_project(project):
        return
    locations = project.locations
    incarnation = _incarnation(locations, project.name)
    if incarnation is None or _stamp(locations, project.name) == incarnation:
        return
    tree = FileTree(artifact_base(project))
    root = artifact_root(project)
    for name in (*_RECEIPTS, _OWNER_FILE):
        tree.remove(root / name)
    _write_stamp(locations, project.name, incarnation)


def ensure_artifact_root(project: CatalogProject) -> None:
    """Create the view's generated-state directory and keep it out of Git.

    Raises ``FileNotFoundError`` when the view project no longer exists, so a
    late writer cannot recreate state for a removed view.
    """
    root = artifact_root(project)
    base = artifact_base(project)
    project.root.lstat()
    if _outside_project(project):
        try:
            base.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            raise ConfigurationError(
                f"Could not create the view state directory {base}: {error}. "
                "Make that folder writable, or choose another location with "
                f"state_dir or {STATE_DIR_ENV}."
            ) from error
        _ensure_private_state_root(project)
    ensure_secure_directory(base, root, "Artifact control root")
    if not os.path.lexists(project.root):
        remove_artifact_state(project)
        raise FileNotFoundError(f"View project was removed: {project.root}")
    ignore_generated_directory(FileTree(base), root)


def _ensure_private_state_root(project: CatalogProject) -> None:
    # Build state can hold data derived from the notebook, so other accounts
    # on a shared host cannot list or read a notebook's state folder.
    base = artifact_base(project)
    state_root = project.locations.state_root
    ensure_secure_directory(base, state_root.parent, "View state directory")
    with suppress(FileExistsError):
        FileTree(base).create_directory(state_root)


def _discard(tree: FileTree, directory: Path) -> None:
    # Moving the state aside first lets readers see it whole or not at all.
    aside = directory.parent.parent / temporary_name("aside")
    tree.publish(directory, aside)
    tree.remove(aside)


def remove_artifact_state(project: CatalogProject) -> None:
    """Delete a view's generated state when the view is removed or created.

    Only ``.artifacts`` is removed. Generated state can be rebuilt, so a
    failure leaves the directory for the next view with this name to discard.
    """
    if not _outside_project(project):
        return
    root = artifact_root(project)
    tree = FileTree(artifact_base(project))
    try:
        if _holds_project(tree, root.parent) or not tree.exists(root):
            return
        _discard(tree, root)
        tree.remove_empty_directory(root.parent)
    except (OSError, ConfigurationError) as error:
        _LOGGER.warning(
            "Studio could not delete the generated state of view %r in %s: %s",
            project.name,
            root,
            error,
        )


def move_artifact_state(project: CatalogProject, target: CatalogProject) -> None:
    """Carry a renamed view's generated state to its new name.

    Pass the state only after ``owns_artifact_state(project)`` held before the
    rename changed the owner records, because the move claims it for the new
    name. State inside the project moves with the project directory.
    Otherwise a failed move removes both copies, and the next build starts
    clean.
    """
    if not _outside_project(project) or not _outside_project(target):
        return
    source = artifact_root(project)
    destination = artifact_root(target)
    tree = FileTree(artifact_base(project))
    try:
        if _holds_project(tree, source.parent) or _holds_project(
            tree, destination.parent
        ):
            return
        if tree.exists(destination):
            _discard(tree, destination)
        if tree.exists(source):
            tree.ensure_directory(destination.parent)
            tree.publish(source, destination)
            tree.remove_empty_directory(source.parent)
            incarnation = _incarnation(target.locations, target.name)
            if incarnation is not None:
                _write_stamp(target.locations, target.name, incarnation)
    except (OSError, ConfigurationError) as error:
        _LOGGER.warning(
            "Studio could not move the generated state of view %r to %r and "
            "will rebuild it: %s",
            project.name,
            target.name,
            error,
        )
        remove_artifact_state(project)
        remove_artifact_state(target)
