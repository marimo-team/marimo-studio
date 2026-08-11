"""Run one bounded child process and terminate its owned processes."""

from __future__ import annotations

import os
import signal
import subprocess
import threading
import time
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from typing import BinaryIO, Protocol, cast

_TERMINATION_TIMEOUT = 2.0
_MAX_OUTPUT_BYTES = 2_000_000
_MAX_ERROR_BYTES = 16_000
_MAX_ERROR_STREAM_BYTES = 2_000_000
_READ_CHUNK_BYTES = 64 * 1024
_FORCED_SIGNAL = getattr(signal, "SIGKILL", signal.SIGTERM)
_KILL_PROCESS_GROUP = cast(
    "Callable[[int, int], None] | None",
    getattr(os, "killpg", None),
)


@dataclass(frozen=True)
class ProcessResult:
    returncode: int
    stdout: bytes
    stderr: bytes
    timed_out: bool = False
    output_too_large: bool = False


class ProcessCleanupError(OSError):
    """Owned child processes or operating-system handles could not be cleaned up."""


class _ProcessTreeOwner(Protocol):
    def terminate(self) -> None: ...

    def close(self) -> None: ...


class _BoundedCapture:
    def __init__(
        self,
        keep: int,
        limit: int,
        overflow: threading.Event,
        *,
        tail: bool = False,
    ) -> None:
        self._keep = keep
        self._limit = limit
        self._overflow = overflow
        self._tail = tail
        self._buffer = bytearray()
        self.total = 0

    def append(self, chunk: bytes) -> None:
        self.total += len(chunk)
        if self.total > self._limit:
            self._overflow.set()
        if self._tail:
            if len(chunk) >= self._keep:
                self._buffer[:] = chunk[-self._keep :]
                return
            excess = max(0, len(self._buffer) + len(chunk) - self._keep)
            if excess:
                del self._buffer[:excess]
            self._buffer.extend(chunk)
            return
        remaining = self._keep - len(self._buffer)
        if remaining > 0:
            self._buffer.extend(chunk[:remaining])

    def value(self) -> bytes:
        return bytes(self._buffer)

    @property
    def overflowed(self) -> bool:
        return self._overflow.is_set()


class ProcessSupervisor:
    """Own one process and its cancellation boundary."""

    def __init__(self) -> None:
        self._cancelled = threading.Event()

    def cancel(self) -> None:
        self._cancelled.set()

    def run(self, command: list[str], timeout: float) -> ProcessResult:
        if self._cancelled.is_set():
            return ProcessResult(
                returncode=-int(signal.SIGTERM),
                stdout=b"",
                stderr=b"",
            )
        process = _start_process(command)
        try:
            tree_owner = _own_process_tree(process)
        except OSError:
            with suppress(OSError, ProcessLookupError):
                process.kill()
            _wait_for_exit(process, _TERMINATION_TIMEOUT)
            _close_process_streams(process)
            raise
        overflow = threading.Event()
        stdout = _BoundedCapture(_MAX_OUTPUT_BYTES, _MAX_OUTPUT_BYTES, overflow)
        stderr = _BoundedCapture(
            _MAX_ERROR_BYTES,
            _MAX_ERROR_STREAM_BYTES,
            overflow,
            tail=True,
        )
        stop_readers = threading.Event()
        readers = _start_readers(process, stdout, stderr, stop_readers)
        cleanup_errors: list[OSError] = []

        def terminate_owned_processes() -> None:
            try:
                _terminate_owned_processes(process, tree_owner)
            except OSError as error:
                cleanup_errors.append(error)

        if self._cancelled.is_set():
            terminate_owned_processes()
        deadline = time.monotonic() + timeout
        timed_out = False
        try:
            while True:
                if overflow.is_set():
                    terminate_owned_processes()
                    break
                if self._cancelled.is_set():
                    terminate_owned_processes()
                    break
                if process.poll() is not None:
                    break
                if time.monotonic() >= deadline:
                    timed_out = True
                    terminate_owned_processes()
                    break
                self._cancelled.wait(0.01)
            terminate_owned_processes()
            try:
                returncode = process.wait(timeout=_TERMINATION_TIMEOUT)
            except subprocess.TimeoutExpired:
                with suppress(OSError, ProcessLookupError):
                    process.kill()
                _wait_for_exit(process, _TERMINATION_TIMEOUT)
                returncode = process.poll()
                if returncode is None:
                    returncode = -int(_FORCED_SIGNAL)
        finally:
            terminate_owned_processes()
            if tree_owner is not None:
                try:
                    tree_owner.close()
                except OSError as error:
                    cleanup_errors.append(error)
            _finish_readers(process, readers, stop_readers)
        if cleanup_errors:
            error = cleanup_errors[0]
            raise ProcessCleanupError(str(error)) from error
        return ProcessResult(
            returncode=returncode,
            stdout=stdout.value(),
            stderr=stderr.value(),
            timed_out=timed_out,
            output_too_large=overflow.is_set(),
        )


def _start_process(
    command: list[str],
) -> subprocess.Popen[bytes]:
    if os.name == "posix":
        return subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
            text=False,
        )
    creation_flag = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(
        subprocess,
        "CREATE_SUSPENDED",
        0x00000004,
    )
    return subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=creation_flag,
        text=False,
    )


