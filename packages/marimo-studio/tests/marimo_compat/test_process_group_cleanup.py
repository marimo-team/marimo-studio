"""Protect platform process-group and job cleanup ownership."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
from types import SimpleNamespace
from typing import cast

import pytest

import marimo_studio._processes.supervisor as process_supervisor


def test_process_supervisor_surfaces_process_group_signal_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if os.name != "posix":
        return
    monkeypatch.setattr(process_supervisor, "_TERMINATION_TIMEOUT", 0.2)
    started: list[subprocess.Popen[bytes]] = []
    native_start = process_supervisor._start_process

    def start(*args, **kwargs):
        process = native_start(*args, **kwargs)
        started.append(process)
        return process

    def fail_signal(_pid, _signal):
        raise PermissionError("signal denied")

    monkeypatch.setattr(process_supervisor, "_start_process", start)
    monkeypatch.setattr(process_supervisor, "_KILL_PROCESS_GROUP", fail_signal)

    with pytest.raises(
        process_supervisor.ProcessCleanupError,
        match="signal denied",
    ):
        process_supervisor.ProcessSupervisor().run(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            timeout=0.01,
        )

    assert started[0].poll() is not None


def test_process_group_cleanup_fails_when_forced_termination_leaves_owners(
    monkeypatch,
) -> None:
    if os.name != "posix":
        return
    signals: list[signal.Signals] = []
    leader_kills = 0

    def kill() -> None:
        nonlocal leader_kills
        leader_kills += 1

    process = cast(
        subprocess.Popen[bytes],
        SimpleNamespace(pid=42, kill=kill),
    )
    monkeypatch.setattr(
        process_supervisor,
        "_signal_process_group",
        lambda _process, requested: signals.append(requested),
    )
    monkeypatch.setattr(
        process_supervisor,
        "_wait_for_process_group_exit",
        lambda _process, _timeout: False,
    )
    monkeypatch.setattr(
        process_supervisor,
        "_wait_for_exit",
        lambda _process, _timeout: False,
    )
    monkeypatch.setattr(
        process_supervisor,
        "_process_group_disappeared",
        lambda _process: False,
    )

    with pytest.raises(OSError, match="remained alive"):
        process_supervisor._terminate_owned_processes(process)

    assert signals == [signal.SIGTERM, process_supervisor._FORCED_SIGNAL]
    assert leader_kills == 1


def test_windows_job_cleanup_fails_when_the_process_survives(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    kills = 0
    terminations = 0

    def kill() -> None:
        nonlocal kills
        kills += 1

    class TreeOwner:
        def terminate(self) -> None:
            nonlocal terminations
            terminations += 1

        def close(self) -> None:
            return

    process = cast(
        subprocess.Popen[bytes],
        SimpleNamespace(pid=42, poll=lambda: None, kill=kill),
    )
    monkeypatch.setattr(
        process_supervisor,
        "_wait_for_exit",
        lambda _process, _timeout: False,
    )

    with pytest.raises(OSError, match="alive after Windows job termination"):
        process_supervisor._terminate_owned_processes(
            process,
            TreeOwner(),
            platform="nt",
        )

    assert terminations == 1
    assert kills == 1


def test_windows_taskkill_cleanup_fails_when_the_process_survives(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    kills = 0
    taskkill_commands: list[list[str]] = []

    def kill() -> None:
        nonlocal kills
        kills += 1

    def run(command: list[str], **_kwargs: object) -> object:
        taskkill_commands.append(command)
        return SimpleNamespace(returncode=1)

    process = cast(
        subprocess.Popen[bytes],
        SimpleNamespace(
            pid=42,
            poll=lambda: None,
            kill=kill,
            send_signal=lambda _signal: None,
        ),
    )
    monkeypatch.setattr(process_supervisor.subprocess, "run", run)
    monkeypatch.setattr(
        process_supervisor,
        "_wait_for_exit",
        lambda _process, _timeout: False,
    )

    with pytest.raises(OSError, match="alive after taskkill"):
        process_supervisor._terminate_owned_processes(process, platform="nt")

    assert taskkill_commands == [["taskkill", "/PID", "42", "/T", "/F"]]
    assert kills == 1


def test_process_group_signal_ignores_a_disappearing_darwin_group(
    monkeypatch,
) -> None:
    if os.name != "posix":
        return
    probes = iter(
        [
            PermissionError("group is exiting"),
            ProcessLookupError("group exited"),
        ]
    )

    def signal_group(_pid, requested_signal):
        if requested_signal == signal.SIGTERM:
            raise PermissionError("group is exiting")
        error = next(probes)
        raise error

    def fail_kill() -> None:
        raise AssertionError("an exited group reached direct process cleanup")

    process = cast(
        subprocess.Popen[bytes],
        SimpleNamespace(
            pid=42,
            poll=lambda: 0,
            kill=fail_kill,
        ),
    )
    monkeypatch.setattr(process_supervisor, "_KILL_PROCESS_GROUP", signal_group)
    monkeypatch.setattr(
        process_supervisor,
        "_process_group_has_live_members",
        lambda _group: None,
    )

    process_supervisor._signal_process_group(process, signal.SIGTERM)


def test_process_group_signal_waits_for_an_exited_leader_group(
    monkeypatch,
) -> None:
    if os.name != "posix":
        return
    probes = 0

    def signal_group(_pid, requested_signal):
        nonlocal probes
        if requested_signal == signal.SIGTERM:
            raise PermissionError("leader exited")
        probes += 1
        if probes > 1:
            raise ProcessLookupError("group exited")

    def fail_kill() -> None:
        raise AssertionError("an exiting group reached direct process cleanup")

    process = cast(
        subprocess.Popen[bytes],
        SimpleNamespace(
            pid=42,
            poll=lambda: 0,
            kill=fail_kill,
        ),
    )
    monkeypatch.setattr(process_supervisor, "_KILL_PROCESS_GROUP", signal_group)
    monkeypatch.setattr(
        process_supervisor,
        "_process_group_has_live_members",
        lambda _group: None,
    )

    process_supervisor._signal_process_group(process, signal.SIGTERM)

    assert probes == 2


def test_process_group_signal_surfaces_repeated_permission_denial(
    monkeypatch,
) -> None:
    if os.name != "posix":
        return
    leader_kills = 0

    def fail_signal(_pid, _requested_signal):
        raise PermissionError("group access denied")

    def kill() -> None:
        nonlocal leader_kills
        leader_kills += 1

    process = cast(
        subprocess.Popen[bytes],
        SimpleNamespace(pid=42, poll=lambda: 0, kill=kill, wait=lambda timeout: 0),
    )
    monkeypatch.setattr(process_supervisor, "_KILL_PROCESS_GROUP", fail_signal)
    monkeypatch.setattr(
        process_supervisor,
        "_process_group_has_live_members",
        lambda _group: True,
    )
    monotonic = iter((0.0, process_supervisor._TERMINATION_TIMEOUT + 1))
    monkeypatch.setattr(process_supervisor.time, "monotonic", lambda: next(monotonic))

    with pytest.raises(PermissionError, match="group access denied"):
        process_supervisor._signal_process_group(process, signal.SIGTERM)

    assert leader_kills == 1


def test_process_group_signal_accepts_an_exited_zombie_group(
    monkeypatch,
) -> None:
    if os.name != "posix":
        return

    def fail_signal(_pid, _requested_signal):
        raise PermissionError("zombie group")

    def fail_kill() -> None:
        raise AssertionError("a zombie-only group reached direct process cleanup")

    process = cast(
        subprocess.Popen[bytes],
        SimpleNamespace(pid=42, poll=lambda: 0, kill=fail_kill),
    )
    monkeypatch.setattr(process_supervisor, "_KILL_PROCESS_GROUP", fail_signal)
    monkeypatch.setattr(
        process_supervisor,
        "_process_group_has_live_members",
        lambda _group: False,
    )

    process_supervisor._signal_process_group(process, signal.SIGTERM)
