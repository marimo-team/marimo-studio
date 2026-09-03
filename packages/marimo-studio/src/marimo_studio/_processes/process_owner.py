"""Own one launched process across platform cleanup boundaries."""

from __future__ import annotations

import os
import secrets
import signal
import subprocess
import time
from collections.abc import Callable, Mapping
from contextlib import suppress
from typing import Any, Protocol, cast

TERMINATION_TIMEOUT = 2.0
_FORCED_SIGNAL = getattr(signal, "SIGKILL", signal.SIGTERM)
_KILL_PROCESS_GROUP = cast(
    "Callable[[int, int], None] | None",
    getattr(os, "killpg", None),
)
_PROCESS_OWNER_ENV = "_MARIMO_STUDIO_PROCESS_OWNER"
_PROCESS_GROUP_OWNER_ENV = "_MARIMO_STUDIO_PROCESS_GROUP_OWNER"


class ProcessOwner(Protocol):
    """Prepare and clean up one launched process."""

    launch_environment: Mapping[str, str]

    def attach(self, process: subprocess.Popen[bytes]) -> None: ...

    def terminate(self) -> None: ...

    def close(self) -> None: ...


def create_process_owner(
    environment: Mapping[str, str] | None,
    *,
    owns_process_tree: bool,
    platform: str = os.name,
) -> ProcessOwner:
    """Create the platform owner before launching its process."""
    if not owns_process_tree:
        return _SingleProcessOwner(_inherited_environment(environment))
    if platform == "posix":
        launch_environment, owner_token, group_token = _owned_environment(environment)
        return _PosixProcessOwner(
            launch_environment,
            owner_token=owner_token,
            group_token=group_token,
        )
    return _WindowsProcessOwner(_windows_environment(environment))


def wait_for_exit(process: subprocess.Popen[bytes], timeout: float) -> bool:
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        return False
    return True


class _ProcessOwnerBase:
    def __init__(self, launch_environment: Mapping[str, str]) -> None:
        self.launch_environment = launch_environment
        self._process: subprocess.Popen[bytes] | None = None

    def attach(self, process: subprocess.Popen[bytes]) -> None:
        self._process = process

    def _attached_process(self) -> subprocess.Popen[bytes]:
        if self._process is None:
            raise RuntimeError("The process owner has no attached process.")
        return self._process

    def close(self) -> None:
        return


class _SingleProcessOwner(_ProcessOwnerBase):
    """Stop one child while an enclosing owner retains its descendants."""

    def terminate(self) -> None:
        process = self._attached_process()
        if process.poll() is not None:
            return
        with suppress(OSError, ProcessLookupError):
            process.terminate()
        if wait_for_exit(process, TERMINATION_TIMEOUT):
            return
        with suppress(OSError, ProcessLookupError):
            process.kill()
        if wait_for_exit(process, TERMINATION_TIMEOUT):
            return
        raise OSError(
            "The contained child process remained alive after forced termination."
        )


