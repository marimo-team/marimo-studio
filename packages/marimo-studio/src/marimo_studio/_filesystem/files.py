"""Read, write, publish, and remove files contained in one workspace root.

``FileTree`` owns Studio's changes to workspace and artifact files. Each verb
resolves its path from the root through directory descriptors that never follow
a symlink, uses the strongest primitive the filesystem offers, and flushes the
affected directory before it returns. Callers express
preconditions with ``Version`` values and never coordinate temporary files,
identity checks, or syncs themselves.

Windows has no descriptor-relative file API. There, each verb checks the
path for symlinks and junctions before it acts.
"""

from __future__ import annotations

import errno
import hashlib
import os
import stat
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager, suppress
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Final, Literal

from marimo_studio._filesystem import _locks
from marimo_studio._filesystem._entry import (
    DESCRIPTORS,
    FILE_FLAGS,
    Entry,
    changed,
    is_link,
    open_directory,
    retry_while_shared,
)
from marimo_studio._filesystem._publish import move_aside, publish_entry
from marimo_studio._filesystem.budgets import FileBudget
from marimo_studio._filesystem.errors import (
    ConcurrentChangeError,
    FileAccessError,
    FileTooLargeError,
    UnsafePathError,
)
from marimo_studio._filesystem.ingest import IngestedFile, copy_tree
from marimo_studio._filesystem.names import temporary_name

_CHUNK_BYTES = 1024 * 1024
WORKSPACE_FILE_MAX_BYTES = 64 * 1024 * 1024
_NEW_FILE_MODE = 0o600
_NEW_DIRECTORY_MODE = 0o700
# O_NONBLOCK keeps a FIFO swapped in at a read path from blocking the open.
_READ_FLAGS = os.O_RDONLY | FILE_FLAGS | getattr(os, "O_NONBLOCK", 0)
_CREATE_FLAGS = os.O_WRONLY | os.O_CREAT | os.O_EXCL | FILE_FLAGS


@dataclass(frozen=True)
class Version:
    """Identify one file or directory incarnation and its content.

    Compare versions for equality only. A file version covers its inode, mode,
    size, and SHA-256 content digest. A directory version covers its inode,
    mode, and the names of its direct entries.
    """

    _kind: Literal["file", "directory"]
    _device: int
    _inode: int
    _mode: int
    _size: int
    _digest: bytes


@dataclass(frozen=True)
class TreeVersion:
    """Identify one directory tree by every entry's path, inode, and metadata.

    A symlink counts as an entry of the tree and is never followed.
    """

    _entries: tuple[tuple[object, ...], ...]


class _Absent:
    def __repr__(self) -> str:
        return "ABSENT"


ABSENT: Final = _Absent()
"""Expect the target to be absent."""

Expectation = Version | _Absent | None


class ConditionalWriteError(OSError):
    """Report a write or removal whose expected version no longer matched.

    ``recovery`` names a preserved copy of displaced content. ``committed``
    is the version of new content that landed before cleanup failed.
    """

    def __init__(
        self,
        message: str,
        *,
        recovery: Path | None = None,
        committed: Version | None = None,
    ) -> None:
        super().__init__(message)
        self.recovery = recovery
        self.committed = committed


@dataclass(frozen=True)
class Snapshot:
    """Complete file content with its permission bits and version."""

    content: bytes
    mode: int
    version: Version


def _file_version(state: os.stat_result, digest: bytes) -> Version:
    return Version(
        "file",
        state.st_dev,
        state.st_ino,
        state.st_mode,
        state.st_size,
        digest,
    )


def _directory_version(state: os.stat_result, names: list[str]) -> Version:
    digest = hashlib.sha256()
    for name in sorted(names):
        encoded = os.fsencode(name)
        digest.update(len(encoded).to_bytes(4, "big"))
        digest.update(encoded)
    return Version(
        "directory",
        state.st_dev,
        state.st_ino,
        state.st_mode,
        0,
        digest.digest(),
    )


