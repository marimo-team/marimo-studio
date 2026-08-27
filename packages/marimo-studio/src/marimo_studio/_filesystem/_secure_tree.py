"""Inspect bounded directory trees through stable owners."""

from __future__ import annotations

import hashlib
import os
import stat
from pathlib import Path

from marimo_studio._filesystem._secure_operations import directory_flags
from marimo_studio._filesystem._secure_types import (
    FileIdentity,
    ParentContext,
    ParentHandle,
    SecureFileError,
)
from marimo_studio._filesystem._secure_windows import (
    close_handle as close_windows_handle,
)
from marimo_studio._filesystem._secure_windows import (
    open_directory_handle as open_windows_directory,
)

_EMPTY_DIRECTORY_DIGEST = hashlib.sha256(b"").digest()


def directory_identity(state: os.stat_result) -> FileIdentity:
    return FileIdentity(
        state.st_dev,
        state.st_ino,
        state.st_mode,
        0,
        _EMPTY_DIRECTORY_DIGEST,
        True,
    )


def directory_entries_digest(parent: ParentHandle, target: str | Path) -> bytes:
    descriptor: int | None = None
    try:
        if parent.descriptor is not None:
            descriptor = os.open(target, directory_flags(), dir_fd=parent.descriptor)
            names = os.listdir(descriptor)
        else:
            names = os.listdir(target)
        digest = hashlib.sha256()
        for name in sorted(names):
            encoded = os.fsencode(name)
            digest.update(len(encoded).to_bytes(4, "big"))
            digest.update(encoded)
        return digest.digest()
    finally:
        if descriptor is not None:
            os.close(descriptor)


def regular_file_sizes(
    root: Path,
    owner: ParentHandle,
    *,
    max_entries: int,
) -> tuple[tuple[Path, int], ...]:
    """List one bounded regular-file tree through the stable root owner."""
    files: list[tuple[Path, int]] = []
    entries = 0

    def record(path: Path, state: os.stat_result) -> None:
        nonlocal entries
        entries += 1
        if entries > max_entries:
            raise SecureFileError(
                f"Contained tree contains more than {max_entries} entries: {root}"
            )
        if stat.S_ISLNK(state.st_mode):
            raise SecureFileError(f"Contained tree contains a symlink: {path}")
        if stat.S_ISREG(state.st_mode):
            files.append((path, state.st_size))
            return
        if not stat.S_ISDIR(state.st_mode):
            raise SecureFileError(
                f"Contained tree contains a non-regular entry: {path}"
            )

    if owner.descriptor is None:

        def visit_windows(directory: Path) -> None:
            handle = open_windows_directory(directory)
            try:
                with os.scandir(directory) as children:
                    for child in sorted(children, key=lambda entry: entry.name):
                        path = directory / child.name
                        state = child.stat(follow_symlinks=False)
                        record(path, state)
                        if stat.S_ISDIR(state.st_mode):
                            visit_windows(path)
            finally:
                close_windows_handle(handle)

        visit_windows(root)
        return tuple(files)

    def visit_posix(descriptor: int, directory: Path) -> None:
        for name in sorted(os.listdir(descriptor)):
            path = directory / name
            state = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
            record(path, state)
            if stat.S_ISDIR(state.st_mode):
                child = os.open(name, directory_flags(), dir_fd=descriptor)
                try:
                    visit_posix(child, path)
                finally:
                    os.close(child)

    descriptor = os.dup(owner.descriptor)
    try:
        visit_posix(descriptor, root)
    finally:
        os.close(descriptor)
    return tuple(files)


def directory_tree_identity(
    parent_context: ParentContext,
    path: Path,
    *,
    max_entries: int,
) -> tuple[tuple[object, ...], ...] | None:
    """Capture a bounded directory tree through its stable parent."""
    identity: list[tuple[object, ...]] = []
    entries = 0

    def record(relative: Path, state: os.stat_result) -> None:
        nonlocal entries
        entries += 1
        if entries > max_entries:
            raise SecureFileError(
                f"Contained tree contains more than {max_entries} entries: {path}"
            )
        identity.append(
            (
                relative.as_posix(),
                state.st_mode,
                state.st_mtime_ns,
                state.st_ctime_ns,
                state.st_size,
                state.st_ino,
            )
        )

    with parent_context(path) as parent:
        target: str | Path = path.name if parent.descriptor is not None else path
        try:
            root_state = os.stat(
                target,
                dir_fd=parent.descriptor,
                follow_symlinks=False,
            )
        except FileNotFoundError:
            return None
        if stat.S_ISLNK(root_state.st_mode) or not stat.S_ISDIR(root_state.st_mode):
            raise SecureFileError(f"Contained path is not a directory: {path}")
        identity.append((".", root_state.st_mode, root_state.st_dev, root_state.st_ino))

        if parent.descriptor is None:

            def visit_windows(directory: Path, relative: Path) -> None:
                handle = open_windows_directory(directory)
                try:
                    with os.scandir(directory) as children:
                        for child in sorted(children, key=lambda item: item.name):
                            child_path = directory / child.name
                            child_relative = relative / child.name
                            state = child.stat(follow_symlinks=False)
                            record(child_relative, state)
                            if stat.S_ISDIR(state.st_mode):
                                visit_windows(child_path, child_relative)
                finally:
                    close_windows_handle(handle)

            visit_windows(path, Path())
            return tuple(identity)

        descriptor = os.open(target, directory_flags(), dir_fd=parent.descriptor)

        def visit_posix(directory: int, relative: Path) -> None:
            for name in sorted(os.listdir(directory)):
                child_relative = relative / name
                state = os.stat(
                    name,
                    dir_fd=directory,
                    follow_symlinks=False,
                )
                record(child_relative, state)
                if stat.S_ISDIR(state.st_mode):
                    child = os.open(name, directory_flags(), dir_fd=directory)
                    try:
                        visit_posix(child, child_relative)
                    finally:
                        os.close(child)

        try:
            visit_posix(descriptor, Path())
        finally:
            os.close(descriptor)
    return tuple(identity)
