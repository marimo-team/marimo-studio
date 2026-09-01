"""Own a Windows process tree with a kill-on-close Job Object."""

from __future__ import annotations

import ctypes
import time
from ctypes import wintypes
from threading import Lock
from typing import Any

_JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
_JOB_OBJECT_BASIC_ACCOUNTING_INFORMATION = 1
_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
_PROCESS_TERMINATE = 0x0001
_PROCESS_SET_QUOTA = 0x0100
_PROCESS_SUSPEND_RESUME = 0x0800
_ctypes_api: Any = ctypes
_TERMINATION_TIMEOUT = 2.0
_TERMINATION_POLL_INTERVAL = 0.01


def _load_library(name: str) -> Any:
    loader = getattr(ctypes, "WinDLL", None)
    if loader is None:
        raise OSError("Windows process APIs are unavailable on this platform.")
    return loader(name, use_last_error=True)


def _windows_error() -> OSError:
    error_code = _ctypes_api.get_last_error()
    return _ctypes_api.WinError(error_code)


class _IoCounters(ctypes.Structure):
    _fields_ = [
        ("ReadOperationCount", ctypes.c_ulonglong),
        ("WriteOperationCount", ctypes.c_ulonglong),
        ("OtherOperationCount", ctypes.c_ulonglong),
        ("ReadTransferCount", ctypes.c_ulonglong),
        ("WriteTransferCount", ctypes.c_ulonglong),
        ("OtherTransferCount", ctypes.c_ulonglong),
    ]


class _BasicLimitInformation(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_longlong),
        ("PerJobUserTimeLimit", ctypes.c_longlong),
        ("LimitFlags", wintypes.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", wintypes.DWORD),
        ("SchedulingClass", wintypes.DWORD),
    ]


class _ExtendedLimitInformation(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _BasicLimitInformation),
        ("IoInfo", _IoCounters),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


class _BasicAccountingInformation(ctypes.Structure):
    _fields_ = [
        ("TotalUserTime", ctypes.c_longlong),
        ("TotalKernelTime", ctypes.c_longlong),
        ("ThisPeriodTotalUserTime", ctypes.c_longlong),
        ("ThisPeriodTotalKernelTime", ctypes.c_longlong),
        ("TotalPageFaultCount", wintypes.DWORD),
        ("TotalProcesses", wintypes.DWORD),
        ("ActiveProcesses", wintypes.DWORD),
        ("TotalTerminatedProcesses", wintypes.DWORD),
    ]


class WindowsJob:
    """Assign one worker tree to a Job Object and close it idempotently."""

    def __init__(self, handle: int) -> None:
        self._handle = handle
        self._lock = Lock()

    @classmethod
    def create_for_process(cls, pid: int) -> WindowsJob:
        kernel32 = _load_library("kernel32")
        kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        kernel32.SetInformationJobObject.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
        ]
        kernel32.SetInformationJobObject.restype = wintypes.BOOL
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL

        handle = kernel32.CreateJobObjectW(None, None)
        if not handle:
            raise _windows_error()
        job = cls(int(handle))
        try:
            limits = _ExtendedLimitInformation()
            limits.BasicLimitInformation.LimitFlags = (
                _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            )
            if not kernel32.SetInformationJobObject(
                handle,
                _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
                ctypes.byref(limits),
                ctypes.sizeof(limits),
            ):
                raise _windows_error()
            process = kernel32.OpenProcess(
                _PROCESS_TERMINATE | _PROCESS_SET_QUOTA | _PROCESS_SUSPEND_RESUME,
                False,
                pid,
            )
            if not process:
                raise _windows_error()
            try:
                if not kernel32.AssignProcessToJobObject(handle, process):
                    raise _windows_error()
                ntdll = _load_library("ntdll")
                ntdll.NtResumeProcess.argtypes = [wintypes.HANDLE]
                ntdll.NtResumeProcess.restype = wintypes.LONG
                status = ntdll.NtResumeProcess(process)
                if status != 0:
                    raise OSError(f"NtResumeProcess failed with status {status:#x}")
            except BaseException as error:
                if not kernel32.CloseHandle(process):
                    raise _windows_error() from error
                raise
            if not kernel32.CloseHandle(process):
                raise _windows_error()
        except BaseException as error:
            try:
                job.close()
            except OSError as cleanup_error:
                raise error from cleanup_error
            raise
        return job

    def terminate(self) -> None:
        with self._lock:
            handle = self._handle
            if not handle:
                return
            kernel32 = _load_library("kernel32")
            kernel32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
            kernel32.TerminateJobObject.restype = wintypes.BOOL
            if not kernel32.TerminateJobObject(handle, 1):
                raise _windows_error()
            kernel32.QueryInformationJobObject.argtypes = [
                wintypes.HANDLE,
                ctypes.c_int,
                ctypes.c_void_p,
                wintypes.DWORD,
                ctypes.POINTER(wintypes.DWORD),
            ]
            kernel32.QueryInformationJobObject.restype = wintypes.BOOL
            deadline = time.monotonic() + _TERMINATION_TIMEOUT
            while _active_processes(kernel32, handle):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise OSError(
                        "Windows job processes remained alive after termination."
                    )
                time.sleep(min(_TERMINATION_POLL_INTERVAL, remaining))

    def close(self) -> None:
        with self._lock:
            handle = self._handle
            if not handle:
                return
            kernel32 = _load_library("kernel32")
            kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
            kernel32.CloseHandle.restype = wintypes.BOOL
            if not kernel32.CloseHandle(handle):
                raise _windows_error()
            self._handle = 0


def _active_processes(kernel32: Any, handle: int) -> int:
    accounting = _BasicAccountingInformation()
    returned = wintypes.DWORD()
    if not kernel32.QueryInformationJobObject(
        handle,
        _JOB_OBJECT_BASIC_ACCOUNTING_INFORMATION,
        ctypes.byref(accounting),
        ctypes.sizeof(accounting),
        ctypes.byref(returned),
    ):
        raise _windows_error()
    return int(accounting.ActiveProcesses)
