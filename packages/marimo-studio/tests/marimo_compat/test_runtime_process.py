"""Protect one isolated runtime validation process."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import signal
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

import marimo_studio._processes.async_command as async_command
import marimo_studio._processes.supervisor as process_supervisor
import marimo_studio._validation.runtime_process as runtime_process
from marimo_studio._workspace.models import StudioWorkspace


def test_isolated_runtime_budget_contains_the_notebook_probe(
    tmp_path,
    monkeypatch,
) -> None:
    captured: dict[str, object] = {}

    class Supervisor:
        def run(self, command, timeout):
            captured["timeout"] = timeout
            captured["command"] = tuple(command)
            captured["request"] = json.loads(Path(command[-2]).read_bytes())
            Path(command[-1]).write_bytes(b'{"schema":1,"checks":[]}')
            return SimpleNamespace(
                timed_out=False,
                output_too_large=False,
                returncode=0,
                stdout=b"not protocol data",
                stderr=b"",
            )

        def cancel(self) -> None:
            return

    monkeypatch.setattr(async_command, "ProcessSupervisor", Supervisor)
    studio = cast(
        StudioWorkspace,
        SimpleNamespace(notebook=tmp_path / "analysis.py"),
    )

    checks = asyncio.run(
        runtime_process.check_runtime_studio_isolated(studio, timeout=42)
    )

    assert checks == ()
    assert captured["timeout"] == 52
    command = captured["command"]
    assert isinstance(command, tuple)
    assert len(command) == 5
    assert command[:3] == (
        command[0],
        "-m",
        "marimo_studio._validation.runtime_process",
    )
    assert not Path(command[-2]).exists()
    assert not Path(command[-1]).exists()
    request_payload = captured["request"]
    assert isinstance(request_payload, dict)
    assert request_payload == {
        "schema": 1,
        "notebook": str(tmp_path / "analysis.py"),
        "view": None,
        "expectedRevisions": None,
        "timeout": 42,
    }


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
            marks=(
                pytest.mark.supported_python,
                pytest.mark.skipif(os.name == "posix", reason="Windows process status"),
            ),
        ),
        pytest.param(
            3221225477,
            "exited with status 0xC0000005",
            marks=(
                pytest.mark.supported_python,
                pytest.mark.skipif(os.name == "posix", reason="Windows process status"),
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
                stderr=(
                    b"Authorization: Bearer sk-release-secret\n"
                    b"OPENAI_API_KEY=sk-another-secret\n"
                    b"https://user:password@example.test/"
                ),
            )

        def cancel(self) -> None:
            return

    monkeypatch.setattr(async_command, "ProcessSupervisor", Supervisor)
    studio = cast(
        StudioWorkspace,
        SimpleNamespace(notebook=tmp_path / "analysis.py"),
    )

    checks = asyncio.run(runtime_process.check_runtime_studio_isolated(studio))

    assert len(checks) == 1
    assert checks[0].status == "fail"
    assert message in checks[0].message
    assert "sk-release-secret" not in checks[0].message
    assert "sk-another-secret" not in checks[0].message
    assert "password" not in checks[0].message


def test_isolated_runtime_reports_cleanup_failures(
    tmp_path,
    monkeypatch,
) -> None:
    class Supervisor:
        def run(self, _command, _timeout):
            raise process_supervisor.ProcessCleanupError("permission denied")

        def cancel(self) -> None:
            return

    monkeypatch.setattr(async_command, "ProcessSupervisor", Supervisor)
    studio = cast(
        StudioWorkspace,
        SimpleNamespace(notebook=tmp_path / "analysis.py"),
    )

    checks = asyncio.run(runtime_process.check_runtime_studio_isolated(studio))

    assert checks[0].code == "runtime-cleanup-failed"
    assert "cleanup failed" in checks[0].message


@pytest.mark.parametrize(
    ("response", "message"),
    (
        (None, "response is unavailable"),
        (b"{", "returned invalid JSON"),
        (b"x" * 2_000_001, "response is unavailable"),
    ),
    ids=("missing", "malformed", "oversized"),
)
def test_isolated_runtime_rejects_invalid_process_responses(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    response: bytes | None,
    message: str,
) -> None:
    captured_paths: tuple[Path, Path] | None = None

    class Supervisor:
        def run(self, command, _timeout):
            nonlocal captured_paths
            captured_paths = (Path(command[-2]), Path(command[-1]))
            if response is not None:
                captured_paths[1].write_bytes(response)
            return SimpleNamespace(
                timed_out=False,
                output_too_large=False,
                returncode=0,
                stdout=b"",
                stderr=b"",
            )

        def cancel(self) -> None:
            return

    monkeypatch.setattr(async_command, "ProcessSupervisor", Supervisor)
    studio = cast(
        StudioWorkspace,
        SimpleNamespace(notebook=tmp_path / "analysis.py"),
    )

    checks = asyncio.run(runtime_process.check_runtime_studio_isolated(studio))

    assert checks[0].status == "fail"
    assert message in checks[0].message
    assert captured_paths is not None
    assert all(not path.exists() for path in captured_paths)


def test_repeatedly_cancelled_runtime_waits_for_process_cleanup(
    tmp_path,
    monkeypatch,
) -> None:
    started = threading.Event()
    cancelled = threading.Event()
    release = threading.Event()
    finished = threading.Event()
    captured_paths: tuple[Path, Path] | None = None

    class Supervisor:
        def run(self, _command, _timeout):
            nonlocal captured_paths
            captured_paths = (Path(_command[-2]), Path(_command[-1]))
            started.set()
            try:
                assert cancelled.wait(timeout=2)
                assert release.wait(timeout=2)
                Path(_command[-1]).write_bytes(b'{"schema":1,"checks":[]}')
                return SimpleNamespace(
                    timed_out=False,
                    output_too_large=False,
                    returncode=0,
                    stdout=b"not protocol data",
                    stderr=b"",
                )
            finally:
                finished.set()

        def cancel(self) -> None:
            cancelled.set()

    monkeypatch.setattr(async_command, "ProcessSupervisor", Supervisor)
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
    assert captured_paths is not None
    assert all(not path.exists() for path in captured_paths)


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

    monkeypatch.setattr(async_command, "ProcessSupervisor", Supervisor)
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


def test_validation_worker_rejects_an_aba_startup_revision(
    notebook_path: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import marimo_studio._validation.static as static_validation
    from marimo_studio._views.revisions import capture_source_revisions
    from marimo_studio._workspace import load_studio

    from ..app_helpers import configured

    studio = configured(notebook_path)
    expected = capture_source_revisions(studio, ("dashboard",))
    source = notebook_path.read_text(encoding="utf-8")
    notebook_path.write_text(source + "\n# transient generation\n", encoding="utf-8")
    response = tmp_path / "response.json"
    request = tmp_path / "request.json"

    async def fail_runtime(*_args: object, **_kwargs: object) -> tuple[()]:
        raise AssertionError("A stale worker reached notebook execution")

    monkeypatch.setattr(static_validation, "check_runtime_studio", fail_runtime)
    from marimo_studio._validation.runtime_protocol import (
        encode_runtime_validation_request,
    )

    request.write_bytes(
        encode_runtime_validation_request(
            notebook_path,
            "dashboard",
            expected,
            1,
        )
    )
    try:
        assert runtime_process._run_worker(request, response) == 0
    finally:
        notebook_path.write_text(source, encoding="utf-8")

    payload = json.loads(response.read_bytes())
    assert payload["checks"][0]["code"] == "validation-source-changed"
    restored = capture_source_revisions(
        load_studio(notebook_path),
        ("dashboard",),
    )
    assert restored != expected


def test_validation_worker_rejects_a_malformed_request() -> None:
    from marimo_studio._processes.limits import runtime_process_timeout

    result, response = asyncio.run(
        runtime_process._run_runtime_worker(
            b"{",
            runtime_process_timeout(1),
        )
    )

    assert result.returncode != 0
    assert response == b""


@pytest.mark.native_process
@pytest.mark.supported_python
def test_native_validation_worker_launches_with_many_maximum_view_names(
    notebook_path: Path,
) -> None:
    from marimo_studio._processes.limits import runtime_process_timeout
    from marimo_studio._validation.runtime_protocol import (
        encode_runtime_validation_request,
    )

    from ..app_helpers import configured

    configured(notebook_path)
    revisions = {
        f"{index:04x}" + "v" * 236: hashlib.sha256(str(index).encode()).hexdigest()
        for index in range(1_000)
    }
    request = encode_runtime_validation_request(
        notebook_path,
        None,
        revisions,
        5,
    )

    result, response = asyncio.run(
        runtime_process._run_runtime_worker(
            request,
            runtime_process_timeout(5),
        )
    )

    assert result.returncode == 0
    assert not result.timed_out
    assert json.loads(response)["checks"][0]["code"] == "validation-source-changed"
