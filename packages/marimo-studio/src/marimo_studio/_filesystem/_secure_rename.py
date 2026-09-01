"""Publish directories without replacing concurrently created paths."""

from __future__ import annotations

import ctypes
import errno
import os
import sys
from pathlib import Path

from marimo_studio._filesystem._secure_names import (
    TemporarySiblingKind,
    temporary_sibling_name,
)
from marimo_studio._filesystem._secure_types import ParentHandle, SecureFileError

_TEMPORARY_RENAME_ATTEMPTS = 128


def _raise_rename_error(source: Path, destination: Path) -> None:
    code = ctypes.get_errno()
    if code in {errno.EEXIST, errno.ENOTEMPTY}:
        raise FileExistsError(code, os.strerror(code), destination)
    raise OSError(code, os.strerror(code), source, destination)


def _rename_macos(
    source_parent: ParentHandle,
    source: Path,
    destination_parent: ParentHandle,
    destination: Path,
) -> None:
    if source_parent.descriptor is None or destination_parent.descriptor is None:
        raise SecureFileError("Exclusive directory rename requires parent descriptors")
    rename = ctypes.CDLL(None, use_errno=True).renameatx_np
    rename.argtypes = (
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    )
    rename.restype = ctypes.c_int
    rename_exclusive = 0x00000004
    if (
        rename(
            source_parent.descriptor,
            os.fsencode(source.name),
            destination_parent.descriptor,
            os.fsencode(destination.name),
            rename_exclusive,
        )
        != 0
    ):
        _raise_rename_error(source, destination)


def _rename_linux(
    source_parent: ParentHandle,
    source: Path,
    destination_parent: ParentHandle,
    destination: Path,
) -> None:
    if source_parent.descriptor is None or destination_parent.descriptor is None:
        raise SecureFileError("Exclusive directory rename requires parent descriptors")
    library = ctypes.CDLL(None, use_errno=True)
    try:
        rename = library.renameat2
    except AttributeError as error:
        raise SecureFileError(
            "This platform does not provide exclusive directory publication"
        ) from error
    rename.argtypes = (
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    )
    rename.restype = ctypes.c_int
    rename_no_replace = 1
    if (
        rename(
            source_parent.descriptor,
            os.fsencode(source.name),
            destination_parent.descriptor,
            os.fsencode(destination.name),
            rename_no_replace,
        )
        != 0
    ):
        _raise_rename_error(source, destination)


def rename_if_absent(
    source_parent: ParentHandle,
    source: Path,
    destination_parent: ParentHandle,
    destination: Path,
) -> None:
    """Atomically rename a filesystem entry when the destination remains absent."""
    if os.name == "nt":
        os.rename(source, destination)
        return
    if sys.platform == "darwin":
        _rename_macos(source_parent, source, destination_parent, destination)
        return
    if sys.platform.startswith("linux"):
        _rename_linux(source_parent, source, destination_parent, destination)
        return
    raise SecureFileError(
        "This platform does not provide exclusive directory publication"
    )


def rename_to_temporary_sibling(
    parent: ParentHandle,
    source: Path,
    kind: TemporarySiblingKind,
) -> Path:
    """Move one entry to a fresh bounded sibling without replacing a collision."""
    for _attempt in range(_TEMPORARY_RENAME_ATTEMPTS):
        destination = source.with_name(temporary_sibling_name(kind))
        try:
            rename_if_absent(parent, source, parent, destination)
        except FileExistsError:
            continue
        return destination
    raise SecureFileError(f"Could not allocate a temporary sibling for {source}")
