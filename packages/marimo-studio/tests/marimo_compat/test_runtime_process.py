"""Protect one isolated runtime validation process."""

from __future__ import annotations

import asyncio
import os
import signal
import threading
from types import SimpleNamespace
from typing import cast

import pytest

import marimo_studio._processes.supervisor as process_supervisor
import marimo_studio._validation.runtime_process as runtime_process
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
    assert captured["timeout"] == 52


@pytest.mark.parametrize(
    ("returncode", "message"),
    (
        (7, "exited with status 7"),
        pytest.param(
            -int(signal.SIGTERM),
            "was terminated by signal SIGTERM",
            marks=pytest.mark.skipif(os.name != "posix", reason="POSIX signal status"),
        ),
        pytest.param(
            -1073741819,
            "exited with status 0xC0000005",
            marks=pytest.mark.skipif(
                os.name == "posix", reason="Windows process status"
            ),
        ),
    ),
)
def test_isolated_runtime_converts_supervised_process_crashes(
    tmp_path,
    monkeypatch,
    returncode: int,
    message: str,
) -> None:
    class Supervisor:
        def run(self, _command, _timeout):
            return SimpleNamespace(
                timed_out=False,
                output_too_large=False,
                returncode=returncode,
                stdout=b"",
                stderr=b"worker crashed",
            )

        def cancel(self) -> None:
            return

    monkeypatch.setattr(runtime_process, "ProcessSupervisor", Supervisor)
    studio = cast(
        StudioWorkspace,
        SimpleNamespace(notebook=tmp_path / "analysis.py"),
    )

    checks = asyncio.run(runtime_process.check_runtime_studio_isolated(studio))

    assert len(checks) == 1
    assert checks[0].status == "fail"
    assert message in checks[0].message
    assert "worker crashed" in checks[0].message


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


def test_repeatedly_cancelled_runtime_waits_for_process_cleanup(
    tmp_path,
    monkeypatch,
) -> None:
    started = threading.Event()
    cancelled = threading.Event()
    release = threading.Event()
    finished = threading.Event()

    class Supervisor:
        def run(self, _command, _timeout):
            started.set()
            try:
                assert cancelled.wait(timeout=2)
                assert release.wait(timeout=2)
                return SimpleNamespace(
                    timed_out=False,
                    output_too_large=False,
                    returncode=0,
                    stdout=b'{"schema":1,"checks":[]}',
                    stderr=b"",
                )
            finally:
                finished.set()

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
        assert await asyncio.to_thread(cancelled.wait, 1)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert finished.is_set()

    try:
        asyncio.run(exercise())
    finally:
        release.set()


def test_cancelled_runtime_surfaces_process_cleanup_failure(
    tmp_path,
    monkeypatch,
) -> None:
    started = threading.Event()
    cancelled = threading.Event()

    class Supervisor:
        def run(self, _command, _timeout):
            started.set()
            assert cancelled.wait(timeout=2)
            raise process_supervisor.ProcessCleanupError(
                "runtime process tree survived"
            )

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
        with pytest.raises(
            process_supervisor.ProcessCleanupError,
            match="runtime process tree survived",
        ):
            await task

    asyncio.run(exercise())
