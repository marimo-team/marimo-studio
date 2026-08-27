"""Protect process, pipe, descendant, and supervisor cleanup ownership."""

from __future__ import annotations

import asyncio
import os
import signal
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest

import marimo_studio._processes.supervisor as process_supervisor


def test_process_supervisor_times_out_and_terminates_the_worker() -> None:
    supervisor = process_supervisor.ProcessSupervisor()

    result = supervisor.run(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        timeout=0.05,
    )

    assert result.timed_out
    assert result.returncode != 0


def test_process_supervisor_bounds_stdout_and_stderr() -> None:
    cases = (
        (
            "stderr",
            "import sys; sys.stderr.buffer.write(b'x' * 2_100_000)",
            16_000,
        ),
        (
            "stdout",
            "import os; os.write(1, b'x' * 2_100_000)",
            2_000_000,
        ),
    )

    for stream, script, limit in cases:
        result = process_supervisor.ProcessSupervisor().run(
            [sys.executable, "-c", script],
            timeout=5,
        )

        assert result.output_too_large, stream
        assert len(getattr(result, stream)) == limit, stream


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
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if os.name != "posix":
        return
    monkeypatch.setattr(process_supervisor, "_TERMINATION_TIMEOUT", 0.2)
    supervisor = process_supervisor.ProcessSupervisor()
    ready = tmp_path / "ready"

    async def exercise() -> process_supervisor.ProcessResult:
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
        supervisor.cancel()
        heartbeat = asyncio.Event()
        asyncio.get_running_loop().call_soon(heartbeat.set)
        await heartbeat.wait()
        assert not worker.done()
        result = await worker
        return result

    result = asyncio.run(exercise())

    assert result.returncode != 0


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


def test_process_supervisor_cleans_up_when_exit_observer_setup_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process: subprocess.Popen[bytes] | None = None
    native_start = process_supervisor._start_process
    native_cleanup = process_supervisor._terminate_owned_processes
    cleanup_calls = 0

    def start(*args, **kwargs):
        nonlocal process
        process = native_start(*args, **kwargs)
        return process

    def cleanup(*args, **kwargs):
        nonlocal cleanup_calls
        cleanup_calls += 1
        return native_cleanup(*args, **kwargs)

    def fail_observer(_process: object) -> object:
        raise RuntimeError("observer setup failed")

    monkeypatch.setattr(process_supervisor, "_start_process", start)
    monkeypatch.setattr(process_supervisor, "_ProcessExitObserver", fail_observer)
    monkeypatch.setattr(process_supervisor, "_terminate_owned_processes", cleanup)

    with pytest.raises(RuntimeError, match="observer setup failed"):
        process_supervisor.ProcessSupervisor().run(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            timeout=30,
        )

    assert process is not None
    assert process.poll() is not None
    assert cleanup_calls == 1
    assert process.stdout is not None and process.stdout.closed
    assert process.stderr is not None and process.stderr.closed


