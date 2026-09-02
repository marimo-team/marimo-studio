"""Run one bounded child process and terminate its owned processes."""

from __future__ import annotations

import os
import select
import signal
import subprocess
import threading
import time
from collections.abc import Mapping
from contextlib import suppress
from dataclasses import dataclass
from typing import Any, BinaryIO, cast

from marimo_studio._processes.process_owner import (
    TERMINATION_TIMEOUT as _TERMINATION_TIMEOUT,
)
from marimo_studio._processes.process_owner import create_process_owner, wait_for_exit

MAX_PROCESS_STDOUT_BYTES = 2_000_000
_MAX_ERROR_BYTES = 16_000
_MAX_ERROR_STREAM_BYTES = 2_000_000
_READ_CHUNK_BYTES = 64 * 1024
_FORCED_SIGNAL = getattr(signal, "SIGKILL", signal.SIGTERM)


@dataclass(frozen=True)
class ProcessResult:
    returncode: int
    stdout: bytes
    stderr: bytes
    timed_out: bool = False
    output_too_large: bool = False


def process_returncode_message(
    returncode: int,
    *,
    platform: str = os.name,
) -> str:
    """Describe one POSIX signal status or Windows exception status."""
    if platform != "posix":
        if returncode < 0 or returncode > 0x7FFFFFFF:
            return f"exited with status 0x{returncode & 0xFFFFFFFF:08X}"
        return f"exited with status {returncode}"
    if returncode >= 0:
        return f"exited with status {returncode}"
    try:
        name = signal.Signals(-returncode).name
    except ValueError:
        name = str(-returncode)
    return f"was terminated by signal {name}"


class ProcessCleanupError(OSError):
    """Owned child processes or operating-system handles could not be cleaned up."""


