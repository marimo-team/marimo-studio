"""Perform low-level file operations through stable parent handles."""

from __future__ import annotations

import errno
import hashlib
import os
import secrets
import stat
import time
from contextlib import suppress
from pathlib import Path

from marimo_studio._filesystem._secure_types import (
    FileIdentity,
    ParentHandle,
    SecureFileError,
)
from marimo_studio._filesystem._secure_windows import (
    close_handle as close_windows_handle,
)
from marimo_studio._filesystem._secure_windows import (
    open_directory_handle as open_windows_directory,
)
from marimo_studio._filesystem._secure_windows import open_file as open_windows_file

_WINDOWS_REPLACE_ATTEMPTS = 100
_WINDOWS_REPLACE_INTERVAL_SECONDS = 0.01


def _replace(
    source: str | Path,
    target: str | Path,
    *,
    parent: ParentHandle,
) -> None:
    attempts = _WINDOWS_REPLACE_ATTEMPTS if os.name == "nt" else 1
    for attempt in range(attempts):
        try:
            os.replace(
                source,
                target,
                src_dir_fd=parent.descriptor,
                dst_dir_fd=parent.descriptor,
            )
            return
        except PermissionError:
            if attempt + 1 == attempts:
                raise
            time.sleep(_WINDOWS_REPLACE_INTERVAL_SECONDS)


def directory_flags() -> int:
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    return flags


def file_digest(descriptor: int, size: int) -> bytes:
    os.lseek(descriptor, 0, os.SEEK_SET)
    digest = hashlib.sha256()
    remaining = size
    while remaining:
        chunk = os.read(descriptor, min(1024 * 1024, remaining))
        if not chunk:
            raise SecureFileError("File changed while its identity was captured")
        digest.update(chunk)
        remaining -= len(chunk)
    if os.read(descriptor, 1):
        raise SecureFileError("File changed while its identity was captured")
    return digest.digest()


def regular_identity(descriptor: int) -> FileIdentity:
    before = os.fstat(descriptor)
    if not stat.S_ISREG(before.st_mode):
        raise SecureFileError("A regular file identity was required")
    digest = file_digest(descriptor, before.st_size)
    after = os.fstat(descriptor)
    if (
        before.st_dev != after.st_dev
        or before.st_ino != after.st_ino
        or before.st_mode != after.st_mode
        or before.st_size != after.st_size
        or before.st_mtime_ns != after.st_mtime_ns
        or before.st_ctime_ns != after.st_ctime_ns
    ):
        raise SecureFileError("File changed while its identity was captured")
    return FileIdentity(
        before.st_dev,
        before.st_ino,
        before.st_mode,
        before.st_size,
        digest,
        False,
    )


def open_file_at(parent: ParentHandle, path: Path, flags: int) -> int:
    if os.name == "nt":
        return open_windows_file(path, flags)
    selected_flags = flags
    if hasattr(os, "O_NOFOLLOW"):
        selected_flags |= os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        selected_flags |= os.O_CLOEXEC
    target: str | Path = path.name if parent.descriptor is not None else path
    descriptor = os.open(target, selected_flags, dir_fd=parent.descriptor)
    state = os.fstat(descriptor)
    if not stat.S_ISREG(state.st_mode):
        os.close(descriptor)
        raise SecureFileError(f"Contained path is not a regular file: {path}")
    return descriptor


def create_file_at(parent: ParentHandle, path: Path, mode: int) -> int:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    target: str | Path = path.name if parent.descriptor is not None else path
    descriptor = os.open(target, flags, mode, dir_fd=parent.descriptor)
    state = os.fstat(descriptor)
    if not stat.S_ISREG(state.st_mode):
        os.close(descriptor)
        raise SecureFileError(f"Contained path is not a regular file: {path}")
    return descriptor