def test_observer_setup_failure_terminates_a_fast_detached_descendant(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if os.name != "posix":
        return
    marker = tmp_path / "detached-child.pid"
    child_pid = 0

    def fail_observer(_process: object) -> object:
        deadline = time.monotonic() + 2
        while not marker.is_file() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert marker.is_file()
        raise RuntimeError("observer setup failed")

    monkeypatch.setattr(process_supervisor, "_ProcessExitObserver", fail_observer)
    try:
        with pytest.raises(RuntimeError, match="observer setup failed"):
            process_supervisor.ProcessSupervisor().run(
                [
                    sys.executable,
                    "-c",
                    (
                        "import pathlib, subprocess, sys, time; "
                        "child = subprocess.Popen([sys.executable, '-c', "
                        "'import time; time.sleep(30)'], start_new_session=True); "
                        f"pathlib.Path({str(marker)!r}).write_text(str(child.pid)); "
                        "time.sleep(30)"
                    ),
                ],
                timeout=30,
            )
        child_pid = int(marker.read_text(encoding="utf-8"))
        assert not _process_exists(child_pid)
    finally:
        if child_pid and _process_exists(child_pid):
            os.kill(child_pid, getattr(signal, "SIGKILL", signal.SIGTERM))


def test_process_supervisor_cleans_up_partially_started_readers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process: subprocess.Popen[bytes] | None = None
    native_process_start = process_supervisor._start_process
    native_thread_start = threading.Thread.start
    started_readers: list[threading.Thread] = []
    reader_starts = 0

    def start_process(*args, **kwargs):
        nonlocal process
        process = native_process_start(*args, **kwargs)
        return process

    def start_reader(reader: threading.Thread) -> None:
        nonlocal reader_starts
        reader_starts += 1
        if reader_starts == 2:
            raise RuntimeError("reader setup failed")
        native_thread_start(reader)
        started_readers.append(reader)

    monkeypatch.setattr(process_supervisor, "_start_process", start_process)
    monkeypatch.setattr(threading.Thread, "start", start_reader)

    with pytest.raises(RuntimeError, match="reader setup failed"):
        process_supervisor.ProcessSupervisor().run(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            timeout=30,
        )

    assert process is not None
    assert process.poll() is not None
    assert len(started_readers) == 1
    assert not started_readers[0].is_alive()
    assert process.stdout is not None and process.stdout.closed
    assert process.stderr is not None and process.stderr.closed


def test_process_supervisor_surfaces_cleanup_failure_over_setup_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process = SimpleNamespace(
        pid=42,
        returncode=None,
        stdout=None,
        stderr=None,
    )
    forced_returncode = -9

    def wait(*, timeout: float) -> int:
        if process.returncode is None:
            raise subprocess.TimeoutExpired("test", timeout)
        return process.returncode

    def kill() -> None:
        process.returncode = forced_returncode

    def fail_observer(_process: object) -> object:
        raise RuntimeError("observer setup failed")

    def fail_cleanup(_process: object, _owner: object) -> None:
        raise OSError("group cleanup failed")

    process.wait = wait
    process.kill = kill
    process.poll = lambda: process.returncode
    monkeypatch.setattr(
        process_supervisor, "_start_process", lambda *_args, **_kwargs: process
    )
    monkeypatch.setattr(process_supervisor, "_ProcessExitObserver", fail_observer)
    monkeypatch.setattr(process_supervisor, "_terminate_owned_processes", fail_cleanup)

    with pytest.raises(
        process_supervisor.ProcessCleanupError,
        match="group cleanup failed",
    ) as captured:
        process_supervisor.ProcessSupervisor().run(
            [sys.executable, "-c", "pass"],
            timeout=1,
        )

    assert isinstance(captured.value.__cause__, RuntimeError)
    assert str(captured.value.__cause__) == "observer setup failed"
    assert process.returncode == forced_returncode


def test_process_supervisor_fails_when_final_forced_termination_does_not_exit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    kills = 0
    process = SimpleNamespace(
        pid=42,
        returncode=None,
        stdout=None,
        stderr=None,
    )

    def kill() -> None:
        nonlocal kills
        kills += 1

    def fail_observer(_process: object) -> object:
        raise RuntimeError("observer setup failed")

    process.kill = kill
    process.poll = lambda: None
    monkeypatch.setattr(
        process_supervisor, "_start_process", lambda *_args, **_kwargs: process
    )
    monkeypatch.setattr(process_supervisor, "_ProcessExitObserver", fail_observer)
    monkeypatch.setattr(
        process_supervisor, "_terminate_owned_processes", lambda *_args: None
    )
    monkeypatch.setattr(
        process_supervisor,
        "_wait_for_exit",
        lambda _process, _timeout: False,
    )

    with pytest.raises(
        process_supervisor.ProcessCleanupError,
        match="alive after final forced termination",
    ) as captured:
        process_supervisor.ProcessSupervisor().run(
            [sys.executable, "-c", "pass"],
            timeout=1,
        )

    assert isinstance(captured.value.__cause__, RuntimeError)
    assert kills == 1


def test_process_supervisor_closes_every_owner_when_wait_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    kills = 0
    owner_closed = False
    observer_closed = False
    readers_finished = False
    process = SimpleNamespace(
        pid=42,
        returncode=None,
        stdout=None,
        stderr=None,
    )

    def wait(*, timeout: float) -> int:
        del timeout
        raise OSError("wait failed")

    def kill() -> None:
        nonlocal kills
        kills += 1

    class TreeOwner:
        def terminate(self) -> None:
            return

        def close(self) -> None:
            nonlocal owner_closed
            owner_closed = True

    class ExitObserver:
        @staticmethod
        def exited() -> bool:
            return True

        @staticmethod
        def close() -> None:
            nonlocal observer_closed
            observer_closed = True

    def finish_readers(*_args: object) -> None:
        nonlocal readers_finished
        readers_finished = True

    process.wait = wait
    process.kill = kill
    process.poll = lambda: None
    monkeypatch.setattr(
        process_supervisor, "_start_process", lambda *_args, **_kwargs: process
    )
    monkeypatch.setattr(
        process_supervisor, "_ProcessExitObserver", lambda _process: ExitObserver()
    )
    monkeypatch.setattr(
        process_supervisor, "_own_process_tree", lambda *_args: TreeOwner()
    )
    monkeypatch.setattr(process_supervisor, "_start_readers", lambda *_args: ())
    monkeypatch.setattr(process_supervisor, "_finish_readers", finish_readers)
    monkeypatch.setattr(
        process_supervisor, "_terminate_owned_processes", lambda *_args: None
    )

    with pytest.raises(
        process_supervisor.ProcessCleanupError,
        match="wait failed",
    ):
        process_supervisor.ProcessSupervisor().run(
            [sys.executable, "-c", "pass"],
            timeout=1,
        )

    assert kills == 1
    assert owner_closed
    assert readers_finished
    assert observer_closed


def test_process_supervisor_cleans_group_once_before_reaping_leader(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if os.name != "posix":
        return
    process = SimpleNamespace(
        pid=42,
        returncode=None,
        stdout=None,
        stderr=None,
        reaped=False,
    )
    cleanup_calls = 0

    def wait(*, timeout: float) -> int:
        del timeout
        process.reaped = True
        process.returncode = 0
        return 0

    def cleanup(_process: object, _owner: object) -> None:
        nonlocal cleanup_calls
        assert not process.reaped
        cleanup_calls += 1

    process.wait = wait

    class ExitObserver:
        @staticmethod
        def exited() -> bool:
            return True

        @staticmethod
        def close() -> None:
            return

    monkeypatch.setattr(
        process_supervisor, "_start_process", lambda *_args, **_kwargs: process
    )
    monkeypatch.setattr(
        process_supervisor, "_ProcessExitObserver", lambda _process: ExitObserver()
    )
    monkeypatch.setattr(process_supervisor, "_start_readers", lambda *_args: ())
    monkeypatch.setattr(process_supervisor, "_finish_readers", lambda *_args: None)
    monkeypatch.setattr(process_supervisor, "_own_process_tree", lambda *_args: None)
    monkeypatch.setattr(process_supervisor, "_terminate_owned_processes", cleanup)

    result = process_supervisor.ProcessSupervisor().run(
        [sys.executable, "-c", "pass"],
        timeout=1,
    )

    assert result.returncode == 0
    assert cleanup_calls == 1


def test_process_supervisor_terminates_detached_descendant_and_returns(
    tmp_path: Path,
) -> None:
    if os.name != "posix":
        return
    supervisor = process_supervisor.ProcessSupervisor()
    marker = tmp_path / "detached-child.pid"
    child_pid = 0
    executor = ThreadPoolExecutor(max_workers=1)

    try:
        future = executor.submit(
            supervisor.run,
            [
                sys.executable,
                "-c",
                (
                    "import pathlib, subprocess, sys; "
                    "child = subprocess.Popen([sys.executable, '-c', "
                    "'import time; time.sleep(30)'], start_new_session=True); "
                    f"pathlib.Path({str(marker)!r}).write_text(str(child.pid)); "
                    "print(child.pid, flush=True)"
                ),
            ],
            2,
        )
        result = future.result(timeout=5)
        child_pid = int(result.stdout)

        assert result.returncode == 0
        deadline = time.monotonic() + 2
        while _process_exists(child_pid) and time.monotonic() < deadline:
            time.sleep(0.01)
        assert not _process_exists(child_pid)
    finally:
        if not child_pid and marker.is_file():
            child_pid = int(marker.read_text(encoding="utf-8"))
        if child_pid and _process_exists(child_pid):
            os.kill(child_pid, getattr(signal, "SIGKILL", signal.SIGTERM))
        executor.shutdown(wait=True, cancel_futures=True)


@pytest.mark.parametrize("finish", ("cancel", "timeout"))
def test_process_supervisor_terminates_detached_process_on_early_finish(
    tmp_path: Path,
    finish: str,
) -> None:
    if os.name != "posix":
        return
    supervisor = process_supervisor.ProcessSupervisor()
    marker = tmp_path / "detached-child.pid"
    executor = ThreadPoolExecutor(max_workers=1)
    child_pid = 0
    try:
        future = executor.submit(
            supervisor.run,
            [
                sys.executable,
                "-c",
                (
                    "import pathlib, subprocess, sys, time; "
                    "child = subprocess.Popen([sys.executable, '-c', "
                    "'import time; time.sleep(30)'], start_new_session=True); "
                    f"pathlib.Path({str(marker)!r}).write_text(str(child.pid)); "
                    "time.sleep(30)"
                ),
            ],
            0.2 if finish == "timeout" else 30,
        )
        deadline = time.monotonic() + 2
        while not marker.is_file() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert marker.is_file()
        child_pid = int(marker.read_text(encoding="utf-8"))
        if finish == "cancel":
            supervisor.cancel()
        result = future.result(timeout=5)

        assert result.timed_out is (finish == "timeout")
        deadline = time.monotonic() + 2
        while _process_exists(child_pid) and time.monotonic() < deadline:
            time.sleep(0.01)
        assert not _process_exists(child_pid)
    finally:
        if child_pid and _process_exists(child_pid):
            os.kill(child_pid, getattr(signal, "SIGKILL", signal.SIGTERM))
        executor.shutdown(wait=True, cancel_futures=True)


def _process_exists(pid: int) -> bool:
    if os.name == "nt":
        result = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
            check=False,
            capture_output=True,
            text=True,
        )
        return f'"{pid}"' in result.stdout
    result = subprocess.run(
        ["ps", "-o", "stat=", "-p", str(pid)],
        check=False,
        capture_output=True,
        text=True,
    )
    state = result.stdout.strip()
    return bool(state) and not state.startswith("Z")
