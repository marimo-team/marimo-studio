"""Serialize one view's artifact publication across threads and processes."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import ExitStack, contextmanager

from marimo_studio._artifacts.paths import (
    artifact_root,
    assert_secure_path,
)
from marimo_studio._filesystem.files import FileTree
from marimo_studio.errors import ConfigurationError
from marimo_studio.view_providers import ViewProject


@contextmanager
def _view_lock(
    project: ViewProject,
    filename: str,
    label: str,
    *,
    blocking: bool = True,
    create: bool = True,
) -> Iterator[bool]:
    control_root = artifact_root(project)
    lock_path = control_root / filename
    assert_secure_path(project.root, lock_path, label)
    with ExitStack() as owner:
        try:
            acquired = owner.enter_context(
                FileTree(project.root).lock(lock_path, blocking=blocking, create=create)
            )
        except ConfigurationError:
            raise
        except OSError as error:
            raise ConfigurationError(f"Could not open {label}: {lock_path}") from error
        yield acquired


@contextmanager
def artifact_lock(
    project: ViewProject,
    *,
    blocking: bool = True,
    create: bool = True,
) -> Iterator[bool]:
    """Acquire the short view-local publication and lease lock."""
    with _view_lock(
        project,
        ".publication.lock",
        "Artifact publication lock",
        blocking=blocking,
        create=create,
    ) as acquired:
        yield acquired


@contextmanager
def build_lock(
    project: ViewProject,
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