def open_or_create_file_at(parent: ParentHandle, path: Path, mode: int) -> int:
    flags = os.O_RDWR | getattr(os, "O_BINARY", 0)
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    target: str | Path = path.name if parent.descriptor is not None else path
    try:
        descriptor = os.open(target, flags, dir_fd=parent.descriptor)
    except FileNotFoundError:
        try:
            descriptor = os.open(
                target,
                flags | os.O_CREAT | os.O_EXCL,
                mode,
                dir_fd=parent.descriptor,
            )
        except FileExistsError:
            descriptor = os.open(target, flags, dir_fd=parent.descriptor)
    try:
        descriptor_state = os.fstat(descriptor)
        path_state = os.stat(
            target,
            dir_fd=parent.descriptor,
            follow_symlinks=False,
        )
        if (
            not stat.S_ISREG(descriptor_state.st_mode)
            or stat.S_ISLNK(path_state.st_mode)
            or not os.path.samestat(path_state, descriptor_state)
        ):
            raise SecureFileError(
                f"Contained path is not a stable regular file: {path}"
            )
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def remove_tree_at(parent: ParentHandle, path: Path) -> None:
    target: str | Path = path.name if parent.descriptor is not None else path
    try:
        state = os.stat(
            target,
            dir_fd=parent.descriptor,
            follow_symlinks=False,
        )
    except FileNotFoundError:
        return
    if stat.S_ISLNK(state.st_mode) or not stat.S_ISDIR(state.st_mode):
        os.unlink(target, dir_fd=parent.descriptor)
        return
    if parent.descriptor is not None:
        descriptor = os.open(target, directory_flags(), dir_fd=parent.descriptor)
        child_parent = ParentHandle(path, descriptor)
        try:
            for name in os.listdir(descriptor):
                remove_tree_at(child_parent, path / name)
        finally:
            os.close(descriptor)
        os.rmdir(target, dir_fd=parent.descriptor)
        return
    handle = open_windows_directory(path) if os.name == "nt" else None
    try:
        names = os.listdir(path)
        for name in names:
            remove_tree_at(ParentHandle(path, None), path / name)
    finally:
        if handle is not None:
            close_windows_handle(handle)
    os.rmdir(path)


def _target_mode(parent: ParentHandle, path: Path, mode: int | None) -> int | None:
    try:
        state = os.stat(
            path.name if parent.descriptor is not None else path,
            dir_fd=parent.descriptor,
            follow_symlinks=False,
        )
    except FileNotFoundError:
        return mode
    if not stat.S_ISREG(state.st_mode):
        raise SecureFileError(f"Contained write target is not a regular file: {path}")
    return mode if mode is not None else stat.S_IMODE(state.st_mode)


def copy_file_if_absent_at(
    parent: ParentHandle,
    source: str | Path,
    target: str | Path,
    mode: int,
) -> None:
    read_flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
    write_flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
    if hasattr(os, "O_NOFOLLOW"):
        read_flags |= os.O_NOFOLLOW
        write_flags |= os.O_NOFOLLOW
    source_descriptor = os.open(source, read_flags, dir_fd=parent.descriptor)
    try:
        target_descriptor = os.open(
            target,
            write_flags,
            mode,
            dir_fd=parent.descriptor,
        )
        with (
            os.fdopen(source_descriptor, "rb") as source_stream,
            os.fdopen(target_descriptor, "wb") as target_stream,
        ):
            source_descriptor = -1
            while chunk := source_stream.read(1024 * 1024):
                target_stream.write(chunk)
            target_stream.flush()
            if hasattr(os, "fchmod"):
                os.fchmod(target_stream.fileno(), mode)
            elif isinstance(target, Path):
                os.chmod(target, mode)
            os.fsync(target_stream.fileno())
    finally:
        if source_descriptor >= 0:
            os.close(source_descriptor)


