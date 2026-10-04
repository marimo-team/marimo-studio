"""Open and rename Windows files and directories without following links."""

from __future__ import annotations

import os
import stat
from pathlib import Path
from typing import Any, cast

from marimo_studio._filesystem._entry import NAME_SURROGATE
from marimo_studio._filesystem.errors import UnsafePathError

_GENERIC_READ = 0x80000000
_GENERIC_WRITE = 0x40000000
_DELETE = 0x00010000
_FILE_LIST_DIRECTORY = 0x00000001
_FILE_READ_ATTRIBUTES = 0x00000080
_FILE_SHARE_READ_WRITE = 0x00000001 | 0x00000002
_FILE_SHARE_ALL = _FILE_SHARE_READ_WRITE | 0x00000004
_CREATE_NEW = 1
_OPEN_EXISTING = 3
_FILE_ATTRIBUTE_REPARSE_POINT = 0x00000400
_FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
_FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000
_FILE_RENAME_INFO = 3
_FILE_ATTRIBUTE_TAG_INFO = 9


def _kernel32() -> Any:
    import ctypes

    return cast(Any, ctypes).WinDLL("kernel32", use_last_error=True)


def _open_handle(
    path: Path,
    access: int,
    flags: int,
    label: str,
    *,
    share: int,
    disposition: int = _OPEN_EXISTING,
) -> int:
    import ctypes
    from ctypes import wintypes

    kernel32 = _kernel32()
    create_file = kernel32.CreateFileW
    create_file.argtypes = (
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    )
    create_file.restype = wintypes.HANDLE
    handle = create_file(
        str(path),
        access,
        share,
        None,
        disposition,
        flags | _FILE_FLAG_OPEN_REPARSE_POINT,
        None,
    )
    if handle == ctypes.c_void_p(-1).value:
        # The Windows error code selects the OSError subclass, so a missing
        # path raises FileNotFoundError and a sharing violation raises
        # PermissionError.
        error = cast(Any, ctypes).get_last_error()
        raise OSError(0, f"Could not open {label.lower()}", str(path), error)

    # GetFileInformationByHandle reports attributes on every local and
    # network filesystem, including exFAT and FAT32.
    class ByHandleFileInformation(ctypes.Structure):
        _fields_ = [
            ("file_attributes", wintypes.DWORD),
            ("creation_time", wintypes.FILETIME),
            ("last_access_time", wintypes.FILETIME),
            ("last_write_time", wintypes.FILETIME),
            ("volume_serial_number", wintypes.DWORD),
            ("file_size_high", wintypes.DWORD),
            ("file_size_low", wintypes.DWORD),
            ("number_of_links", wintypes.DWORD),
            ("file_index_high", wintypes.DWORD),
            ("file_index_low", wintypes.DWORD),
        ]

    information = ByHandleFileInformation()
    get_information = kernel32.GetFileInformationByHandle
    get_information.argtypes = (wintypes.HANDLE, wintypes.LPVOID)
    get_information.restype = wintypes.BOOL
    if not get_information(handle, ctypes.byref(information)):
        error = cast(Any, ctypes).get_last_error()
        close_handle(handle)
        raise UnsafePathError(error, f"Could not inspect {label.lower()}: {path}")
    if information.file_attributes & _FILE_ATTRIBUTE_REPARSE_POINT and (
        _reparse_tag(kernel32, handle) & NAME_SURROGATE
    ):
        close_handle(handle)
        raise UnsafePathError(f"{label} is a symlink or junction: {path}")
    return int(handle)


def _reparse_tag(kernel32: Any, handle: int) -> int:
    # Only filesystems with reparse points answer this query. A failed query
    # reports a name surrogate, so the entry is refused.
    import ctypes
    from ctypes import wintypes

    class AttributeTagInformation(ctypes.Structure):
        _fields_ = [
            ("file_attributes", wintypes.DWORD),
            ("reparse_tag", wintypes.DWORD),
        ]

    information = AttributeTagInformation()
    get_information = kernel32.GetFileInformationByHandleEx
    get_information.argtypes = (
        wintypes.HANDLE,
        ctypes.c_int,
        wintypes.LPVOID,
        wintypes.DWORD,
    )
    get_information.restype = wintypes.BOOL
    if not get_information(
        handle,
        _FILE_ATTRIBUTE_TAG_INFO,
        ctypes.byref(information),
        ctypes.sizeof(information),
    ):
        return NAME_SURROGATE
    return int(information.reparse_tag)