class _PosixProcessOwner(_ProcessOwnerBase):
    """Own a verified process group and same-root detached descendants."""

    def __init__(
        self,
        launch_environment: Mapping[str, str],
        *,
        owner_token: str | None,
        group_token: str,
    ) -> None:
        super().__init__(launch_environment)
        self._owner_token = owner_token
        self._group_token = group_token

    def terminate(self) -> None:
        process = self._attached_process()
        group_error: OSError | None = None
        try:
            self._terminate_process_group(process)
        except OSError as error:
            group_error = error
        try:
            self._terminate_detached_processes()
        except OSError as error:
            if group_error is not None:
                raise error from group_error
            raise
        if group_error is not None:
            raise group_error

    def owns_process_group(self, group: int) -> bool:
        """Return whether one stable live group snapshot carries this nonce."""
        try:
            import psutil
        except ImportError as error:
            raise OSError(
                "Process group verification requires the installed psutil runtime."
            ) from error
        owner = os.getuid() if hasattr(os, "getuid") else None
        for _attempt in range(3):
            processes = _live_process_group_members(psutil, group)
            if processes is None or not processes:
                return False
            matches = [
                _process_matches_token(
                    psutil,
                    process,
                    owner=owner,
                    variable=_PROCESS_GROUP_OWNER_ENV,
                    token=self._group_token,
                )
                for process in processes
            ]
            refreshed = _live_process_group_members(psutil, group)
            if refreshed is None:
                return False
            if tuple(process.pid for process in processes) == tuple(
                process.pid for process in refreshed
            ):
                return all(match is True for match in matches)
        return False

    def _terminate_process_group(self, process: subprocess.Popen[bytes]) -> None:
        if not self._signal_process_group(process, signal.SIGTERM):
            return
        if _wait_for_process_group_exit(process, TERMINATION_TIMEOUT):
            return
        if not self._signal_process_group(process, _FORCED_SIGNAL):
            return
        if not _wait_for_process_group_exit(
            process,
            TERMINATION_TIMEOUT,
        ) and self.owns_process_group(process.pid):
            raise OSError(
                "The owned process group remained alive after forced termination."
            )

    def _signal_process_group(
        self,
        process: subprocess.Popen[bytes],
        requested_signal: signal.Signals,
    ) -> bool:
        if _KILL_PROCESS_GROUP is None or not self.owns_process_group(process.pid):
            return False
        try:
            _KILL_PROCESS_GROUP(process.pid, requested_signal)
        except ProcessLookupError:
            return False
        except OSError as error:
            if _process_group_disappeared(process):
                return False
            if _wait_for_process_group_exit(process, TERMINATION_TIMEOUT):
                return False
            if not self.owns_process_group(process.pid):
                return False
            raise error
        return True

    def _terminate_detached_processes(self) -> None:
        if self._owner_token is None:
            return
        try:
            import psutil
        except ImportError as error:
            raise OSError(
                "Detached process cleanup requires the installed psutil runtime."
            ) from error
        for requested_signal in ("terminate", "kill"):
            processes = self._matching_detached_processes(psutil)
            if not processes:
                return
            for process in processes:
                with suppress(psutil.Error):
                    getattr(process, requested_signal)()
            _gone, alive = psutil.wait_procs(processes, timeout=TERMINATION_TIMEOUT)
            if not alive and not self._matching_detached_processes(psutil):
                return
        remaining = self._matching_detached_processes(psutil)
        if remaining:
            raise OSError(
                "Owned detached processes remained alive after forced termination: "
                + ", ".join(str(process.pid) for process in remaining)
            )

    def _matching_detached_processes(self, psutil: Any) -> list[Any]:
        owner = os.getuid() if hasattr(os, "getuid") else None
        matches = []
        for process in psutil.process_iter(("pid", "uids")):
            match = _process_matches_token(
                psutil,
                process,
                owner=owner,
                variable=_PROCESS_OWNER_ENV,
                token=self._owner_token,
            )
            if match:
                matches.append(process)
        return matches


class _WindowsProcessOwner(_ProcessOwnerBase):
    """Own a Windows job with taskkill fallback during partial setup."""

    def __init__(self, launch_environment: Mapping[str, str]) -> None:
        super().__init__(launch_environment)
        self._job: Any | None = None

    def attach(self, process: subprocess.Popen[bytes]) -> None:
        super().attach(process)
        from marimo_studio._processes.windows import WindowsJob

        self._job = WindowsJob.create_for_process(process.pid)

    def terminate(self) -> None:
        process = self._attached_process()
        if self._job is None:
            _terminate_windows_process_tree(process)
            return
        try:
            self._job.terminate()
        except OSError as error:
            with suppress(OSError, ProcessLookupError):
                process.kill()
            if not wait_for_exit(process, TERMINATION_TIMEOUT):
                raise OSError(
                    "The owned process remained alive after a "
                    "Windows job termination failure."
                ) from error
            raise
        if wait_for_exit(process, TERMINATION_TIMEOUT):
            return
        with suppress(OSError, ProcessLookupError):
            process.kill()
        if wait_for_exit(process, TERMINATION_TIMEOUT):
            return
        raise OSError("The owned process remained alive after Windows job termination.")

    def close(self) -> None:
        if self._job is not None:
            self._job.close()


