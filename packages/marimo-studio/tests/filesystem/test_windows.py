from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

import marimo_studio._filesystem._windows as windows

pytestmark = pytest.mark.supported_python


class _Function:
    def __init__(self, callback: Any) -> None:
        self._callback = callback
        self.argtypes: Any = None
        self.restype: Any = None

    def __call__(self, *args: Any) -> Any:
        return self._callback(*args)


class _Kernel32:
    def __init__(self, *, reopened_tag: int = 0, reopened_index: int = 101) -> None:
        self.create_flags: list[int] = []
        self.closed: list[int] = []
        self.reopened_tag = reopened_tag
        self.reopened_index = reopened_index

        def create_file(
            _path: str,
            _access: int,
            _share: int,
            _security: Any,
            _disposition: int,
            flags: int,
            _template: Any,
        ) -> int:
            self.create_flags.append(flags)
            return 101 if len(self.create_flags) == 1 else 102

        def get_information(handle: int, pointer: Any) -> bool:
            pointer._obj.file_attributes = (
                windows._FILE_ATTRIBUTE_REPARSE_POINT
                if handle == 101 or self.reopened_tag
                else 0
            )
            pointer._obj.volume_serial_number = 7
            pointer._obj.file_index_low = 101 if handle == 101 else self.reopened_index
            return True

        def get_information_ex(
            _handle: int,
            _info_class: int,
            pointer: Any,
            _size: int,
        ) -> bool:
            pointer._obj.reparse_tag = (
                0x9000001A if _handle == 101 else self.reopened_tag
            )
            return True

        self.CreateFileW = _Function(create_file)
        self.GetFileInformationByHandle = _Function(get_information)
        self.GetFileInformationByHandleEx = _Function(get_information_ex)
        self.CloseHandle = _Function(lambda handle: self.closed.append(handle))


def test_data_reparse_handles_are_reopened_through_the_cloud_filter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    kernel32 = _Kernel32()
    monkeypatch.setattr(windows, "_kernel32", lambda: kernel32)

    handle = windows._open_handle(
        Path("cloud-placeholder"),
        windows._GENERIC_READ,
        0,
        "File",
        share=windows._FILE_SHARE_ALL,
        follow_data_reparse=True,
    )

    assert handle == 102
    assert kernel32.create_flags == [
        windows._FILE_FLAG_OPEN_REPARSE_POINT,
        0,
    ]
    assert kernel32.closed == [101]


def test_reopened_handle_rejects_a_replaced_name_surrogate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    kernel32 = _Kernel32(reopened_tag=0xA000000C)
    monkeypatch.setattr(windows, "_kernel32", lambda: kernel32)

    with pytest.raises(windows.UnsafePathError, match="symlink or junction"):
        windows._open_handle(
            Path("cloud-placeholder"),
            windows._GENERIC_READ,
            0,
            "File",
            share=windows._FILE_SHARE_ALL,
            follow_data_reparse=True,
        )

    assert kernel32.closed == [102, 101]


def test_reopened_handle_rejects_a_replaced_entry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    kernel32 = _Kernel32(reopened_index=202)
    monkeypatch.setattr(windows, "_kernel32", lambda: kernel32)

    with pytest.raises(windows.UnsafePathError, match="changed while opening"):
        windows._open_handle(
            Path("cloud-placeholder"),
            windows._GENERIC_READ,
            0,
            "File",
            share=windows._FILE_SHARE_ALL,
            follow_data_reparse=True,
        )

    assert kernel32.closed == [102, 101]
