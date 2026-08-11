from __future__ import annotations

import asyncio
import os
import signal
import subprocess
import sys
import threading
import time
from types import SimpleNamespace
from typing import cast

import pytest

import marimo_studio._process_supervisor as process_supervisor
import marimo_studio._runtime_process as runtime_process
from marimo_studio._runtime_limits import runtime_process_timeout
from marimo_studio._runtime_process import _returncode_message
from marimo_studio._workspace.models import StudioWorkspace


def test_isolated_runtime_budget_contains_the_notebook_probe(
    tmp_path,
    monkeypatch,
) -> None:
    captured: dict[str, float] = {}

    class Supervisor:
        def run(self, _command, timeout):
            captured["timeout"] = timeout
            return SimpleNamespace(
                timed_out=False,
                output_too_large=False,
                returncode=0,
                stdout=b'{"schema":1,"checks":[]}',
                stderr=b"",
            )

        def cancel(self) -> None:
            return

    monkeypatch.setattr(runtime_process, "ProcessSupervisor", Supervisor)
    studio = cast(
        StudioWorkspace,
        SimpleNamespace(notebook=tmp_path / "analysis.py"),
    )

    checks = asyncio.run(
        runtime_process.check_runtime_studio_isolated(studio, timeout=42)
    )

    assert checks == ()
    assert captured["timeout"] == runtime_process_timeout(42)


def test_runtime_exit_messages_follow_the_host_process_model() -> None:
    assert _returncode_message(-int(signal.SIGTERM), platform="posix") == (
        "was terminated by signal SIGTERM"
    )


def test_isolated_runtime_reports_cleanup_failures(
    tmp_path,
    monkeypatch,
) -> None:
    class Supervisor:
        def run(self, _command, _timeout):
            raise process_supervisor.ProcessCleanupError("permission denied")

        def cancel(self) -> None:
            return

    monkeypatch.setattr(runtime_process, "ProcessSupervisor", Supervisor)
    studio = cast(
        StudioWorkspace,
        SimpleNamespace(notebook=tmp_path / "analysis.py"),
    )

    checks = asyncio.run(runtime_process.check_runtime_studio_isolated(studio))

    assert checks[0].code == "runtime-cleanup-failed"
    assert "cleanup failed" in checks[0].message
    assert _returncode_message(-1073741819, platform="nt") == (
        "exited with status 0xC0000005"
    )


def test_cancelled_runtime_preserves_cleanup_failure_as_its_cause(
    tmp_path,
    monkeypatch,
) -> None:
    started = threading.Event()
    cancelled = threading.Event()

    class Supervisor:
        def run(self, _command, _timeout):
            started.set()
            cancelled.wait(timeout=2)
            raise process_supervisor.ProcessCleanupError("group remained alive")

        def cancel(self) -> None:
            cancelled.set()

    monkeypatch.setattr(runtime_process, "ProcessSupervisor", Supervisor)
    studio = cast(
        StudioWorkspace,
        SimpleNamespace(notebook=tmp_path / "analysis.py"),
    )

    async def exercise() -> None:
        task = asyncio.create_task(
            runtime_process.check_runtime_studio_isolated(studio)
        )
        assert await asyncio.to_thread(started.wait, 1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError) as raised:
            await task
        assert isinstance(
            raised.value.__cause__,
            process_supervisor.ProcessCleanupError,
        )

    asyncio.run(exercise())


def test_process_supervisor_times_out_and_terminates_the_worker() -> None:
    supervisor = process_supervisor.ProcessSupervisor()

    result = supervisor.run(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        timeout=0.05,
    )

    assert result.timed_out
    assert result.returncode != 0


def test_process_supervisor_bounds_large_stderr() -> None:
    supervisor = process_supervisor.ProcessSupervisor()

    result = supervisor.run(
        [
            sys.executable,
            "-c",
            "import sys; sys.stderr.buffer.write(b'x' * 2_100_000)",
        ],
        timeout=5,
    )

    assert result.output_too_large
    assert len(result.stderr) == process_supervisor._MAX_ERROR_BYTES


def test_process_supervisor_bounds_one_large_stdout_write() -> None:
    supervisor = process_supervisor.ProcessSupervisor()

    result = supervisor.run(
        [
            sys.executable,
            "-c",
            "import os; os.write(1, b'x' * 20_000_000)",
        ],
        timeout=5,
    )

    assert result.output_too_large
    assert len(result.stdout) == process_supervisor._MAX_OUTPUT_BYTES


def test_process_supervisor_drains_output_after_worker_exit() -> None:
    supervisor = process_supervisor.ProcessSupervisor()

    result = supervisor.run(
        [
            sys.executable,
            "-c",
            "import os; os.write(1, b'x' * 1_000_000)",
        ],
        timeout=5,
    )

    assert result.returncode == 0
    assert not result.output_too_large
    assert result.stdout == b"x" * 1_000_000


