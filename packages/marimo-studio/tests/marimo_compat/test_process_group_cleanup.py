"""Protect platform process-group and job cleanup ownership."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from contextlib import suppress
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

import marimo_studio._processes.process_owner as process_owner
import marimo_studio._processes.supervisor as process_supervisor

pytestmark = pytest.mark.native_process

_POSIX_ONLY = pytest.mark.skipif(
    os.name != "posix",
    reason="POSIX process groups are required",
)


def _owned_group() -> process_owner._PosixProcessOwner:
    return process_owner._PosixProcessOwner(
        {},
        owner_token=None,
        group_token="group-owner",
    )


@pytest.mark.parametrize("owns_process_tree", (False, True))
@_POSIX_ONLY
def test_process_group_nonce_follows_the_new_session_boundary(
    monkeypatch: pytest.MonkeyPatch,
    owns_process_tree: bool,
) -> None:
    inherited = "parent-group-owner"
    monkeypatch.setenv(process_owner._PROCESS_OWNER_ENV, "root-owner")
    monkeypatch.setenv(process_owner._PROCESS_GROUP_OWNER_ENV, inherited)

    owner = process_owner.create_process_owner(
        None,
        owns_process_tree=owns_process_tree,
        platform="posix",
    )

    assert isinstance(
        owner,
        process_owner._PosixProcessOwner
        if owns_process_tree
        else process_owner._SingleProcessOwner,
    )
    if owns_process_tree:
        assert owner.launch_environment[process_owner._PROCESS_GROUP_OWNER_ENV] != (
            inherited
        )
    else:
        assert (
            owner.launch_environment[process_owner._PROCESS_GROUP_OWNER_ENV]
            == inherited
        )


@_POSIX_ONLY
def test_process_cleanup_does_not_signal_a_reused_foreign_group() -> None:
    victim = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    process = cast(
        subprocess.Popen[bytes],
        SimpleNamespace(
            pid=victim.pid,
            poll=lambda: 0,
            kill=lambda: pytest.fail("foreign leader reached direct cleanup"),
        ),
    )
    owner = process_owner._PosixProcessOwner(
        {},
        owner_token="not-the-victim-owner",
        group_token="not-the-victim-owner",
    )
    owner.attach(process)

    try:
        owner.terminate()

        assert victim.poll() is None
    finally:
        with suppress(ProcessLookupError):
            os.killpg(victim.pid, signal.SIGKILL)
        victim.wait(timeout=2)


@_POSIX_ONLY
def test_nested_no_tree_process_keeps_its_parent_group_ownership(
    tmp_path: Path,
) -> None:
    marker = tmp_path / "grandchild.pid"
    group_token = "parent-group-owner"
    grandchild = (
        "import os, pathlib, time; "
        f"pathlib.Path({str(marker)!r}).write_text(str(os.getpid())); "
        "time.sleep(30)"
    )
    child = (
        "import subprocess, sys; "
        "subprocess.Popen("
        f"[sys.executable, '-c', {grandchild!r}], "
        "stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, "
        "stderr=subprocess.DEVNULL)"
    )
    leader = (
        "import sys, time; "
        "from marimo_studio._processes.supervisor import ProcessSupervisor; "
        "ProcessSupervisor(owns_process_tree=False).run("
        f"[sys.executable, '-c', {child!r}], timeout=5); "
        "time.sleep(30)"
    )
    environment = {
        **os.environ,
        "_MARIMO_STUDIO_PROCESS_OWNER": "root-owner",
        "_MARIMO_STUDIO_PROCESS_GROUP_OWNER": group_token,
    }
    process = subprocess.Popen(
        [sys.executable, "-c", leader],
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    owner = process_owner._PosixProcessOwner(
        environment,
        owner_token=None,
        group_token=group_token,
    )
    owner.attach(process)

    try:
        deadline = time.monotonic() + 3
        while not marker.is_file() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert marker.is_file()

        owner.terminate()

        assert process.wait(timeout=2) != 0
        assert process_owner._process_group_has_live_members(process.pid) is False
    finally:
        with suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
        with suppress(subprocess.TimeoutExpired):
            process.wait(timeout=2)


@_POSIX_ONLY
def test_process_supervisor_surfaces_process_group_signal_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(process_owner, "TERMINATION_TIMEOUT", 0.2)
    started: list[subprocess.Popen[bytes]] = []
    native_start = process_supervisor._start_process

    def start(*args, **kwargs):
        process = native_start(*args, **kwargs)
        started.append(process)
        return process

    def fail_signal(_pid, _signal):
        raise PermissionError("signal denied")

    monkeypatch.setattr(process_supervisor, "_start_process", start)
    monkeypatch.setattr(process_owner, "_KILL_PROCESS_GROUP", fail_signal)

    with pytest.raises(
        process_supervisor.ProcessCleanupError,
        match="signal denied",
    ):
        process_supervisor.ProcessSupervisor().run(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            timeout=0.01,
        )

    assert started[0].poll() is not None


@_POSIX_ONLY
def test_process_group_cleanup_fails_when_forced_termination_leaves_owners(
    monkeypatch,
) -> None:
    signals: list[signal.Signals] = []
    owner = _owned_group()
    process = cast(
        subprocess.Popen[bytes],
        SimpleNamespace(pid=42),
    )
    owner.attach(process)
    monkeypatch.setattr(
        owner,
        "_signal_process_group",
        lambda _process, requested: signals.append(requested) or True,
    )
    monkeypatch.setattr(
        process_owner,
        "_wait_for_process_group_exit",
        lambda _process, _timeout: False,
    )
    monkeypatch.setattr(owner, "owns_process_group", lambda _group: True)

    with pytest.raises(OSError, match="remained alive"):
        owner._terminate_process_group(process)

    assert signals == [signal.SIGTERM, signal.SIGKILL]


@_POSIX_ONLY
def test_process_group_cleanup_rechecks_ownership_before_forced_signal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    signals: list[signal.Signals] = []
    ownership = iter((True, False))
    owner = _owned_group()
    process = cast(subprocess.Popen[bytes], SimpleNamespace(pid=42))
    monkeypatch.setattr(owner, "owns_process_group", lambda _group: next(ownership))
    monkeypatch.setattr(
        process_owner,
        "_KILL_PROCESS_GROUP",
        lambda _group, requested: signals.append(requested),
    )
    monkeypatch.setattr(
        process_owner,
        "_wait_for_process_group_exit",
        lambda _process, _timeout: False,
    )

    owner._terminate_process_group(process)

    assert signals == [signal.SIGTERM]


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
    owner = process_owner._WindowsProcessOwner({})
    owner._process = process
    owner._job = TreeOwner()
    monkeypatch.setattr(
        process_owner,
        "wait_for_exit",
        lambda _process, _timeout: False,
    )

    with pytest.raises(OSError, match="alive after Windows job termination"):
        owner.terminate()

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
    owner = process_owner._WindowsProcessOwner({})
    owner._process = process
    monkeypatch.setattr(process_owner.subprocess, "run", run)
    monkeypatch.setattr(
        process_owner,
        "wait_for_exit",
        lambda _process, _timeout: False,
    )

    with pytest.raises(OSError, match="alive after taskkill"):
        owner.terminate()

    assert taskkill_commands == [["taskkill", "/PID", "42", "/T", "/F"]]
    assert kills == 1


@_POSIX_ONLY
def test_process_group_signal_ignores_a_disappearing_darwin_group(
    monkeypatch,
) -> None:
    owner = _owned_group()
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
    monkeypatch.setattr(owner, "owns_process_group", lambda _group: True)
    monkeypatch.setattr(process_owner, "_KILL_PROCESS_GROUP", signal_group)
    monkeypatch.setattr(
        process_owner,
        "_process_group_has_live_members",
        lambda _group: None,
    )

    owner._signal_process_group(
        process,
        signal.SIGTERM,
    )


@_POSIX_ONLY
def test_process_group_signal_waits_for_an_exited_leader_group(
    monkeypatch,
) -> None:
    owner = _owned_group()
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
    monkeypatch.setattr(owner, "owns_process_group", lambda _group: True)
    monkeypatch.setattr(process_owner, "_KILL_PROCESS_GROUP", signal_group)
    monkeypatch.setattr(
        process_owner,
        "_process_group_has_live_members",
        lambda _group: None,
    )

    owner._signal_process_group(
        process,
        signal.SIGTERM,
    )

    assert probes == 2


@_POSIX_ONLY
def test_process_group_signal_surfaces_repeated_permission_denial(
    monkeypatch,
) -> None:
    owner = _owned_group()
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
    monkeypatch.setattr(owner, "owns_process_group", lambda _group: True)
    monkeypatch.setattr(process_owner, "_KILL_PROCESS_GROUP", fail_signal)
    monkeypatch.setattr(
        process_owner,
        "_process_group_has_live_members",
        lambda _group: True,
    )
    monotonic = iter((0.0, process_owner.TERMINATION_TIMEOUT + 1))
    monkeypatch.setattr(process_owner.time, "monotonic", lambda: next(monotonic))

    with pytest.raises(PermissionError, match="group access denied"):
        owner._signal_process_group(
            process,
            signal.SIGTERM,
        )

    assert leader_kills == 0


@_POSIX_ONLY
def test_process_group_signal_accepts_an_exited_zombie_group(
    monkeypatch,
) -> None:
    owner = _owned_group()

    def fail_signal(_pid, _requested_signal):
        raise PermissionError("zombie group")

    def fail_kill() -> None:
        raise AssertionError("a zombie-only group reached direct process cleanup")

    process = cast(
        subprocess.Popen[bytes],
        SimpleNamespace(pid=42, poll=lambda: 0, kill=fail_kill),
    )
    monkeypatch.setattr(owner, "owns_process_group", lambda _group: True)
    monkeypatch.setattr(process_owner, "_KILL_PROCESS_GROUP", fail_signal)
    monkeypatch.setattr(
        process_owner,
        "_process_group_has_live_members",
        lambda _group: False,
    )

    owner._signal_process_group(
        process,
        signal.SIGTERM,
    )
