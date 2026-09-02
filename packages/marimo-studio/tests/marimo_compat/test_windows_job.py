"""Protect Windows child-process ownership."""

from __future__ import annotations

import ctypes
from typing import Any, cast

import pytest

import marimo_studio._processes.windows as windows_job

pytestmark = pytest.mark.supported_python


class _Function:
    def __init__(self, *results: object) -> None:
        self.argtypes: object = None
        self.restype: object = None
        self.calls: list[tuple[object, ...]] = []
        self._results = list(results)

    def __call__(self, *args: object) -> object:
        self.calls.append(args)
        if len(self._results) > 1:
            return self._results.pop(0)
        return self._results[0]


class _ActiveProcesses:
    def __init__(self, *counts: int) -> None:
        self.argtypes: object = None
        self.restype: object = None
        self.calls = 0
        self._counts = list(counts)

    def __call__(self, *_args: object) -> bool:
        info = ctypes.cast(
            cast(Any, _args[2]),
            ctypes.POINTER(windows_job._BasicAccountingInformation),
        ).contents
        info.ActiveProcesses = self._counts.pop(0)
        self.calls += 1
        return True


def _failed_windows_call() -> OSError:
    return OSError("Windows process operation failed")


def test_windows_job_reports_termination_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    kernel: Any = type(
        "Kernel",
        (),
        {"TerminateJobObject": _Function(False)},
    )()
    monkeypatch.setattr(windows_job, "_load_library", lambda _name: kernel)
    monkeypatch.setattr(windows_job, "_windows_error", _failed_windows_call)

    with pytest.raises(OSError, match="operation failed"):
        windows_job.WindowsJob(7).terminate()


def test_windows_job_waits_until_every_process_exits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    active = _ActiveProcesses(2, 0)
    kernel: Any = type(
        "Kernel",
        (),
        {
            "TerminateJobObject": _Function(True),
            "QueryInformationJobObject": active,
        },
    )()
    monkeypatch.setattr(windows_job, "_load_library", lambda _name: kernel)
    monkeypatch.setattr(windows_job.time, "sleep", lambda _seconds: None)

    windows_job.WindowsJob(7).terminate()

    assert active.calls == 2


def test_windows_job_fails_when_processes_do_not_exit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    active = _ActiveProcesses(1)
    kernel: Any = type(
        "Kernel",
        (),
        {
            "TerminateJobObject": _Function(True),
            "QueryInformationJobObject": active,
        },
    )()
    clock = iter((0.0, windows_job._TERMINATION_TIMEOUT + 1))
    monkeypatch.setattr(windows_job, "_load_library", lambda _name: kernel)
    monkeypatch.setattr(windows_job.time, "monotonic", lambda: next(clock))

    with pytest.raises(OSError, match="remained alive"):
        windows_job.WindowsJob(7).terminate()


def test_windows_job_retries_handle_close_after_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    close_handle = _Function(False, True)
    kernel: Any = type("Kernel", (), {"CloseHandle": close_handle})()
    monkeypatch.setattr(windows_job, "_load_library", lambda _name: kernel)
    monkeypatch.setattr(windows_job, "_windows_error", _failed_windows_call)
    job = windows_job.WindowsJob(7)

    with pytest.raises(OSError, match="operation failed"):
        job.close()
    job.close()
    job.close()

    assert len(close_handle.calls) == 2


def test_windows_job_reports_process_handle_close_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    close_handle = _Function(False, True)
    kernel: Any = type(
        "Kernel",
        (),
        {
            "CreateJobObjectW": _Function(7),
            "SetInformationJobObject": _Function(True),
            "OpenProcess": _Function(8),
            "AssignProcessToJobObject": _Function(True),
            "CloseHandle": close_handle,
        },
    )()
    ntdll: Any = type("Ntdll", (), {"NtResumeProcess": _Function(0)})()
    monkeypatch.setattr(
        windows_job,
        "_load_library",
        lambda name: ntdll if name == "ntdll" else kernel,
    )
    monkeypatch.setattr(windows_job, "_windows_error", _failed_windows_call)

    with pytest.raises(OSError, match="operation failed"):
        windows_job.WindowsJob.create_for_process(123)

    assert len(close_handle.calls) == 2