def open_directory_handle(path: Path) -> int:
    """Hold one directory open so it cannot be replaced while it is listed.

    The handle lists the directory and withholds delete sharing, so a rename
    or removal of the directory fails while the handle is open. A handle
    without data access takes no part in sharing checks.
    """
    return _open_handle(
        path,
        _FILE_LIST_DIRECTORY | _FILE_READ_ATTRIBUTES,
        _FILE_FLAG_BACKUP_SEMANTICS,
        "Directory",
        share=_FILE_SHARE_READ_WRITE,
    )


def rename_exclusive(source: Path, destination: Path) -> None:
    """Rename one file or directory while no other handle can rename it.

    ``MoveFileExW`` opens its source by path and then renames whichever entry
    that handle opened, so concurrent renames of one path can all succeed and
    pass the entry between their destinations. This handle withholds delete
    sharing, so a competing rename of the same entry fails with a sharing
    violation until this one completes. Raises ``FileExistsError`` when the
    destination exists.
    """
    import ctypes
    from ctypes import wintypes

    name = str(destination)
    # FILE_RENAME_INFO measures its trailing name in UTF-16 bytes.
    encoded = name.encode("utf-16-le")

    class RenameInformation(ctypes.Structure):
        _fields_ = [
            ("flags", wintypes.DWORD),
            ("root_directory", wintypes.HANDLE),
            ("file_name_length", wintypes.DWORD),
            ("file_name", ctypes.c_ubyte * (len(encoded) + 2)),
        ]

    information = RenameInformation(0, None, len(encoded))
    ctypes.memmove(information.file_name, encoded, len(encoded))
    handle = _open_handle(
        source,
        _DELETE | _FILE_READ_ATTRIBUTES,
        _FILE_FLAG_BACKUP_SEMANTICS,
        "Entry",
        share=_FILE_SHARE_READ_WRITE,
    )
    try:
        set_information = _kernel32().SetFileInformationByHandle
        set_information.argtypes = (
            wintypes.HANDLE,
            ctypes.c_int,
            wintypes.LPVOID,
            wintypes.DWORD,
        )
        set_information.restype = wintypes.BOOL
        if not set_information(
            handle,
            _FILE_RENAME_INFO,
            ctypes.byref(information),
            ctypes.sizeof(information),
        ):
            error = cast(Any, ctypes).get_last_error()
            raise OSError(0, "Could not rename entry", str(source), error, name)
    finally:
        close_handle(handle)


def close_handle(handle: int) -> None:
    from ctypes import wintypes

    kernel32 = _kernel32()
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel32.CloseHandle(handle)


def open_file(path: Path, flags: int, *, create: bool = False) -> int:
    """Open one regular file as a descriptor without following a link.

    The handle shares read, write, and delete access, so other processes can
    rename or remove the file while it is open, as POSIX allows. ``create``
    creates the file and raises ``FileExistsError`` when it already exists.
    """
    import msvcrt

    if flags & os.O_RDWR:
        access = _GENERIC_READ | _GENERIC_WRITE
    elif flags & os.O_WRONLY:
        access = _GENERIC_WRITE
    else:
        access = _GENERIC_READ
    disposition = _CREATE_NEW if create else _OPEN_EXISTING
    handle = _open_handle(
        path, access, 0, "File", share=_FILE_SHARE_ALL, disposition=disposition
    )
    try:
        descriptor = cast(Any, msvcrt).open_osfhandle(
            handle,
            flags | getattr(os, "O_BINARY", 0),
        )
    except Exception:
        close_handle(handle)
        raise
    try:
        state = os.fstat(descriptor)
    except Exception:
        os.close(descriptor)
        raise
    if not stat.S_ISREG(state.st_mode):
        os.close(descriptor)
        raise UnsafePathError(f"Path is not a regular file: {path}")
    return descriptor