class _ProcessExitObserver:
    """Observe a POSIX leader exit without reaping its process-group ID."""

    def __init__(self, process: subprocess.Popen[bytes]) -> None:
        self._process = process
        self._exited = False
        self._queue: Any | None = None
        select_api = cast(Any, select)
        if os.name != "posix" or not hasattr(select_api, "kqueue"):
            return
        queue = select_api.kqueue()
        try:
            event = select_api.kevent(
                process.pid,
                filter=select_api.KQ_FILTER_PROC,
                flags=select_api.KQ_EV_ADD | select_api.KQ_EV_ONESHOT,
                fflags=select_api.KQ_NOTE_EXIT,
            )
            queue.control([event], 0, 0)
        except OSError:
            queue.close()
        else:
            self._queue = queue

    def exited(self) -> bool:
        if self._exited or self._process.returncode is not None:
            self._exited = True
            return True
        if self._queue is not None:
            self._exited = bool(self._queue.control(None, 1, 0))
            if not self._exited:
                self._exited = _process_exited_without_reaping(self._process)
            return self._exited
        self._exited = _process_exited_without_reaping(self._process)
        return self._exited

    def close(self) -> None:
        if self._queue is not None:
            self._queue.close()
            self._queue = None


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

    def __init__(self, *, owns_process_tree: bool = True) -> None:
        self._cancelled = threading.Event()
        self._owns_process_tree = owns_process_tree

    def cancel(self) -> None:
        self._cancelled.set()

    def run(
        self,
        command: list[str],
        timeout: float,
        *,
        cwd: str | os.PathLike[str] | None = None,
        env: Mapping[str, str] | None = None,
    ) -> ProcessResult:
        if self._cancelled.is_set():
            return ProcessResult(
                returncode=-int(signal.SIGTERM),
                stdout=b"",
                stderr=b"",
            )
        process_owner = create_process_owner(
            env,
            owns_process_tree=self._owns_process_tree,
        )
        process = _start_process(
            command,
            cwd=cwd,
            env=process_owner.launch_environment,
            owns_process_tree=self._owns_process_tree,
        )
        overflow = threading.Event()
        stdout = _BoundedCapture(
            MAX_PROCESS_STDOUT_BYTES,
            MAX_PROCESS_STDOUT_BYTES,
            overflow,
        )
        stderr = _BoundedCapture(
            _MAX_ERROR_BYTES,
            _MAX_ERROR_STREAM_BYTES,
            overflow,
            tail=True,
        )
        stop_readers = threading.Event()
        readers: list[threading.Thread] = []
        exit_observer: _ProcessExitObserver | None = None
        cleanup_errors: list[Exception] = []
        cleanup_started = False

        def terminate_processes() -> None:
            nonlocal cleanup_started
            if cleanup_started:
                return
            cleanup_started = True
            try:
                process_owner.terminate()
            except OSError as error:
                cleanup_errors.append(error)

        timed_out = False
        returncode = -int(_FORCED_SIGNAL)
        operation_error: BaseException | None = None
        try:
            process_owner.attach(process)
            exit_observer = _ProcessExitObserver(process)
            _start_readers(process, stdout, stderr, stop_readers, readers)
            if self._cancelled.is_set():
                terminate_processes()
            deadline = time.monotonic() + timeout
            while True:
                if overflow.is_set():
                    terminate_processes()
                    break
                if self._cancelled.is_set():
                    terminate_processes()
                    break
                if exit_observer.exited():
                    break
                if time.monotonic() >= deadline:
                    timed_out = True
                    terminate_processes()
                    break
                self._cancelled.wait(0.01)
            terminate_processes()
            try:
                returncode = process.wait(timeout=_TERMINATION_TIMEOUT)
            except subprocess.TimeoutExpired:
                with suppress(OSError, ProcessLookupError):
                    process.kill()
                wait_for_exit(process, _TERMINATION_TIMEOUT)
                observed_returncode = process.poll()
                returncode = (
                    observed_returncode
                    if observed_returncode is not None
                    else -int(_FORCED_SIGNAL)
                )
        except BaseException as error:
            operation_error = error
        finally:
            terminate_processes()
            try:
                exited = wait_for_exit(process, _TERMINATION_TIMEOUT)
            except OSError as error:
                cleanup_errors.append(error)
                exited = False
            if not exited:
                try:
                    process.kill()
                except ProcessLookupError:
                    pass
                except OSError as error:
                    cleanup_errors.append(error)
                try:
                    forced_exit = wait_for_exit(process, _TERMINATION_TIMEOUT)
                except OSError as error:
                    cleanup_errors.append(error)
                    forced_exit = None
                if forced_exit is False:
                    cleanup_errors.append(
                        OSError(
                            "The owned process remained alive after "
                            "final forced termination."
                        )
                    )
            try:
                process_owner.close()
            except Exception as error:
                cleanup_errors.append(error)
            try:
                _finish_readers(process, tuple(readers), stop_readers)
            except Exception as error:
                cleanup_errors.append(error)
            finally:
                _close_process_streams(process)
            if exit_observer is not None:
                try:
                    exit_observer.close()
                except Exception as error:
                    cleanup_errors.append(error)
        if cleanup_errors:
            error = cleanup_errors[0]
            if operation_error is not None:
                raise ProcessCleanupError(str(error)) from operation_error
            raise ProcessCleanupError(str(error)) from error
        if operation_error is not None:
            raise operation_error.with_traceback(operation_error.__traceback__)
        return ProcessResult(
            returncode=returncode,
            stdout=stdout.value(),
            stderr=stderr.value(),
            timed_out=timed_out,
            output_too_large=overflow.is_set(),
        )


def _start_process(
    command: list[str],
    *,
    cwd: str | os.PathLike[str] | None,
    env: Mapping[str, str] | None,
    owns_process_tree: bool = True,
) -> subprocess.Popen[bytes]:
    if os.name == "posix":
        return subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=cwd,
            env=env,
            start_new_session=owns_process_tree,
            text=False,
        )
    creation_flag = 0
    if owns_process_tree:
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
        cwd=cwd,
        env=env,
        creationflags=creation_flag,
        text=False,
    )


def _start_readers(
    process: subprocess.Popen[bytes],
    stdout: _BoundedCapture,
    stderr: _BoundedCapture,
    stop: threading.Event,
    started: list[threading.Thread] | None = None,
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
    active = started if started is not None else []
    for reader in readers:
        reader.start()
        active.append(reader)
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
    readers: tuple[threading.Thread, ...],
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


def _process_exited_without_reaping(process: subprocess.Popen[bytes]) -> bool:
    if os.name != "posix":
        return process.poll() is not None
    waitid = getattr(os, "waitid", None)
    wait_options = (
        getattr(os, "WEXITED", 0)
        | getattr(os, "WNOHANG", 0)
        | getattr(os, "WNOWAIT", 0)
    )
    if waitid is not None and wait_options:
        try:
            return waitid(os.P_PID, process.pid, wait_options) is not None
        except ChildProcessError:
            return process.returncode is not None
    try:
        import psutil
    except ImportError:
        return False
    try:
        return psutil.Process(process.pid).status() == psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:
        return True
    except psutil.Error:
        return False