def write_file_if_absent_at(
    parent: ParentHandle,
    path: Path,
    content: bytes,
    mode: int,
) -> FileIdentity:
    temporary_name = f".{path.name}.restore-{secrets.token_hex(8)}"
    temporary: str | Path = (
        temporary_name
        if parent.descriptor is not None
        else parent.path / temporary_name
    )
    target: str | Path = path.name if parent.descriptor is not None else path
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(temporary, flags, 0o600, dir_fd=parent.descriptor)
    temporary_exists = True
    try:
        with os.fdopen(descriptor, "wb") as stream:
            descriptor = -1
            stream.write(content)
            stream.flush()
            if hasattr(os, "fchmod"):
                os.fchmod(stream.fileno(), mode)
            else:
                os.chmod(parent.path / temporary_name, mode)
            os.fsync(stream.fileno())
            state = os.fstat(stream.fileno())
            identity = FileIdentity(
                state.st_dev,
                state.st_ino,
                state.st_mode,
                state.st_size,
                hashlib.sha256(content).digest(),
                False,
            )
        try:
            os.link(
                temporary,
                target,
                src_dir_fd=parent.descriptor,
                dst_dir_fd=parent.descriptor,
                follow_symlinks=False,
            )
        except OSError as error:
            unsupported = {
                errno.EPERM,
                errno.EXDEV,
                getattr(errno, "ENOTSUP", errno.EPERM),
                getattr(errno, "EOPNOTSUPP", errno.EPERM),
            }
            if error.errno in unsupported:
                try:
                    identity = _write_direct_if_absent_at(
                        parent,
                        path,
                        content,
                        mode,
                    )
                except Exception as fallback_error:
                    temporary_exists = False
                    raise SecureFileError(
                        "Rollback snapshot was preserved at "
                        f"{path.with_name(temporary_name)}"
                    ) from fallback_error
            else:
                temporary_exists = False
                raise SecureFileError(
                    "Rollback snapshot was preserved at "
                    f"{path.with_name(temporary_name)}"
                ) from error
        os.unlink(temporary, dir_fd=parent.descriptor)
        temporary_exists = False
        if parent.descriptor is not None:
            with suppress(OSError):
                os.fsync(parent.descriptor)
        return identity
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if temporary_exists:
            with suppress(FileNotFoundError):
                os.unlink(temporary, dir_fd=parent.descriptor)


def _write_direct_if_absent_at(
    parent: ParentHandle,
    path: Path,
    content: bytes,
    mode: int,
) -> FileIdentity:
    target: str | Path = path.name if parent.descriptor is not None else path
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(target, flags, mode, dir_fd=parent.descriptor)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(content)
        stream.flush()
        if hasattr(os, "fchmod"):
            os.fchmod(stream.fileno(), mode)
        else:
            os.chmod(parent.path / path.name, mode)
        os.fsync(stream.fileno())
        state = os.fstat(stream.fileno())
    return FileIdentity(
        state.st_dev,
        state.st_ino,
        state.st_mode,
        state.st_size,
        hashlib.sha256(content).digest(),
        False,
    )


def atomic_write_at(
    parent: ParentHandle,
    path: Path,
    content: bytes,
    *,
    mode: int | None = None,
) -> FileIdentity:
    selected_mode = _target_mode(parent, path, mode)
    temporary_name = ""
    descriptor: int | None = None
    temporary_exists = False
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    for _attempt in range(128):
        temporary_name = f".{path.name}.{secrets.token_hex(8)}.tmp"
        target: str | Path = (
            temporary_name
            if parent.descriptor is not None
            else parent.path / temporary_name
        )
        try:
            descriptor = os.open(target, flags, 0o600, dir_fd=parent.descriptor)
            temporary_exists = True
            break
        except FileExistsError:
            continue
    if descriptor is None:
        raise SecureFileError(f"Could not allocate a temporary sibling for {path}")
    identity: FileIdentity | None = None
    try:
        with os.fdopen(descriptor, "wb") as stream:
            descriptor = None
            stream.write(content)
            stream.flush()
            if selected_mode is not None:
                if hasattr(os, "fchmod"):
                    os.fchmod(stream.fileno(), selected_mode)
                else:
                    os.chmod(parent.path / temporary_name, selected_mode)
            os.fsync(stream.fileno())
            state = os.fstat(stream.fileno())
            identity = FileIdentity(
                state.st_dev,
                state.st_ino,
                state.st_mode,
                state.st_size,
                hashlib.sha256(content).digest(),
                False,
            )
        if parent.descriptor is not None:
            os.rename(
                temporary_name,
                path.name,
                src_dir_fd=parent.descriptor,
                dst_dir_fd=parent.descriptor,
            )
            with suppress(OSError):
                os.fsync(parent.descriptor)
        else:
            _replace(parent.path / temporary_name, path, parent=parent)
        temporary_exists = False
        if identity is None:
            raise SecureFileError(f"Atomic write identity is unavailable: {path}")
        return identity
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if temporary_exists:
            with suppress(FileNotFoundError):
                os.unlink(
                    temporary_name
                    if parent.descriptor is not None
                    else parent.path / temporary_name,
                    dir_fd=parent.descriptor,
                )