_PASSTHROUGH_ERRORS = (
    FileNotFoundError,
    ConditionalWriteError,
    UnsafePathError,
    ConcurrentChangeError,
    FileTooLargeError,
)


@contextmanager
def _access(action: str, path: Path) -> Iterator[None]:
    try:
        yield
    except _PASSTHROUGH_ERRORS:
        raise
    except OSError as error:
        reason = error.strerror or str(error)
        raise FileAccessError(f"Could not {action} {path}: {reason}") from error


def _lstat(entry: Entry) -> os.stat_result | None:
    try:
        return os.stat(entry.name, dir_fd=entry.parent, follow_symlinks=False)
    except FileNotFoundError:
        return None


def _sync(entry: Entry) -> None:
    # Some network and FUSE filesystems reject directory fsync, and Windows
    # entries carry no directory descriptor. Durability stays best effort.
    if entry.parent is not None:
        with suppress(OSError):
            os.fsync(entry.parent)


def _replace(source: Entry, target: Entry) -> None:
    retry_while_shared(
        lambda: os.replace(
            source.name,
            target.name,
            src_dir_fd=source.parent,
            dst_dir_fd=target.parent,
        )
    )


def _handle_state(handle: int | Path) -> os.stat_result:
    return os.fstat(handle) if isinstance(handle, int) else os.lstat(handle)


def _child_state(directory: int | Path, name: str) -> os.stat_result:
    if isinstance(directory, int):
        return os.stat(name, dir_fd=directory, follow_symlinks=False)
    return os.lstat(directory / name)


@contextmanager
def _child_directory(
    directory: int | Path, name: str, path: Path
) -> Iterator[int | Path]:
    if not isinstance(directory, int):
        yield directory / name
        return
    descriptor = open_directory(name, parent=directory, path=path)
    try:
        yield descriptor
    finally:
        os.close(descriptor)


def _visit(
    directory: int | Path,
    path: Path,
    counter: list[int],
    max_entries: int,
) -> Iterator[tuple[Path, os.stat_result]]:
    for name in sorted(os.listdir(directory)):
        entry = path / name
        state = _child_state(directory, name)
        counter[0] += 1
        if counter[0] > max_entries:
            raise UnsafePathError(
                f"Tree contains more than {max_entries} entries: {path}"
            )
        yield entry, state
        if stat.S_ISDIR(state.st_mode) and not is_link(state):
            with _child_directory(directory, name, entry) as child:
                yield from _visit(child, entry, counter, max_entries)


@contextmanager
def _entry_directory(entry: Entry) -> Iterator[int | Path]:
    if DESCRIPTORS:
        descriptor = open_directory(entry.name, parent=entry.parent, path=entry.path)
        try:
            yield descriptor
        finally:
            os.close(descriptor)
        return
    state = _lstat(entry)
    if state is None:
        raise FileNotFoundError(errno.ENOENT, "Directory is unavailable", entry.path)
    if is_link(state):
        raise UnsafePathError(f"Path is a symlink: {entry.path}")
    if not stat.S_ISDIR(state.st_mode):
        raise UnsafePathError(f"Path is not a directory: {entry.path}")
    yield entry.path


@contextmanager
def _entry_reader(entry: Entry) -> Iterator[tuple[BinaryIO, os.stat_result]]:
    if not DESCRIPTORS:
        state = _lstat(entry)
        if state is None:
            raise FileNotFoundError(errno.ENOENT, "File is unavailable", entry.path)
        if is_link(state):
            raise UnsafePathError(f"Path is a symlink: {entry.path}")
        # Windows refuses to open a directory as a file descriptor.
        if not stat.S_ISREG(state.st_mode):
            raise UnsafePathError(f"Path is not a regular file: {entry.path}")
        # A delete-sharing handle lets a concurrent rename move the file, as
        # an open descriptor allows on POSIX.
        from marimo_studio._filesystem._windows import open_file

        descriptor = open_file(entry.path, os.O_RDONLY)
    else:
        try:
            descriptor = os.open(entry.name, _READ_FLAGS, dir_fd=entry.parent)
        except OSError as error:
            if error.errno == errno.ELOOP:
                raise UnsafePathError(f"Path is a symlink: {entry.path}") from error
            raise
    before = os.fstat(descriptor)
    if not stat.S_ISREG(before.st_mode):
        os.close(descriptor)
        raise UnsafePathError(f"Path is not a regular file: {entry.path}")
    stream = os.fdopen(descriptor, "rb")
    try:
        yield stream, before
        if changed(before, os.fstat(stream.fileno())):
            raise ConcurrentChangeError(f"File changed while it was read: {entry.path}")
    finally:
        stream.close()


