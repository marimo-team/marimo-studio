"""Open and replace contained files through stable directory ownership."""

from __future__ import annotations

import os
import secrets
import stat
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from pathlib import Path

from marimo_studio._filesystem._secure_conditional import (
    quarantine_if_identity as _quarantine_if_identity,
)
from marimo_studio._filesystem._secure_conditional import (
    replace_file_if_identity as _replace_file_if_identity,
)
from marimo_studio._filesystem._secure_operations import (
    atomic_write_at as _atomic_write_at,
)
from marimo_studio._filesystem._secure_operations import (
    create_file_at as _create_file_at,
)
from marimo_studio._filesystem._secure_operations import (
    directory_flags as _directory_flags,
)
from marimo_studio._filesystem._secure_operations import open_file_at as _open_file_at
from marimo_studio._filesystem._secure_operations import (
    open_or_create_file_at as _open_or_create_file_at,
)
from marimo_studio._filesystem._secure_operations import (
    regular_identity as _regular_identity,
)
from marimo_studio._filesystem._secure_operations import (
    remove_tree_at as _remove_tree_at,
)
from marimo_studio._filesystem._secure_operations import (
    write_file_if_absent_at as _write_file_if_absent_at,
)
from marimo_studio._filesystem._secure_rename import rename_if_absent
from marimo_studio._filesystem._secure_tree import (
    directory_entries_digest as _directory_entries_digest,
)
from marimo_studio._filesystem._secure_tree import (
    directory_identity as _directory_identity,
)
from marimo_studio._filesystem._secure_tree import (
    directory_tree_identity as _directory_tree_identity,
)
from marimo_studio._filesystem._secure_tree import (
    regular_file_sizes as _regular_file_sizes,
)
from marimo_studio._filesystem._secure_types import (
    ConditionalWriteError,
    FileIdentity,
    SecureFileError,
)
from marimo_studio._filesystem._secure_types import (
    ParentHandle as _ParentHandle,
)
from marimo_studio._filesystem._secure_windows import (
    close_handle as _close_windows_handle,
)
from marimo_studio._filesystem._secure_windows import (
    open_directory_handle as _windows_directory_handle,
)

_HAS_DESCRIPTOR_RELATIVE_FILES = (
    os.name != "nt"
    and hasattr(os, "O_DIRECTORY")
    and hasattr(os, "O_NOFOLLOW")
    and os.open in os.supports_dir_fd
    and os.link in os.supports_dir_fd
    and os.link in os.supports_follow_symlinks
    and os.rename in os.supports_dir_fd
    and os.rmdir in os.supports_dir_fd
    and os.stat in os.supports_dir_fd
    and os.stat in os.supports_follow_symlinks
    and os.unlink in os.supports_dir_fd
)


def _contained(root: Path, path: Path) -> tuple[Path, Path, Path]:
    if ".." in root.parts or ".." in path.parts:
        raise SecureFileError("Contained paths must not include parent segments")
    selected_root = root.absolute()
    selected_path = path.absolute()
    try:
        relative = selected_path.relative_to(selected_root)
    except ValueError as error:
        raise SecureFileError(
            f"Path is outside its owning root: {selected_path}"
        ) from error
    if not relative.parts:
        raise SecureFileError(f"A contained file path is required: {selected_path}")
    return selected_root, selected_path, relative


@contextmanager
def _posix_parent(root: Path, path: Path, relative: Path) -> Iterator[_ParentHandle]:
    flags = _directory_flags()
    if root.parent == root:
        descriptor = os.open(root, flags)
        components = relative.parts[:-1]
    else:
        descriptor = os.open(root.parent, flags)
        components = (root.name, *relative.parts[:-1])
    current = root.parent
    try:
        for component in components:
            next_descriptor = os.open(component, flags, dir_fd=descriptor)
            state = os.fstat(next_descriptor)
            if not stat.S_ISDIR(state.st_mode):
                os.close(next_descriptor)
                raise SecureFileError(
                    f"Contained path ancestor is not a directory: {current / component}"
                )
            os.close(descriptor)
            descriptor = next_descriptor
            current /= component
        yield _ParentHandle(path.parent, descriptor)
    finally:
        os.close(descriptor)


