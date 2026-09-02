"""Serialize one view's artifact publication across threads and processes."""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager

from marimo_studio._artifacts.paths import (
    artifact_root,
    assert_secure_path,
)
from marimo_studio._filesystem.file_lock import (
    acquire_file_lock,
    release_file_lock,
)
from marimo_studio._filesystem.secure import secure_directory
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
    if not create and (not project.root.is_dir() or not control_root.is_dir()):
        yield False
        return
    assert_secure_path(project.root, control_root, "Artifact control root")
    lock_path = control_root / filename
    assert_secure_path(project.root, lock_path, label)
    owner = ExitStack()
    try:
        filesystem = owner.enter_context(secure_directory(project.root))
        if create:
            filesystem.ensure_directory(control_root)
            descriptor = filesystem.open_or_create_file(lock_path)
        else:
            descriptor = filesystem.open_file(lock_path, os.O_RDWR)
    except FileNotFoundError as error:
        owner.close()
        if not create:
            yield False
            return
        raise ConfigurationError(f"Could not open {label}: {lock_path}") from error
    except OSError as error:
        owner.close()
        raise ConfigurationError(f"Could not open {label}: {lock_path}") from error
    acquired = False
    try:
        acquired = acquire_file_lock(descriptor, blocking=blocking)
        yield acquired
    finally:
        if acquired:
            release_file_lock(descriptor)
        os.close(descriptor)
        owner.close()


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
