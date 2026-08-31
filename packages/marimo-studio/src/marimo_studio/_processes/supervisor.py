"""Run one bounded child process and terminate its owned processes."""

from __future__ import annotations

import os
import secrets
import select
import signal
import subprocess
import threading
import time
from collections.abc import Callable, Mapping
from contextlib import suppress
from dataclasses import dataclass
from typing import Any, BinaryIO, Protocol, cast

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
_PROCESS_OWNER_ENV = "_MARIMO_STUDIO_PROCESS_OWNER"


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


class _TaggedProcessTreeOwner:
    """Terminate same-user descendants that escaped their original group."""

    def __init__(self, token: str) -> None:
        self._token = token

    def terminate(self) -> None:
        try:
            import psutil
        except ImportError as error:
            raise OSError(
                "Detached process cleanup requires the installed psutil runtime."
            ) from error
        for requested_signal in ("terminate", "kill"):
            processes = self._matching_processes(psutil)
            if not processes:
                return
            for process in processes:
                with suppress(psutil.Error):
                    getattr(process, requested_signal)()
            _gone, alive = psutil.wait_procs(processes, timeout=_TERMINATION_TIMEOUT)
            if not alive and not self._matching_processes(psutil):
                return
        remaining = self._matching_processes(psutil)
        if remaining:
            raise OSError(
                "Owned detached processes remained alive after forced termination: "
                + ", ".join(str(process.pid) for process in remaining)
            )

    def _matching_processes(self, psutil: Any) -> list[Any]:
        owner = os.getuid() if hasattr(os, "getuid") else None
        matches = []
        for process in psutil.process_iter(("pid", "uids")):
            try:
                uids = process.info.get("uids")
                if owner is not None and (uids is None or uids.real != owner):
                    continue
                if process.environ().get(_PROCESS_OWNER_ENV) == self._token:
                    matches.append(process)
            except (psutil.AccessDenied, psutil.NoSuchProcess, psutil.ZombieProcess):
                continue
        return matches

    def close(self) -> None:
        return


class _ProcessExitObserver:
    """Observe a POSIX leader exit without reaping its process-group ID."""

    def __init__(self, process: subprocess.Popen[bytes]) -> None:
        self._process = process
        self._exited = False
        self._queue: Any | None = None
        if os.name != "posix" or not hasattr(select, "kqueue"):
            return
        queue = select.kqueue()
        try:
            event = select.kevent(
                process.pid,
                filter=select.KQ_FILTER_PROC,
                flags=select.KQ_EV_ADD | select.KQ_EV_ONESHOT,
                fflags=select.KQ_NOTE_EXIT,
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
        process_environment, owner_token = _owned_environment(
            env,
            owns_process_tree=self._owns_process_tree,
        )
        process = _start_process(
            command,
            cwd=cwd,
            env=process_environment,
            owns_process_tree=self._owns_process_tree,
        )
        overflow = threading.Event()
        stdout = _BoundedCapture(_MAX_OUTPUT_BYTES, _MAX_OUTPUT_BYTES, overflow)
        stderr = _BoundedCapture(
            _MAX_ERROR_BYTES,
            _MAX_ERROR_STREAM_BYTES,
            overflow,
            tail=True,
        )
        stop_readers = threading.Event()
        readers: list[threading.Thread] = []
        exit_observer: _ProcessExitObserver | None = None
        tree_owner: _ProcessTreeOwner | None = None
        cleanup_errors: list[Exception] = []
        cleanup_started = False

        def terminate_processes() -> None:
            nonlocal cleanup_started
            if cleanup_started:
                return
            cleanup_started = True
            try:
                if self._owns_process_tree:
                    _terminate_owned_processes(process, tree_owner)
                else:
                    _terminate_process(process)
            except OSError as error:
                cleanup_errors.append(error)

        timed_out = False
        returncode = -int(_FORCED_SIGNAL)
        operation_error: BaseException | None = None
        try:
            tree_owner = (
                _own_process_tree(process, owner_token)
                if self._owns_process_tree
                else None
            )
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
                _wait_for_exit(process, _TERMINATION_TIMEOUT)
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
                exited = _wait_for_exit(process, _TERMINATION_TIMEOUT)
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
                    forced_exit = _wait_for_exit(process, _TERMINATION_TIMEOUT)
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
            if tree_owner is not None:
                try:
                    tree_owner.close()
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


def _owned_environment(
    environment: Mapping[str, str] | None,
    *,
    owns_process_tree: bool,
) -> tuple[dict[str, str], str | None]:
    selected = os.environ.copy() if environment is None else dict(environment)
    inherited = os.environ.get(_PROCESS_OWNER_ENV)
    if owns_process_tree and inherited is None:
        token = secrets.token_urlsafe(24)
    else:
        token = inherited
    if token is not None:
        selected[_PROCESS_OWNER_ENV] = token
    else:
        selected.pop(_PROCESS_OWNER_ENV, None)
    return selected, token if owns_process_tree and inherited is None else None


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


def _own_process_tree(
    process: subprocess.Popen[bytes],
    owner_token: str | None,
) -> _ProcessTreeOwner | None:
    if os.name == "posix":
        return _TaggedProcessTreeOwner(owner_token) if owner_token is not None else None
    if os.name != "nt":
        return None
    from marimo_studio._processes.windows import WindowsJob

    return WindowsJob.create_for_process(process.pid)


def _terminate_owned_processes(
    process: subprocess.Popen[bytes],
    tree_owner: _ProcessTreeOwner | None = None,
    *,
    platform: str | None = None,
) -> None:
    selected_platform = os.name if platform is None else platform
    if selected_platform == "posix":
        group_error: OSError | None = None
        try:
            _terminate_process_group(process)
        except OSError as error:
            group_error = error
        try:
            if tree_owner is not None:
                tree_owner.terminate()
        except OSError as error:
            if group_error is not None:
                raise error from group_error
            raise
        if group_error is not None:
            raise group_error
        return

    if tree_owner is not None:
        try:
            tree_owner.terminate()
        except OSError as error:
            with suppress(OSError, ProcessLookupError):
                process.kill()
            if not _wait_for_exit(process, _TERMINATION_TIMEOUT):
                raise OSError(
                    "The owned process remained alive after a "
                    "Windows job termination failure."
                ) from error
            raise
        if _wait_for_exit(process, _TERMINATION_TIMEOUT):
            return
        with suppress(OSError, ProcessLookupError):
            process.kill()
        if _wait_for_exit(process, _TERMINATION_TIMEOUT):
            return
        raise OSError("The owned process remained alive after Windows job termination.")
    if process.poll() is not None:
        return
    break_signal = getattr(signal, "CTRL_BREAK_EVENT", None)
    if break_signal is not None:
        with suppress(OSError, ProcessLookupError):
            process.send_signal(break_signal)
        if _wait_for_exit(process, _TERMINATION_TIMEOUT):
            return
    with suppress(OSError, subprocess.TimeoutExpired):
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            check=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=_TERMINATION_TIMEOUT,
        )
    if _wait_for_exit(process, _TERMINATION_TIMEOUT):
        return
    with suppress(OSError, ProcessLookupError):
        process.kill()
    if _wait_for_exit(process, _TERMINATION_TIMEOUT):
        return
    raise OSError(
        "The owned process remained alive after taskkill and forced termination."
    )


