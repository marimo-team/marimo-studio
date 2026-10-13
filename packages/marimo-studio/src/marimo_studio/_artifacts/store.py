"""Own the directory that holds one view's generated state.

Each catalog view keeps receipts, revisions, pins, and provider caches in
``artifact_root(project)``, under marimo's output directory and outside the
authored project. The directory ignores itself in Git and can be deleted to
force a clean rebuild.

State outside the project is named after its view, so it records the view
incarnation it belongs to: the generation in the catalog's ``.owners/``
record. A view that was deleted and recreated outside Studio, or by a process
with another cache prefix, therefore reads the old state as unbuilt, and its
next build discards that state's receipts.

A Studio 0.3.0 default catalog keeps state inside each view, where the
project directory owns its lifetime. A view in a configured catalog can still
contain ``.artifacts/`` from Studio 0.3.0. The first build after an upgrade
moves it to the current location when no process is using it, so the retained
revisions stay usable without another provider build.
"""

from __future__ import annotations

import logging
import os
import stat
from pathlib import Path

from marimo_studio._artifacts.paths import (
    artifact_base,
    artifact_root,
    ensure_secure_directory,
    project_artifacts,
)
from marimo_studio._filesystem.files import FileTree
from marimo_studio._filesystem.ignore import ignore_generated_directory
from marimo_studio._filesystem.names import temporary_name
from marimo_studio._filesystem.paths import is_within
from marimo_studio._workspace.locations import VIEW_MANIFEST, is_legacy_view_root
from marimo_studio._workspace.project_manifest import CatalogProject
from marimo_studio._workspace.view_owners import view_owner_snapshot
from marimo_studio.errors import ConfigurationError

_LOGGER = logging.getLogger("marimo.studio")
_OWNER_FILE = "owner"
_OWNER_MAX_BYTES = 128
_RECEIPTS = ("development.json", "production.json")


def _outside_project(project: CatalogProject) -> bool:
    return artifact_base(project) != project.root


def _shares_project(project: CatalogProject) -> bool:
    directory = artifact_root(project).parent
    return is_within(directory, project.root) or is_within(project.root, directory)


def _holds_project(tree: FileTree, directory: Path) -> bool:
    # A view manifest marks authored files that generated-state cleanup must
    # never remove, whatever path spelling led here.
    return tree.exists(directory / VIEW_MANIFEST)


def _owner_generation(project: CatalogProject) -> str | None:
    try:
        owner, _identity = view_owner_snapshot(project.root.parent, project.name)
    except (OSError, ConfigurationError):
        return None
    return owner.generation if owner is not None else None


def _stamp(project: CatalogProject) -> str | None:
    tree = FileTree(artifact_base(project))
    try:
        content = tree.read(
            artifact_root(project) / _OWNER_FILE, max_bytes=_OWNER_MAX_BYTES
        ).content
    except FileNotFoundError:
        return None
    except (OSError, ConfigurationError):
        return ""
    return content.decode("ascii", errors="replace").strip()


def _write_stamp(project: CatalogProject, owner: str) -> None:
    FileTree(artifact_base(project)).write(
        artifact_root(project) / _OWNER_FILE, owner.encode("ascii")
    )


def owns_artifact_state(project: CatalogProject) -> bool:
    """Return whether the view's state belongs to its current incarnation.

    State without a stamp, such as state a build adopted, belongs to the view
    that claims it next.
    """
    if not _outside_project(project):
        return True
    stamp = _stamp(project)
    if stamp is None:
        return True
    owner = _owner_generation(project)
    return owner is None or stamp == owner


def _claim_artifact_state(project: CatalogProject) -> None:
    owner = _owner_generation(project)
    if owner is None:
        return
    stamp = _stamp(project)
    if stamp == owner:
        return
    if stamp is not None:
        tree = FileTree(artifact_base(project))
        root = artifact_root(project)
        for receipt in _RECEIPTS:
            tree.remove(root / receipt)
    _write_stamp(project, owner)


def ensure_artifact_root(project: CatalogProject) -> None:
    """Create the view's generated-state directory and keep it out of Git.

    State that an earlier incarnation of the view left under its name loses
    its receipts here, so revisions without a receipt or pin get pruned.
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
                "Make that folder writable, or set PYTHONPYCACHEPREFIX to a "
                "writable folder."
            ) from error
    ensure_secure_directory(base, root, "Artifact control root")
    if not os.path.lexists(project.root):
        remove_artifact_state(project)
        raise FileNotFoundError(f"View project was removed: {project.root}")
    ignore_generated_directory(FileTree(base), root)
    if _outside_project(project):
        _claim_artifact_state(project)


def _unused(tree: FileTree, legacy: Path) -> bool:
    for name in (".publication.lock", ".build.lock"):
        with tree.lock(legacy / name, blocking=False, create=False) as acquired:
            if not acquired and tree.exists(legacy / name):
                return False
    pins = legacy / ".pins"
    if not tree.is_directory(pins):
        return True
    for revision in tree.children(pins):
        for pin in tree.children(revision):
            # A pin whose holder exited unlocks, so a held lock is a live reader.
            with tree.lock(pin, blocking=False, create=False) as stale:
                if not stale:
                    return False
    return True


def _move_directory(source: Path, destination: Path) -> None:
    os.rename(source, destination)


def adopt_project_artifacts(project: CatalogProject) -> None:
    """Move state that Studio 0.3.0 left inside a configured catalog's view.

    Call this from the build owner before it creates generated state. A view
    in a Studio 0.3.0 default catalog keeps its state in place, because
    processes that run without a cache prefix still use it there. A held lock
    or live pin, a move across file systems, or existing current state leave
    the older directory in place, where source and input scans skip it.
    """
    legacy = project_artifacts(project)
    root = artifact_root(project)
    if legacy == root or is_legacy_view_root(project.root.parent):
        return
    try:
        legacy_state = legacy.lstat()
    except FileNotFoundError:
        return
    if not stat.S_ISDIR(legacy_state.st_mode) or os.path.lexists(root):
        return
    try:
        if not _unused(FileTree(project.root), legacy):
            return
        base = artifact_base(project)
        base.mkdir(parents=True, exist_ok=True)
        ensure_secure_directory(base, root.parent, "View state directory")
        _move_directory(legacy, root)
    except (OSError, ConfigurationError) as error:
        _LOGGER.info(
            "Studio left the earlier generated state of view %r in %s and "
            "will rebuild it in %s: %s",
            project.name,
            legacy,
            root,
            error,
        )


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
    if _shares_project(project):
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

    State inside the project moves with the project directory. Otherwise a
    failed move removes both copies, and the next build starts clean.
    """
    if _shares_project(project) or _shares_project(target):
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
            owner = _owner_generation(target)
            if owner is not None:
                _write_stamp(target, owner)
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
