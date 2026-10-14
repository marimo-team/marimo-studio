"""Serialize one view's artifact publication across threads and processes."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import ExitStack, contextmanager

from marimo_studio._artifacts.paths import (
    artifact_base,
    artifact_root,
    assert_secure_path,
)
from marimo_studio._artifacts.store import (
    claim_artifact_state,
    ensure_artifact_root,
)
from marimo_studio._filesystem.files import FileTree
from marimo_studio._workspace.project_manifest import CatalogProject
from marimo_studio.errors import ConfigurationError


@contextmanager
def _view_lock(
    project: CatalogProject,
    filename: str,
    label: str,
    *,
    blocking: bool = True,
    create: bool = True,
) -> Iterator[bool]:
    if create:
        ensure_artifact_root(project)
    base = artifact_base(project)
    lock_path = artifact_root(project) / filename
    assert_secure_path(base, lock_path, label)
    with ExitStack() as owner:
        try:
            acquired = owner.enter_context(
                FileTree(base).lock(lock_path, blocking=blocking, create=create)
            )
        except ConfigurationError:
            raise
        except OSError as error:
            raise ConfigurationError(f"Could not open {label}: {lock_path}") from error
        yield acquired


@contextmanager
def artifact_lock(
    project: CatalogProject,
    *,
    blocking: bool = True,
    create: bool = True,
) -> Iterator[bool]:
    """Acquire the short view-local publication and lease lock.

    Creating the lock also claims the view's state for its current
    incarnation, so receipts change only under this lock.
    """
    with _view_lock(
        project,
        ".publication.lock",
        "Artifact publication lock",
        blocking=blocking,
        create=create,
    ) as acquired:
        if acquired and create:
            claim_artifact_state(project)
        yield acquired


@contextmanager
def build_lock(
    project: CatalogProject,
    *,
    blocking: bool = True,
    create: bool = True,
) -> Iterator[bool]:
    """Serialize provider work independently from publication and lease reads."""
    with _view_lock(
        project,
        ".build.lock",
        "Artifact build lock",
        blocking=blocking,
        create=create,
    ) as acquired:
        yield acquired