def _terminate_process_group(process: subprocess.Popen[bytes]) -> None:
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
                "The owned process group remained alive after forced termination."
            )


def _terminate_process(process: subprocess.Popen[bytes]) -> None:
    """Stop one child while its enclosing operation owns the process tree."""
    if process.poll() is not None:
        return
    with suppress(OSError, ProcessLookupError):
        process.terminate()
    if _wait_for_exit(process, _TERMINATION_TIMEOUT):
        return
    with suppress(OSError, ProcessLookupError):
        process.kill()
    if _wait_for_exit(process, _TERMINATION_TIMEOUT):
        return
    raise OSError(
        "The contained child process remained alive after forced termination."
    )


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
        if _wait_for_process_group_exit(
            process,
            _TERMINATION_TIMEOUT,
        ):
            return
        with suppress(OSError, ProcessLookupError):
            process.kill()
        _wait_for_exit(process, _TERMINATION_TIMEOUT)
        raise error


def _process_group_disappeared(
    process: subprocess.Popen[bytes],
) -> bool:
    if _KILL_PROCESS_GROUP is None:
        return True
    try:
        _KILL_PROCESS_GROUP(process.pid, 0)
    except ProcessLookupError:
        return True
    except PermissionError:
        return _permission_denied_group_disappeared(process)
    except OSError:
        return False
    return _process_group_has_live_members(process.pid) is False


def _permission_denied_group_disappeared(
    process: subprocess.Popen[bytes],
) -> bool:
    live_members = _process_group_has_live_members(process.pid)
    return live_members is False


def _process_group_has_live_members(group: int) -> bool | None:
    """Inspect a POSIX group after Darwin reports EPERM for a zombie leader."""
    try:
        result = subprocess.run(
            ["ps", "-axo", "pgid=,stat="],
            check=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=_TERMINATION_TIMEOUT,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    for line in result.stdout.splitlines():
        fields = line.split(maxsplit=1)
        if len(fields) != 2:
            continue
        try:
            process_group = int(fields[0])
        except ValueError:
            continue
        if process_group == group and not fields[1].startswith("Z"):
            return True
    return False


def _wait_for_exit(process: subprocess.Popen[bytes], timeout: float) -> bool:
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        return False
    return True


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


def _wait_for_process_group_exit(
    process: subprocess.Popen[bytes],
    timeout: float,
) -> bool:
    if _KILL_PROCESS_GROUP is None:
        return process.poll() is not None
    deadline = time.monotonic() + timeout
    while True:
        try:
            _KILL_PROCESS_GROUP(process.pid, 0)
        except ProcessLookupError:
            return True
        except PermissionError:
            if _permission_denied_group_disappeared(process):
                return True
        else:
            if _process_group_has_live_members(process.pid) is False:
                return True
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        time.sleep(min(0.01, remaining))