def _inherited_environment(
    environment: Mapping[str, str] | None,
) -> dict[str, str]:
    selected = os.environ.copy() if environment is None else dict(environment)
    for variable in (_PROCESS_OWNER_ENV, _PROCESS_GROUP_OWNER_ENV):
        inherited = os.environ.get(variable)
        if inherited is not None:
            selected[variable] = inherited
        else:
            selected.pop(variable, None)
    return selected


def _root_environment(
    environment: Mapping[str, str] | None,
) -> dict[str, str]:
    selected = _inherited_environment(environment)
    if _PROCESS_OWNER_ENV not in selected:
        selected[_PROCESS_OWNER_ENV] = secrets.token_urlsafe(24)
    return selected


def _windows_environment(
    environment: Mapping[str, str] | None,
) -> dict[str, str]:
    selected = _root_environment(environment)
    selected.pop(_PROCESS_GROUP_OWNER_ENV, None)
    return selected


def _owned_environment(
    environment: Mapping[str, str] | None,
) -> tuple[dict[str, str], str | None, str]:
    selected = _root_environment(environment)
    inherited_owner = os.environ.get(_PROCESS_OWNER_ENV)
    group_token = secrets.token_urlsafe(24)
    selected[_PROCESS_GROUP_OWNER_ENV] = group_token
    owner_token = selected[_PROCESS_OWNER_ENV] if inherited_owner is None else None
    return selected, owner_token, group_token


def _process_matches_token(
    psutil: Any,
    process: Any,
    *,
    owner: int | None,
    variable: str,
    token: str | None,
) -> bool | None:
    try:
        uids = process.info.get("uids")
        if owner is not None and (uids is None or uids.real != owner):
            return False
        return process.environ().get(variable) == token
    except SystemError as error:
        if not isinstance(error.__cause__, PermissionError):
            raise
        return None
    except (
        PermissionError,
        psutil.AccessDenied,
        psutil.NoSuchProcess,
        psutil.ZombieProcess,
    ):
        return None


def _live_process_group_members(psutil: Any, group: int) -> list[Any] | None:
    members = []
    for process in psutil.process_iter(("pid", "status", "uids")):
        try:
            if process.info.get("status") == psutil.STATUS_ZOMBIE:
                continue
            if os.getpgid(process.pid) == group:
                members.append(process)
        except (ProcessLookupError, psutil.NoSuchProcess, psutil.ZombieProcess):
            continue
        except (PermissionError, psutil.AccessDenied):
            return None
    return sorted(members, key=lambda process: process.pid)


def _process_group_disappeared(process: subprocess.Popen[bytes]) -> bool:
    if _KILL_PROCESS_GROUP is None:
        return True
    try:
        _KILL_PROCESS_GROUP(process.pid, 0)
    except ProcessLookupError:
        return True
    except PermissionError:
        return _process_group_has_live_members(process.pid) is False
    except OSError:
        return False
    return _process_group_has_live_members(process.pid) is False


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
            timeout=TERMINATION_TIMEOUT,
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
            if _process_group_has_live_members(process.pid) is False:
                return True
        else:
            if _process_group_has_live_members(process.pid) is False:
                return True
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        time.sleep(min(0.01, remaining))


def _terminate_windows_process_tree(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    break_signal = getattr(signal, "CTRL_BREAK_EVENT", None)
    if break_signal is not None:
        with suppress(OSError, ProcessLookupError):
            process.send_signal(break_signal)
        if wait_for_exit(process, TERMINATION_TIMEOUT):
            return
    with suppress(OSError, subprocess.TimeoutExpired):
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            check=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=TERMINATION_TIMEOUT,
        )
    if wait_for_exit(process, TERMINATION_TIMEOUT):
        return
    with suppress(OSError, ProcessLookupError):
        process.kill()
    if wait_for_exit(process, TERMINATION_TIMEOUT):
        return
    raise OSError(
        "The owned process remained alive after taskkill and forced termination."
    )
