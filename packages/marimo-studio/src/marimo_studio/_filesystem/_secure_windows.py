"""Hold Windows filesystem objects without traversing reparse points."""

from __future__ import annotations

import os
import stat
from pathlib import Path
from typing import Any, cast

from marimo_studio._filesystem._secure_types import SecureFileError


def open_directory_handle(path: Path) -> int:
    import ctypes
    from ctypes import wintypes

    file_share_read = 0x00000001
    file_share_write = 0x00000002
    open_existing = 3
    file_attribute_reparse_point = 0x00000400
    file_flag_backup_semantics = 0x02000000
    file_flag_open_reparse_point = 0x00200000
    file_attribute_tag_info = 9
    invalid_handle = ctypes.c_void_p(-1).value

    class FileAttributeTagInfo(ctypes.Structure):
        _fields_ = [
            ("file_attributes", wintypes.DWORD),
            ("reparse_tag", wintypes.DWORD),
        ]

    windows = cast(Any, ctypes)
    kernel32 = windows.WinDLL("kernel32", use_last_error=True)
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
        0,
        file_share_read | file_share_write,
        None,
        open_existing,
        file_flag_backup_semantics | file_flag_open_reparse_point,
        None,
    )
    if handle == invalid_handle:
        error = windows.get_last_error()
        if error in {2, 3}:
            raise FileNotFoundError(error, f"Directory is unavailable: {path}")
        raise SecureFileError(error, f"Could not lock directory: {path}")
    information = FileAttributeTagInfo()
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
        file_attribute_tag_info,
        ctypes.byref(information),
        ctypes.sizeof(information),
    ):
        error = windows.get_last_error()
        kernel32.CloseHandle(handle)
        raise SecureFileError(error, f"Could not inspect directory: {path}")
    if information.file_attributes & file_attribute_reparse_point:
        kernel32.CloseHandle(handle)
        raise SecureFileError(f"Contained path ancestor is a reparse point: {path}")
    return int(handle)


def close_handle(handle: int) -> None:
    import ctypes
    from ctypes import wintypes

    kernel32 = cast(Any, ctypes).WinDLL("kernel32", use_last_error=True)
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel32.CloseHandle(handle)


def open_file(path: Path, flags: int) -> int:
    import ctypes
    import msvcrt
    from ctypes import wintypes

    generic_read = 0x80000000
    generic_write = 0x40000000
    if flags & os.O_RDWR:
        desired_access = generic_read | generic_write
    elif flags & os.O_WRONLY:
        desired_access = generic_write
    else:
        desired_access = generic_read
    file_share_read = 0x00000001
    file_share_write = 0x00000002
    file_share_delete = 0x00000004
    open_existing = 3
    file_attribute_reparse_point = 0x00000400
    file_flag_open_reparse_point = 0x00200000
    file_attribute_tag_info = 9
    invalid_handle = ctypes.c_void_p(-1).value

    class FileAttributeTagInfo(ctypes.Structure):
        _fields_ = [
            ("file_attributes", wintypes.DWORD),
            ("reparse_tag", wintypes.DWORD),
        ]

    windows = cast(Any, ctypes)
    kernel32 = windows.WinDLL("kernel32", use_last_error=True)
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
        desired_access,
        file_share_read | file_share_write | file_share_delete,
        None,
        open_existing,
        file_flag_open_reparse_point,
        None,
    )
    if handle == invalid_handle:
        error = windows.get_last_error()
        if error in {2, 3}:
            raise FileNotFoundError(error, f"File is unavailable: {path}")
        raise SecureFileError(error, f"Could not open file: {path}")
    information = FileAttributeTagInfo()
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
        file_attribute_tag_info,
        ctypes.byref(information),
        ctypes.sizeof(information),
    ):
        error = windows.get_last_error()
        kernel32.CloseHandle(handle)
        raise SecureFileError(error, f"Could not inspect file: {path}")
    if information.file_attributes & file_attribute_reparse_point:
        kernel32.CloseHandle(handle)
        raise SecureFileError(f"Contained file is a reparse point: {path}")
    try:
        descriptor = cast(Any, msvcrt).open_osfhandle(
            int(handle),
            flags | getattr(os, "O_BINARY", 0),
        )
    except Exception:
        kernel32.CloseHandle(handle)
        raise
    try:
        state = os.fstat(descriptor)
    except Exception:
        os.close(descriptor)
        raise
    if not stat.S_ISREG(state.st_mode):
        os.close(descriptor)
        raise SecureFileError(f"Contained path is not a regular file: {path}")
    return descriptor