def _start_readers(
    process: subprocess.Popen[bytes],
    stdout: _BoundedCapture,
    stderr: _BoundedCapture,
    stop: threading.Event,
) -> tuple[threading.Thread, threading.Thread]:
    assert process.stdout is not None
    assert process.stderr is not None
    readers = (
        threading.Thread(
            target=_drain_stream,
            args=(process.stdout, stdout, stop),
            daemon=True,
        ),
        threading.Thread(
            target=_drain_stream,
            args=(process.stderr, stderr, stop),
            daemon=True,
        ),
    )
    for reader in readers:
        reader.start()
    return readers


def _drain_stream(
    stream: BinaryIO,
    capture: _BoundedCapture,
    stop: threading.Event,
) -> None:
    if os.name == "posix":
        _drain_posix_stream(stream, capture, stop)
        return
    try:
        while chunk := stream.read(_READ_CHUNK_BYTES):
            capture.append(chunk)
    except (OSError, ValueError):
        pass


def _drain_posix_stream(
    stream: BinaryIO,
    capture: _BoundedCapture,
    stop: threading.Event,
) -> None:
    descriptor = stream.fileno()
    os.set_blocking(descriptor, False)
    while True:
        try:
            chunk = os.read(descriptor, _READ_CHUNK_BYTES)
        except BlockingIOError:
            if stop.is_set():
                return
            stop.wait(0.01)
            continue
        except OSError:
            return
        if not chunk:
            return
        capture.append(chunk)
        if stop.is_set() and capture.overflowed:
            return


def _finish_readers(
    process: subprocess.Popen[bytes],
    readers: tuple[threading.Thread, threading.Thread],
    stop: threading.Event,
) -> None:
    stop.set()
    for reader in readers:
        reader.join(_TERMINATION_TIMEOUT)
    _close_process_streams(process)
    for reader in readers:
        if reader.is_alive():
            reader.join(_TERMINATION_TIMEOUT)


def _close_process_streams(process: subprocess.Popen[bytes]) -> None:
    for stream in (process.stdout, process.stderr):
        if stream is not None:
            with suppress(OSError, ValueError):
                stream.close()


def _own_process_tree(process: subprocess.Popen[bytes]) -> _ProcessTreeOwner | None:
    if os.name != "nt":
        return None
    from marimo_studio._windows_job import WindowsJob

    return WindowsJob.create_for_process(process.pid)


def _terminate_owned_processes(
    process: subprocess.Popen[bytes],
    tree_owner: _ProcessTreeOwner | None = None,
) -> None:
    if os.name == "posix":
        _signal_process_group(process, signal.SIGTERM)
        if _wait_for_process_group_exit(process, _TERMINATION_TIMEOUT):
            return
        _signal_process_group(process, _FORCED_SIGNAL)
        if not _wait_for_process_group_exit(process, _TERMINATION_TIMEOUT):
            with suppress(OSError, ProcessLookupError):
                process.kill()
            _wait_for_exit(process, _TERMINATION_TIMEOUT)
            if not _process_group_disappeared(process):
                raise OSError(
                    "The isolated notebook process group remained alive after "
                    "forced termination."
                )
        return

    if tree_owner is not None:
        try:
            tree_owner.terminate()
        except OSError:
            with suppress(OSError, ProcessLookupError):
                process.kill()
            _wait_for_exit(process, _TERMINATION_TIMEOUT)
            raise
        _wait_for_exit(process, _TERMINATION_TIMEOUT)
        return
    if process.poll() is not None:
        return
    break_signal = getattr(signal, "CTRL_BREAK_EVENT", None)
    if break_signal is not None:
        with suppress(OSError, ProcessLookupError):
            process.send_signal(break_signal)
        if _wait_for_exit(process, _TERMINATION_TIMEOUT):
            return
    try:
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            check=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=_TERMINATION_TIMEOUT,
        )
    except (OSError, subprocess.TimeoutExpired):
        with suppress(OSError, ProcessLookupError):
            process.kill()
    _wait_for_exit(process, _TERMINATION_TIMEOUT)


def _signal_process_group(
    process: subprocess.Popen[bytes],
    requested_signal: signal.Signals,
) -> None:
    if _KILL_PROCESS_GROUP is None:
        return
    try:
        _KILL_PROCESS_GROUP(process.pid, requested_signal)
    except ProcessLookupError:
        return
    except OSError as error:
        if _process_group_disappeared(process):
            return
        with suppress(OSError, ProcessLookupError):
            process.kill()
        _wait_for_exit(process, _TERMINATION_TIMEOUT)
        raise error


def _process_group_disappeared(
    process: subprocess.Popen[bytes],
    timeout: float = 0.05,
) -> bool:
    if _KILL_PROCESS_GROUP is None:
        return True
    deadline = time.monotonic() + timeout
    while True:
        try:
            _KILL_PROCESS_GROUP(process.pid, 0)
        except ProcessLookupError:
            return True
        except PermissionError:
            if process.poll() is None or time.monotonic() >= deadline:
                return False
            time.sleep(0.001)
            continue
        except OSError:
            return False
        return False


def _wait_for_exit(process: subprocess.Popen[bytes], timeout: float) -> bool:
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        return False
    return True


def _wait_for_process_group_exit(
    process: subprocess.Popen[bytes],
    timeout: float,
) -> bool:
    if _KILL_PROCESS_GROUP is None:
        return process.poll() is not None
    deadline = time.monotonic() + timeout
    while True:
        process.poll()
        try:
            _KILL_PROCESS_GROUP(process.pid, 0)
        except ProcessLookupError:
            return True
        except PermissionError:
            pass
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        time.sleep(min(0.01, remaining))


__all__ = ["ProcessCleanupError", "ProcessResult", "ProcessSupervisor"]