@contextmanager
def _windows_parent(path: Path) -> Iterator[_ParentHandle]:
    parent = path.parent.absolute()
    anchor = Path(parent.anchor)
    current = anchor
    handles = [_windows_directory_handle(anchor)]
    try:
        for component in parent.parts[1:]:
            current /= component
            handles.append(_windows_directory_handle(current))
        yield _ParentHandle(parent, None)
    finally:
        for handle in reversed(handles):
            _close_windows_handle(handle)


@contextmanager
def secure_parent(root: Path, path: Path) -> Iterator[_ParentHandle]:
    """Hold the contained file's parent stable for one filesystem operation."""
    selected_root, selected_path, relative = _contained(root, path)
    if os.name == "nt":
        with _windows_parent(selected_path) as parent:
            yield parent
        return
    if not _HAS_DESCRIPTOR_RELATIVE_FILES:
        raise SecureFileError("Descriptor-relative file operations are unavailable")
    with _posix_parent(selected_root, selected_path, relative) as parent:
        yield parent


class SecureDirectory:
    """Keep one directory owner stable across a multi-file transaction."""

    def __init__(self, root: Path, owner: _ParentHandle) -> None:
        self.root = root.absolute()
        self._owner = owner

    @contextmanager
    def _parent(self, path: Path) -> Iterator[_ParentHandle]:
        _root, selected_path, relative = _contained(self.root, path)
        if os.name == "nt":
            with _windows_parent(selected_path) as parent:
                yield parent
            return
        if self._owner.descriptor is None:
            raise SecureFileError("The secure directory descriptor is unavailable")
        descriptor = os.dup(self._owner.descriptor)
        current = self.root
        flags = _directory_flags()
        try:
            for component in relative.parts[:-1]:
                next_descriptor = os.open(component, flags, dir_fd=descriptor)
                os.close(descriptor)
                descriptor = next_descriptor
                current /= component
            yield _ParentHandle(selected_path.parent, descriptor)
        finally:
            os.close(descriptor)

    def open_file(self, path: Path, flags: int = os.O_RDONLY) -> int:
        with self._parent(path) as parent:
            return _open_file_at(parent, path, flags)

    def file_identity(self, path: Path) -> FileIdentity:
        """Capture one regular file identity through its stable parent."""
        descriptor = self.open_file(path)
        try:
            return _regular_identity(descriptor)
        finally:
            os.close(descriptor)

    def ensure_attached(self, expected: FileIdentity | None = None) -> None:
        """Require the held directory incarnation to remain at its path."""
        if self._owner.descriptor is None:
            handle = _windows_directory_handle(self.root)
            _close_windows_handle(handle)
            current = self.root.stat(follow_symlinks=False)
            held = current
        else:
            held = os.fstat(self._owner.descriptor)
            try:
                current = self.root.stat(follow_symlinks=False)
            except OSError as error:
                raise SecureFileError(
                    f"Secure directory moved during the transaction: {self.root}"
                ) from error
        expected_matches = expected is None or (
            expected.directory
            and held.st_dev == expected.device
            and held.st_ino == expected.inode
            and held.st_mode == expected.mode
        )
        if not expected_matches or (
            stat.S_ISLNK(current.st_mode)
            or not stat.S_ISDIR(current.st_mode)
            or current.st_dev != held.st_dev
            or current.st_ino != held.st_ino
            or current.st_mode != held.st_mode
        ):
            raise SecureFileError(
                f"Secure directory moved during the transaction: {self.root}"
            )

    def atomic_write(
        self,
        path: Path,
        content: bytes,
        *,
        mode: int | None = None,
    ) -> FileIdentity:
        with self._parent(path) as parent:
            return _atomic_write_at(parent, path, content, mode=mode)

    def create_file(self, path: Path, mode: int = 0o600) -> int:
        with self._parent(path) as parent:
            return _create_file_at(parent, path, mode)

    def replace_file_if_identity(
        self,
        path: Path,
        content: bytes,
        expected: FileIdentity,
    ) -> FileIdentity:
        """Replace one regular file when its full identity is still current."""
        return _replace_file_if_identity(self, path, content, expected)

    def regular_file_sizes(
        self,
        *,
        max_entries: int,
    ) -> tuple[tuple[Path, int], ...]:
        """List one bounded regular-file tree through the stable root owner."""
        return _regular_file_sizes(
            self.root,
            self._owner,
            max_entries=max_entries,
        )

    def replace_with_copy(self, path: Path, *, expected_size: int) -> None:
        """Replace one regular file with a detached copy through its stable parent."""
        with self._parent(path) as parent:
            target: str | Path = path.name if parent.descriptor is not None else path
            source = _open_file_at(parent, path, os.O_RDONLY)
            temporary_name = f".{path.name}.{secrets.token_hex(16)}.detach"
            temporary: str | Path = (
                temporary_name
                if parent.descriptor is not None
                else parent.path / temporary_name
            )
            destination = -1
            temporary_exists = False
            try:
                before = os.fstat(source)
                if before.st_size != expected_size:
                    raise SecureFileError(f"Contained file changed before copy: {path}")
                destination = os.open(
                    temporary,
                    os.O_WRONLY
                    | os.O_CREAT
                    | os.O_EXCL
                    | getattr(os, "O_BINARY", 0)
                    | (os.O_NOFOLLOW if hasattr(os, "O_NOFOLLOW") else 0),
                    0o600,
                    dir_fd=parent.descriptor,
                )
                temporary_exists = True
                remaining = before.st_size
                while remaining:
                    chunk = os.read(source, min(1024 * 1024, remaining))
                    if not chunk:
                        raise SecureFileError(
                            f"Contained file changed while it was copied: {path}"
                        )
                    view = memoryview(chunk)
                    while view:
                        written = os.write(destination, view)
                        view = view[written:]
                    remaining -= len(chunk)
                if os.read(source, 1):
                    raise SecureFileError(
                        f"Contained file changed while it was copied: {path}"
                    )
                after = os.fstat(source)
                current = os.stat(
                    target,
                    dir_fd=parent.descriptor,
                    follow_symlinks=False,
                )
                stable = (
                    before.st_dev == after.st_dev == current.st_dev
                    and before.st_ino == after.st_ino == current.st_ino
                    and before.st_size == after.st_size == current.st_size
                    and before.st_mtime_ns == after.st_mtime_ns
                    and before.st_ctime_ns == after.st_ctime_ns
                    and stat.S_ISREG(current.st_mode)
                )
                if not stable:
                    raise SecureFileError(
                        f"Contained file changed while it was copied: {path}"
                    )
                if hasattr(os, "fchmod"):
                    os.fchmod(destination, stat.S_IMODE(before.st_mode))
                os.fsync(destination)
                os.close(destination)
                destination = -1
                os.close(source)
                source = -1
                os.replace(
                    temporary,
                    target,
                    src_dir_fd=parent.descriptor,
                    dst_dir_fd=parent.descriptor,
                )
                temporary_exists = False
            finally:
                if source >= 0:
                    os.close(source)
                if destination >= 0:
                    os.close(destination)
                if temporary_exists:
                    with suppress(FileNotFoundError):
                        os.unlink(temporary, dir_fd=parent.descriptor)

    def open_or_create_file(self, path: Path, mode: int = 0o600) -> int:
        """Open one contained regular file, creating the leaf when absent."""
        with self._parent(path) as parent:
            return _open_or_create_file_at(parent, path, mode)

    def replace(self, source: Path, destination: Path) -> None:
        """Atomically replace one contained path through stable parents."""
        with (
            self._parent(source) as source_parent,
            self._parent(destination) as destination_parent,
        ):
            source_name: str | Path = (
                source.name if source_parent.descriptor is not None else source
            )
            destination_name: str | Path = (
                destination.name
                if destination_parent.descriptor is not None
                else destination
            )
            os.replace(
                source_name,
                destination_name,
                src_dir_fd=source_parent.descriptor,
                dst_dir_fd=destination_parent.descriptor,
            )

    def rename_if_absent(self, source: Path, destination: Path) -> None:
        """Atomically rename one contained directory if the leaf stays absent."""
        with (
            self._parent(source) as source_parent,
            self._parent(destination) as destination_parent,
        ):
            rename_if_absent(
                source_parent,
                source,
                destination_parent,
                destination,
            )

    def remove_tree(self, path: Path) -> None:
        """Remove one contained tree without following mutable links."""
        with self._parent(path) as parent:
            _remove_tree_at(parent, path)

    def _ensure_components(
        self,
        path: Path,
        components: tuple[str, ...],
        created_directories: dict[Path, FileIdentity] | None = None,
    ) -> tuple[Path, ...]:
        _root, _selected_path, _relative = _contained(self.root, path)
        created: list[Path] = []
        if os.name == "nt":
            current = self.root
            handles: list[int] = []
            try:
                for component in components:
                    current /= component
                    try:
                        handle = _windows_directory_handle(current)
                    except FileNotFoundError:
                        created_here = False
                        with suppress(FileExistsError):
                            os.mkdir(current)
                            created.append(current)
                            created_here = True
                        handle = _windows_directory_handle(current)
                        if created_directories is not None and created_here:
                            state = current.stat(follow_symlinks=False)
                            created_directories[current] = _directory_identity(state)
                    handles.append(handle)
            finally:
                for handle in reversed(handles):
                    _close_windows_handle(handle)
            return tuple(created)
        if self._owner.descriptor is None:
            raise SecureFileError("The secure directory descriptor is unavailable")
        descriptor = os.dup(self._owner.descriptor)
        current = self.root
        flags = _directory_flags()
        try:
            for component in components:
                current /= component
                try:
                    next_descriptor = os.open(component, flags, dir_fd=descriptor)
                except FileNotFoundError:
                    created_here = False
                    with suppress(FileExistsError):
                        os.mkdir(component, dir_fd=descriptor)
                        created.append(current)
                        created_here = True
                    next_descriptor = os.open(component, flags, dir_fd=descriptor)
                    if created_directories is not None and created_here:
                        state = os.fstat(next_descriptor)
                        created_directories[current] = _directory_identity(state)
                os.close(descriptor)
                descriptor = next_descriptor
        finally:
            os.close(descriptor)
        return tuple(created)

    def ensure_parent(
        self,
        path: Path,
        created_directories: dict[Path, FileIdentity] | None = None,
    ) -> tuple[Path, ...]:
        """Create missing contained parent directories through the root owner."""
        _root, _selected_path, relative = _contained(self.root, path)
        return self._ensure_components(
            path,
            relative.parts[:-1],
            created_directories,
        )

    def ensure_directory(self, path: Path) -> tuple[Path, ...]:
        """Create one contained directory path through the root owner."""
        _root, _selected_path, relative = _contained(self.root, path)
        return self._ensure_components(path, relative.parts)

    def create_directory(self, path: Path, mode: int = 0o700) -> FileIdentity:
        """Publish one empty directory while its destination remains absent."""
        with self._parent(path) as parent:
            temporary_name = f".{path.name}.{secrets.token_hex(8)}.claim"
            temporary = path.with_name(temporary_name)
            target: str | Path = (
                temporary_name if parent.descriptor is not None else temporary
            )
            temporary_exists = False
            try:
                os.mkdir(target, mode, dir_fd=parent.descriptor)
                temporary_exists = True
                state = os.stat(
                    target,
                    dir_fd=parent.descriptor,
                    follow_symlinks=False,
                )
                if stat.S_ISLNK(state.st_mode) or not stat.S_ISDIR(state.st_mode):
                    raise SecureFileError(
                        f"Contained path is not a stable directory: {path}"
                    )
                identity = _directory_identity(state)
                rename_if_absent(parent, temporary, parent, path)
                temporary_exists = False
                return identity
            finally:
                if temporary_exists:
                    with suppress(OSError):
                        os.rmdir(target, dir_fd=parent.descriptor)

    def children(self) -> tuple[Path, ...]:
        """List direct children through the stable root owner."""
        if self._owner.descriptor is not None:
            names = os.listdir(self._owner.descriptor)
        else:
            names = os.listdir(self.root)
        return tuple(self.root / name for name in names)

    def directory_identity(self, path: Path) -> FileIdentity:
        """Capture one contained directory identity while its parent is stable."""
        with self._parent(path) as parent:
            target: str | Path = path.name if parent.descriptor is not None else path
            if parent.descriptor is not None:
                descriptor = os.open(
                    target, _directory_flags(), dir_fd=parent.descriptor
                )
                try:
                    state = os.fstat(descriptor)
                    digest = _directory_entries_digest(parent, target)
                finally:
                    os.close(descriptor)
            else:
                handle = _windows_directory_handle(path) if os.name == "nt" else None
                try:
                    state = path.stat(follow_symlinks=False)
                    digest = _directory_entries_digest(parent, target)
                finally:
                    if handle is not None:
                        _close_windows_handle(handle)
            if stat.S_ISLNK(state.st_mode) or not stat.S_ISDIR(state.st_mode):
                raise SecureFileError(f"Contained path is not a directory: {path}")
            return FileIdentity(
                state.st_dev,
                state.st_ino,
                state.st_mode,
                0,
                digest,
                True,
            )

    def directory_tree_identity(
        self,
        path: Path,
        *,
        max_entries: int,
    ) -> tuple[tuple[object, ...], ...] | None:
        """Capture a bounded directory tree through the stable root owner."""
        return _directory_tree_identity(
            self._parent,
            path,
            max_entries=max_entries,
        )

    def quarantine_if_identity(
        self,
        path: Path,
        expected: FileIdentity,
    ) -> Path:
        """Move one leaf aside atomically, then verify the moved identity."""
        return _quarantine_if_identity(self._parent, path, expected)

    def unlink(self, path: Path) -> None:
        with self._parent(path) as parent:
            target: str | Path = path.name if parent.descriptor is not None else path
            os.unlink(target, dir_fd=parent.descriptor)

    def rmdir(self, path: Path) -> None:
        with self._parent(path) as parent:
            target: str | Path = path.name if parent.descriptor is not None else path
            os.rmdir(target, dir_fd=parent.descriptor)

    def quarantine_directory_if_identity(
        self,
        path: Path,
        expected: FileIdentity,
    ) -> Path:
        """Move one created directory aside, then verify its empty identity."""
        with self._parent(path) as parent:
            target: str | Path = path.name if parent.descriptor is not None else path
            quarantine_name = f".{path.name}.rollback-{secrets.token_hex(8)}"
            quarantine: str | Path = (
                quarantine_name
                if parent.descriptor is not None
                else parent.path / quarantine_name
            )
            os.rename(
                target,
                quarantine,
                src_dir_fd=parent.descriptor,
                dst_dir_fd=parent.descriptor,
            )
            state = os.stat(
                quarantine,
                dir_fd=parent.descriptor,
                follow_symlinks=False,
            )
            if stat.S_ISDIR(state.st_mode):
                actual = FileIdentity(
                    state.st_dev,
                    state.st_ino,
                    state.st_mode,
                    0,
                    _directory_entries_digest(parent, quarantine),
                    True,
                )
                if actual == expected:
                    return path.with_name(quarantine_name)
            recovery = path.with_name(quarantine_name)
            try:
                rename_if_absent(parent, recovery, parent, path)
            except OSError as restore_error:
                raise ConditionalWriteError(
                    "Contained directory changed before rollback and was preserved",
                    recovery=recovery,
                ) from restore_error
            raise ConditionalWriteError(
                "Contained directory changed before rollback and was restored"
            )

    def restore_file_if_absent(
        self,
        path: Path,
        content: bytes,
        mode: int,
    ) -> FileIdentity:
        with self._parent(path) as parent:
            return _write_file_if_absent_at(parent, path, content, mode)

    def write_file_if_absent(
        self,
        path: Path,
        content: bytes,
        mode: int = 0o600,
    ) -> FileIdentity:
        """Write one complete file when its leaf remains absent."""
        with self._parent(path) as parent:
            return _write_file_if_absent_at(parent, path, content, mode)


@contextmanager
def secure_directory(root: Path) -> Iterator[SecureDirectory]:
    """Hold one root stable across a sequence of contained operations."""
    placeholder = root.absolute() / ".marimo-studio-owner"
    with secure_parent(root, placeholder) as owner:
        yield SecureDirectory(root, owner)


def open_contained_file(root: Path, path: Path, flags: int = os.O_RDONLY) -> int:
    """Open one file through a stable, non-following parent directory."""
    with secure_parent(root, path) as parent:
        return _open_file_at(parent, path, flags)


def atomic_write_contained(
    root: Path,
    path: Path,
    content: bytes,
    *,
    mode: int | None = None,
) -> FileIdentity:
    """Replace one file through a temporary sibling owned by a stable parent."""
    with secure_parent(root, path) as parent:
        return _atomic_write_at(parent, path, content, mode=mode)