def test_process_supervisor_cancellation_terminates_the_worker(
    monkeypatch,
) -> None:
    started = threading.Event()
    native_start = process_supervisor._start_process

    def start(*args, **kwargs):
        process = native_start(*args, **kwargs)
        started.set()
        return process

    monkeypatch.setattr(process_supervisor, "_start_process", start)
    supervisor = process_supervisor.ProcessSupervisor()
    results: list[process_supervisor.ProcessResult] = []
    worker = threading.Thread(
        target=lambda: results.append(
            supervisor.run(
                [sys.executable, "-c", "import time; time.sleep(60)"],
                timeout=60,
            )
        )
    )
    worker.start()
    assert started.wait(timeout=2)

    supervisor.cancel()
    worker.join(timeout=5)

    assert not worker.is_alive()
    assert results[0].returncode != 0


def test_process_supervisor_cancellation_does_not_block_asyncio(
    tmp_path,
) -> None:
    if os.name != "posix":
        return
    supervisor = process_supervisor.ProcessSupervisor()
    ready = tmp_path / "ready"
    ticks = 0
    stopped = False

    async def exercise() -> process_supervisor.ProcessResult:
        nonlocal ticks, stopped

        async def heartbeat() -> None:
            nonlocal ticks
            while not stopped:
                ticks += 1
                await asyncio.sleep(0.01)

        heartbeat_task = asyncio.create_task(heartbeat())
        worker = asyncio.create_task(
            asyncio.to_thread(
                supervisor.run,
                [
                    sys.executable,
                    "-c",
                    (
                        "import pathlib, signal, time; "
                        "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
                        f"pathlib.Path({str(ready)!r}).touch(); "
                        "time.sleep(30)"
                    ),
                ],
                60,
            )
        )
        while not ready.exists():
            await asyncio.sleep(0.01)
        started = time.monotonic()
        supervisor.cancel()
        assert time.monotonic() - started < 0.1
        result = await worker
        stopped = True
        await heartbeat_task
        return result

    result = asyncio.run(exercise())

    assert result.returncode != 0
    assert ticks >= 10


def test_process_supervisor_does_not_start_after_early_cancellation(
    monkeypatch,
) -> None:
    def fail_start(*_args, **_kwargs):
        raise AssertionError("cancelled supervisor started a process")

    monkeypatch.setattr(process_supervisor, "_start_process", fail_start)
    supervisor = process_supervisor.ProcessSupervisor()
    supervisor.cancel()

    result = supervisor.run([sys.executable, "-c", "pass"], timeout=1)

    assert result.returncode != 0


def test_process_supervisor_surfaces_process_group_signal_failures(
    monkeypatch,
) -> None:
    if os.name != "posix":
        return
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

    process_supervisor._signal_process_group(process, signal.SIGTERM)


def test_process_supervisor_cleans_descendants_after_the_worker_exits() -> None:
    supervisor = process_supervisor.ProcessSupervisor()
    child_pid = 0

    try:
        result = supervisor.run(
            [
                sys.executable,
                "-c",
                (
                    "import subprocess, sys; "
                    "child = subprocess.Popen([sys.executable, '-c', "
                    "'import time; time.sleep(30)']); "
                    "print(child.pid, flush=True)"
                ),
            ],
            timeout=5,
        )
        child_pid = int(result.stdout)
        deadline = time.monotonic() + 2
        while _process_exists(child_pid) and time.monotonic() < deadline:
            time.sleep(0.01)

        assert result.returncode == 0
        assert not _process_exists(child_pid)
    finally:
        if child_pid and _process_exists(child_pid):
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/PID", str(child_pid), "/F"],
                    check=False,
                    capture_output=True,
                )
            else:
                os.kill(child_pid, getattr(signal, "SIGKILL", signal.SIGTERM))


def test_process_supervisor_returns_when_detached_process_holds_pipe() -> None:
    if os.name != "posix":
        return
    supervisor = process_supervisor.ProcessSupervisor()
    child_pid = 0
    started = time.monotonic()

    try:
        result = supervisor.run(
            [
                sys.executable,
                "-c",
                (
                    "import subprocess, sys; "
                    "child = subprocess.Popen([sys.executable, '-c', "
                    "'import time; time.sleep(30)'], start_new_session=True); "
                    "print(child.pid, flush=True)"
                ),
            ],
            timeout=2,
        )
        child_pid = int(result.stdout)

        assert result.returncode == 0
        assert time.monotonic() - started < 1
    finally:
        if child_pid and _process_exists(child_pid):
            os.kill(child_pid, getattr(signal, "SIGKILL", signal.SIGTERM))


def _process_exists(pid: int) -> bool:
    if os.name == "nt":
        result = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
            check=False,
            capture_output=True,
            text=True,
        )
        return f'"{pid}"' in result.stdout
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True