def _entry_version(entry: Entry) -> Version | None:
    state = _lstat(entry)
    if state is None:
        return None
    if is_link(state):
        raise UnsafePathError(f"Path is a symlink: {entry.path}")
    if stat.S_ISDIR(state.st_mode):
        with _entry_directory(entry) as directory:
            return _directory_version(_handle_state(directory), os.listdir(directory))
    digest = hashlib.sha256()
    with _entry_reader(entry) as (stream, opened):
        remaining = opened.st_size
        while remaining:
            chunk = stream.read(min(_CHUNK_BYTES, remaining))
            if not chunk:
                raise ConcurrentChangeError(
                    f"File changed while it was read: {entry.path}"
                )
            digest.update(chunk)
            remaining -= len(chunk)
        if stream.read(1):
            raise ConcurrentChangeError(f"File changed while it was read: {entry.path}")
    return _file_version(opened, digest.digest())


def _entry_tree_version(entry: Entry, max_entries: int) -> TreeVersion:
    with _entry_directory(entry) as directory:
        root = _handle_state(directory)
        entries: list[tuple[object, ...]] = [
            (".", root.st_mode, root.st_dev, root.st_ino)
        ]
        for path, state in _visit(directory, entry.path, [0], max_entries):
            relative = path.relative_to(entry.path).as_posix()
            if stat.S_ISDIR(state.st_mode) and not is_link(state):
                entries.append((relative, state.st_mode, state.st_dev, state.st_ino))
            else:
                entries.append(
                    (
                        relative,
                        state.st_mode,
                        state.st_mtime_ns,
                        state.st_ctime_ns,
                        state.st_size,
                        state.st_dev,
                        state.st_ino,
                    )
                )
    return TreeVersion(tuple(entries))


def _displaced_version(
    displaced: Entry,
    expect: Version | TreeVersion,
) -> Version | TreeVersion | None:
    try:
        if isinstance(expect, TreeVersion):
            return _entry_tree_version(displaced, len(expect._entries))
        return _entry_version(displaced)
    except (FileNotFoundError, UnsafePathError, ConcurrentChangeError):
        return None


def _unlink_link(entry: Entry) -> None:
    try:
        os.unlink(entry.name, dir_fd=entry.parent)
    except OSError:
        # Windows removes a directory junction as a directory.
        if os.name != "nt":
            raise
        os.rmdir(entry.path)


def _remove_entry(entry: Entry) -> None:
    # An entry that disappears during removal is already removed.
    state = _lstat(entry)
    if state is None:
        return
    with suppress(FileNotFoundError):
        if is_link(state):
            _unlink_link(entry)
        elif stat.S_ISDIR(state.st_mode):
            if entry.parent is None:
                _remove_windows_tree(entry.path)
            else:
                _remove_posix_tree(entry.parent, entry.path.name)
        else:
            if os.name == "nt" and not state.st_mode & stat.S_IWRITE:
                os.chmod(entry.path, stat.S_IWRITE)
            os.unlink(entry.name, dir_fd=entry.parent)


def _remove_posix_tree(parent: int, name: str) -> None:
    descriptor = open_directory(name, parent=parent, path=Path(name))
    try:
        for child in os.listdir(descriptor):
            _remove_entry(Entry(Path(name) / child, descriptor))
    finally:
        os.close(descriptor)
    os.rmdir(name, dir_fd=parent)


def _remove_windows_tree(path: Path) -> None:
    from marimo_studio._filesystem._windows import close_handle, open_directory_handle

    # The held handle refuses a rename of the directory, so a junction cannot
    # take its place while its children are removed by path.
    handle = open_directory_handle(path)
    try:
        for child in os.listdir(path):
            _remove_entry(Entry(path / child, None))
    finally:
        close_handle(handle)
    os.rmdir(path)


class FileTree:
    """Operate on files contained in one root directory.

    Paths are absolute and must stay under ``root``. A path that crosses a
    symlink or a Windows junction raises ``UnsafePathError``. The first verb
    that opens ``root`` binds the tree to that directory, and later verbs raise
    ``ConcurrentChangeError`` once ``root`` names a different directory.
    """

    def __init__(self, root: Path) -> None:
        if ".." in Path(root).parts:
            raise UnsafePathError(f"Root must not include parent segments: {root}")
        self.root = Path(os.path.abspath(root))
        self._identity: tuple[int, int] | None = None

    def _bind(self, state: os.stat_result) -> None:
        identity = (state.st_dev, state.st_ino)
        if self._identity is None:
            self._identity = identity
        elif identity != self._identity:
            raise ConcurrentChangeError(
                f"Root changed while it was in use: {self.root}"
            )

    def _open_root(self) -> int:
        descriptor = open_directory(self.root, path=self.root)
        try:
            self._bind(os.fstat(descriptor))
        except BaseException:
            os.close(descriptor)
            raise
        return descriptor

    def _target(self, path: Path, *, allow_root: bool = False) -> Path:
        if ".." in Path(path).parts:
            raise UnsafePathError(f"Path must not include parent segments: {path}")
        target = Path(os.path.abspath(path))
        try:
            relative = target.relative_to(self.root)
        except ValueError as error:
            raise UnsafePathError(f"Path is outside {self.root}: {target}") from error
        if not relative.parts and not allow_root:
            raise UnsafePathError(f"A path below {self.root} is required: {target}")
        return target

    @contextmanager
    def _locate(self, path: Path, *, allow_root: bool = False) -> Iterator[Entry]:
        """Yield ``path`` with the directory that holds it open.

        Raises ``FileNotFoundError`` when an ancestor is missing.
        """
        target = self._target(path, allow_root=allow_root)
        if target == self.root:
            state = _lstat(Entry(target, None))
            if state is not None and stat.S_ISDIR(state.st_mode) and not is_link(state):
                self._bind(state)
            yield Entry(target, None)
            return
        if not DESCRIPTORS:
            self._check_ancestors(target)
            yield Entry(target, None)
            return
        descriptor = self._open_root()
        try:
            current = self.root
            for component in target.relative_to(self.root).parts[:-1]:
                current /= component
                child = open_directory(component, parent=descriptor, path=current)
                os.close(descriptor)
                descriptor = child
            yield Entry(target, descriptor)
        finally:
            os.close(descriptor)

    def _check_ancestors(self, target: Path) -> None:
        ancestors = [self.root]
        for component in target.relative_to(self.root).parts[:-1]:
            ancestors.append(ancestors[-1] / component)
        for current in ancestors:
            try:
                state = os.lstat(current)
            except FileNotFoundError as error:
                raise FileNotFoundError(
                    errno.ENOENT, "Directory is unavailable", current
                ) from error
            if is_link(state):
                raise UnsafePathError(f"Path crosses a symlink: {current}")
            if not stat.S_ISDIR(state.st_mode):
                raise UnsafePathError(f"Path ancestor is not a directory: {current}")
            if current == self.root:
                self._bind(state)

    @contextmanager
    def _directory(self, path: Path) -> Iterator[int | Path]:
        """Yield one directory as an open descriptor, or as a path on Windows."""
        if DESCRIPTORS and self._target(path, allow_root=True) == self.root:
            descriptor = self._open_root()
            try:
                yield descriptor
            finally:
                os.close(descriptor)
            return
        with (
            self._locate(path, allow_root=True) as entry,
            _entry_directory(entry) as directory,
        ):
            yield directory

    # Reads

    def stat(self, path: Path) -> os.stat_result | None:
        """Return metadata for one entry without following symlinks, or ``None``."""
        try:
            with self._locate(path, allow_root=True) as entry:
                state = _lstat(entry)
        except FileNotFoundError:
            return None
        if state is not None and is_link(state):
            raise UnsafePathError(f"Path is a symlink: {path}")
        return state

    def is_file(self, path: Path) -> bool:
        """Return whether ``path`` is a regular file. A symlink raises an error."""
        state = self.stat(path)
        return state is not None and stat.S_ISREG(state.st_mode)

    def is_directory(self, path: Path) -> bool:
        """Return whether ``path`` is a directory. A symlink raises an error."""
        state = self.stat(path)
        return state is not None and stat.S_ISDIR(state.st_mode)

    def exists(self, path: Path) -> bool:
        """Return whether an entry, including a symlink, occupies ``path``."""
        try:
            with self._locate(path) as entry:
                return _lstat(entry) is not None
        except FileNotFoundError:
            return False

    def children(self, path: Path) -> tuple[Path, ...]:
        """List the direct entries of one directory."""
        target = self._target(path, allow_root=True)
        with self._directory(target) as directory:
            names = os.listdir(directory)
        return tuple(target / name for name in sorted(names))

    @contextmanager
    def reader(self, path: Path) -> Iterator[tuple[BinaryIO, os.stat_result]]:
        """Open one regular file and verify it stayed unchanged while it was used."""
        with self._locate(path) as entry, _entry_reader(entry) as opened:
            yield opened

    def read(
        self,
        path: Path,
        *,
        max_bytes: int = WORKSPACE_FILE_MAX_BYTES,
    ) -> Snapshot:
        """Read one complete regular file within ``max_bytes``.

        Raises ``FileNotFoundError`` for a missing file and ``FileAccessError``
        when the operating system refuses the read.
        """
        with _access("read", path), self.reader(path) as (stream, state):
            if state.st_size > max_bytes:
                raise FileTooLargeError(Path(path), state.st_size, max_bytes)
            content = stream.read(state.st_size)
            if len(content) != state.st_size or stream.read(1):
                raise ConcurrentChangeError(f"File changed while it was read: {path}")
        return Snapshot(
            content,
            stat.S_IMODE(state.st_mode),
            _file_version(state, hashlib.sha256(content).digest()),
        )

    def version(self, path: Path) -> Version | None:
        """Return the current version of one file or directory, or ``None``."""
        try:
            with self._locate(path, allow_root=True) as entry:
                return _entry_version(entry)
        except FileNotFoundError:
            return None

    def regular_files(
        self,
        path: Path,
        *,
        max_entries: int,
    ) -> tuple[tuple[Path, int], ...]:
        """List every regular file below one directory with its size."""
        target = self._target(path, allow_root=True)
        files: list[tuple[Path, int]] = []
        with self._directory(target) as directory:
            for entry, state in _visit(directory, target, [0], max_entries):
                if is_link(state):
                    raise UnsafePathError(f"Tree contains a symlink: {entry}")
                if stat.S_ISREG(state.st_mode):
                    files.append((entry, state.st_size))
                elif not stat.S_ISDIR(state.st_mode):
                    raise UnsafePathError(f"Tree contains a non-regular entry: {entry}")
        return tuple(files)

    def tree_version(self, path: Path, *, max_entries: int) -> TreeVersion | None:
        """Return the version of one directory tree, or ``None`` when absent."""
        try:
            with self._locate(path, allow_root=True) as entry:
                return _entry_tree_version(entry, max_entries)
        except FileNotFoundError:
            return None

    # Writes

    def _write_temporary(
        self,
        target: Entry,
        content: bytes,
        mode: int,
    ) -> tuple[Entry, Version]:
        temporary = target.sibling(temporary_name("write"))
        descriptor = os.open(
            temporary.name, _CREATE_FLAGS, _NEW_FILE_MODE, dir_fd=temporary.parent
        )
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(content)
                stream.flush()
                if hasattr(os, "fchmod"):
                    os.fchmod(stream.fileno(), mode)
                else:
                    os.chmod(temporary.path, mode)
                os.fsync(stream.fileno())
                state = os.fstat(stream.fileno())
        except BaseException:
            with suppress(OSError):
                os.unlink(temporary.name, dir_fd=temporary.parent)
            raise
        return temporary, _file_version(state, hashlib.sha256(content).digest())

    def write(
        self,
        path: Path,
        content: bytes,
        *,
        expect: Expectation = None,
        mode: int | None = None,
    ) -> Version:
        """Replace one file with complete content and return its new version.

        ``expect=None`` replaces unconditionally. ``ABSENT`` creates the file
        only when it does not exist. A ``Version`` replaces the file only when
        its current version still matches. A failed precondition raises
        ``ConditionalWriteError`` and leaves the current file in place. New
        files default to mode ``0o600``. Replacements keep the current mode
        unless ``mode`` is given. The operating system refusing the write
        raises ``FileAccessError``.
        """
        with _access("write", path), self._locate(path) as target:
            current = _lstat(target)
            if current is not None and is_link(current):
                raise UnsafePathError(f"Path is a symlink: {target.path}")
            if current is not None and not stat.S_ISREG(current.st_mode):
                raise UnsafePathError(
                    f"Write target is not a regular file: {target.path}"
                )
            selected_mode = (
                mode
                if mode is not None
                else stat.S_IMODE(current.st_mode)
                if current is not None
                else _NEW_FILE_MODE
            )
            temporary, version = self._write_temporary(target, content, selected_mode)
            try:
                if expect is None:
                    _replace(temporary, target)
                elif isinstance(expect, _Absent):
                    try:
                        publish_entry(temporary, target)
                    except FileExistsError as error:
                        raise ConditionalWriteError(
                            f"File was created before the write: {target.path}"
                        ) from error
                else:
                    self._swap(temporary, target, expect, version)
            finally:
                # A leftover temporary name never fails a committed write, and
                # discovery skips it.
                with suppress(OSError):
                    os.unlink(temporary.name, dir_fd=temporary.parent)
            _sync(target)
        return version

    def _swap(
        self,
        temporary: Entry,
        target: Entry,
        expect: Version,
        version: Version,
    ) -> None:
        displaced = self._move_aside_matching(target, expect, "write")
        try:
            publish_entry(temporary, target)
        except FileExistsError as error:
            raise ConditionalWriteError(
                f"File was created during the write: {target.path}",
                recovery=displaced.path,
            ) from error
        except BaseException:
            self._restore(displaced, target)
            raise
        try:
            _remove_entry(displaced)
        except OSError as error:
            raise ConditionalWriteError(
                f"The previous content is preserved after the write: {target.path}",
                recovery=displaced.path,
                committed=version,
            ) from error

    def _move_aside_matching(
        self,
        target: Entry,
        expect: Version | TreeVersion,
        action: str,
    ) -> Entry:
        """Move ``target`` to a sibling name and return it while it matches.

        A mismatch, or any failure while comparing, moves the entry back.
        """
        try:
            displaced = move_aside(target, "aside")
        except FileNotFoundError as error:
            raise ConditionalWriteError(
                f"Entry was removed before the {action}: {target.path}"
            ) from error
        try:
            matches = _displaced_version(displaced, expect) == expect
        except BaseException:
            self._restore(displaced, target)
            raise
        if not matches:
            self._restore(displaced, target)
            raise ConditionalWriteError(
                f"Entry changed before the {action}: {target.path}"
            )
        return displaced

    def _restore(self, displaced: Entry, target: Entry) -> None:
        try:
            publish_entry(displaced, target)
        except OSError as error:
            raise ConditionalWriteError(
                f"Displaced content is preserved beside {target.path}",
                recovery=displaced.path,
            ) from error

    @contextmanager
    def create(self, path: Path) -> Iterator[BinaryIO]:
        """Create one new private file and yield it for streaming writes.

        Raises ``FileExistsError`` when an entry occupies ``path``. The file
        skips ``fsync``, so use it for scratch copies that a crash may discard.
        A failure inside the block removes the partial file.
        """
        with self._locate(path) as entry:
            descriptor = os.open(
                entry.name, _CREATE_FLAGS, _NEW_FILE_MODE, dir_fd=entry.parent
            )
            try:
                with os.fdopen(descriptor, "wb") as stream:
                    yield stream
            except BaseException:
                with suppress(OSError):
                    os.unlink(entry.name, dir_fd=entry.parent)
                raise

    def replace(self, source: Path, destination: Path) -> None:
        """Atomically replace ``destination`` with ``source``."""
        with self._locate(source) as moved, self._locate(destination) as target:
            _replace(moved, target)
            _sync(target)
            if moved.path.parent != target.path.parent:
                _sync(moved)

    def publish(self, source: Path, destination: Path) -> None:
        """Rename ``source`` to ``destination`` while the destination stays absent.

        Raises ``FileExistsError`` when the destination exists.
        """
        with self._locate(source) as moved, self._locate(destination) as target:
            if _lstat(moved) is None:
                raise FileNotFoundError(errno.ENOENT, "Entry is unavailable", source)
            publish_entry(moved, target)
            _sync(target)
            if moved.path.parent != target.path.parent:
                _sync(moved)

    def create_directory(self, path: Path) -> Version:
        """Create one empty private directory and return its version.

        Raises ``FileExistsError`` when an entry occupies ``path``.
        """
        with self._locate(path) as entry:
            os.mkdir(entry.name, _NEW_DIRECTORY_MODE, dir_fd=entry.parent)
            _sync(entry)
            state = _lstat(entry)
        if state is None or not stat.S_ISDIR(state.st_mode):
            raise ConcurrentChangeError(
                f"Directory was replaced after it was created: {path}"
            )
        return _directory_version(state, [])

    def ensure_directory(self, path: Path) -> tuple[Path, ...]:
        """Create every missing directory through ``path`` and return the new ones."""
        target = self._target(path, allow_root=True)
        if not DESCRIPTORS:
            return self._create_windows_through(target)
        created: list[Path] = []
        descriptor = self._open_root()
        try:
            current = self.root
            for component in target.relative_to(self.root).parts:
                current /= component
                try:
                    os.mkdir(component, dir_fd=descriptor)
                except FileExistsError:
                    pass
                else:
                    created.append(current)
                    with suppress(OSError):
                        os.fsync(descriptor)
                child = open_directory(component, parent=descriptor, path=current)
                os.close(descriptor)
                descriptor = child
        finally:
            os.close(descriptor)
        return tuple(created)

    def _create_windows_through(self, target: Path) -> tuple[Path, ...]:
        created: list[Path] = []
        current = self.root
        for component in target.relative_to(self.root).parts:
            current /= component
            state = self.stat(current)
            if state is None:
                with suppress(FileExistsError):
                    os.mkdir(current)
                    created.append(current)
                state = self.stat(current)
            if state is None or not stat.S_ISDIR(state.st_mode):
                raise UnsafePathError(f"Path is not a directory: {current}")
        return tuple(created)

    def remove(
        self, path: Path, *, expect: Version | TreeVersion | None = None
    ) -> None:
        """Remove one file or directory tree without following symlinks.

        A missing entry is already removed. With ``expect``, the entry moves
        aside first and is deleted only when its version still matches. A
        mismatch restores it and raises ``ConditionalWriteError``.
        """
        with ExitStack() as stack:
            try:
                target = stack.enter_context(self._locate(path))
            except FileNotFoundError:
                if expect is None:
                    return
                raise ConditionalWriteError(
                    f"Entry was removed before the removal: {path}"
                ) from None
            if expect is None:
                _remove_entry(target)
            else:
                _remove_entry(self._move_aside_matching(target, expect, "removal"))
            _sync(target)

    def remove_empty_directory(self, path: Path) -> bool:
        """Remove one directory only while it has no entries.

        Returns ``False`` when the directory is absent or still has entries.
        """
        try:
            with self._locate(path) as entry:
                os.rmdir(entry.name, dir_fd=entry.parent)
                _sync(entry)
        except FileNotFoundError:
            return False
        except OSError as error:
            if error.errno not in {errno.ENOTEMPTY, errno.EEXIST}:
                raise
            return False
        return True

    @contextmanager
    def temporary_directory(self, parent: Path) -> Iterator[Path]:
        """Create a fresh staging directory in ``parent`` and remove it on exit."""
        staging = self._target(parent, allow_root=True) / temporary_name("stage")
        self.create_directory(staging)
        try:
            yield staging
        finally:
            with suppress(OSError):
                self.remove(staging)

    def ingest(
        self,
        source: Path,
        destination: Path,
        *,
        budget: FileBudget,
        label: str,
    ) -> tuple[IngestedFile, ...]:
        """Copy every regular file below an untrusted ``source`` into ``destination``.

        ``destination`` must be absent. Raises ``UnsafePathError`` for
        symlinks and special files, ``ConcurrentChangeError`` when a file
        changes while it is copied, and ``ConfigurationError`` when the tree
        exceeds ``budget``.
        """
        self.create_directory(destination)
        with (
            self._directory(source) as source_handle,
            self._directory(destination) as destination_handle,
        ):
            return copy_tree(
                source_handle, destination_handle, budget=budget, label=label
            )

    @contextmanager
    def lock(
        self,
        path: Path,
        *,
        blocking: bool = True,
        create: bool = True,
        require_held: bool = False,
    ) -> Iterator[bool]:
        """Hold an exclusive cross-process lock on one persistent lock file.

        Yields ``False`` when ``blocking`` is false and another owner holds
        the lock, or when ``create`` is false and the lock file is absent. The
        lock file stays in place so every owner locks the same inode. Raises
        ``ConcurrentChangeError`` when the lock file was replaced before the
        lock was acquired, and with ``require_held`` also when it was removed
        or replaced while the block ran.
        """
        target = self._target(path)
        if create:
            self.ensure_directory(target.parent)
        descriptor: int | None
        try:
            with self._locate(target) as entry:
                descriptor = _locks.open_lock_file(entry, create=create)
        except FileNotFoundError:
            if create:
                raise
            descriptor = None
        except OSError as error:
            if error.errno == errno.ELOOP:
                raise UnsafePathError(f"Lock file is a symlink: {target}") from error
            raise
        if descriptor is None:
            yield False
            return
        try:
            opened = os.fstat(descriptor)
            if not stat.S_ISREG(opened.st_mode):
                raise UnsafePathError(f"Lock file is not a regular file: {target}")
            if not _locks.acquire(descriptor, blocking=blocking):
                yield False
                return
            try:
                self._require_lock_inode(
                    target, opened, "Lock file was replaced before it was acquired"
                )
                yield True
                if require_held:
                    self._require_lock_inode(
                        target, opened, "Lock file changed while held"
                    )
            finally:
                _locks.release(descriptor)
        finally:
            os.close(descriptor)

    def _require_lock_inode(
        self, target: Path, opened: os.stat_result, message: str
    ) -> None:
        # A lock taken on an unlinked or replaced inode excludes nobody.
        try:
            current = self.stat(target)
        except OSError as error:
            raise ConcurrentChangeError(f"{message}: {target}") from error
        if current is None or not os.path.samestat(current, opened):
            raise ConcurrentChangeError(f"{message}: {target}")
