"""Protect the supervised boundary for public notebook inspection."""

from __future__ import annotations

import asyncio
import hashlib
import json
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

import marimo_studio._notebook.runtime_process as runtime_process
import marimo_studio._processes.async_command as async_command
import marimo_studio._processes.isolated_module as isolated_module
from marimo_studio._notebook.source_generation import (
    capture_notebook_source_generation,
)
from marimo_studio._processes.supervisor import ProcessCleanupError
from marimo_studio._projections.runtime_records import (
    OutputRenderResult,
    RuntimeProbe,
    ValueReadResult,
)
from marimo_studio.errors import ConfigurationError, ProtocolError, RuntimeTimeoutError


def _empty_response() -> bytes:
    runtime = RuntimeProbe(
        cells={},
        values=ValueReadResult(values={}, errors={}),
        outputs=OutputRenderResult(outputs={}, errors={}),
    )
    return json.dumps(
        {"schema": 1, "runtime": runtime.to_dict()},
        separators=(",", ":"),
    ).encode()


def test_isolated_probe_uses_the_runtime_process_budget(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class Supervisor:
        def run(self, command: list[str], timeout: float):
            captured["command"] = command
            captured["timeout"] = timeout
            captured["request"] = json.loads(Path(command[-2]).read_bytes())
            Path(command[-1]).write_bytes(_empty_response())
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
    result = asyncio.run(
        runtime_process.probe_runtime_isolated(
            tmp_path / "analysis.py",
            cell_ids=("cell",),
            variables=("value",),
            output_selector_groups=(("output",),),
            show_tracebacks=True,
            timeout=42,
            value_max_bytes=1024,
        )
    )

    assert result.values.values == {}
    assert captured["timeout"] == 52
    assert captured["request"] == {
        "schema": 1,
        "notebook": str(tmp_path / "analysis.py"),
        "cellIds": ["cell"],
        "variables": ["value"],
        "outputSelectorGroups": [["output"]],
        "showTracebacks": True,
        "timeout": 42,
        "valueMaxBytes": 1024,
        "sourceGeneration": None,
    }


@pytest.mark.parametrize(
    "timeout",
    (-1, float("nan"), 301, 10**400),
)
def test_isolated_probe_rejects_an_invalid_timeout(
    tmp_path: Path,
    timeout: float | int,
) -> None:
    with pytest.raises(ValueError, match="finite number between 0 and 300"):
        asyncio.run(
            runtime_process.probe_runtime_isolated(
                tmp_path / "analysis.py",
                cell_ids=(),
                variables=(),
                output_selector_groups=(),
                show_tracebacks=False,
                timeout=timeout,
            )
        )


@pytest.mark.parametrize("value_max_bytes", (0, 1_000_001))
def test_isolated_probe_rejects_an_invalid_value_budget(
    tmp_path: Path,
    value_max_bytes: int,
) -> None:
    with pytest.raises(ValueError, match="integer between 1 and 1000000"):
        asyncio.run(
            runtime_process.probe_runtime_isolated(
                tmp_path / "analysis.py",
                cell_ids=(),
                variables=(),
                output_selector_groups=(),
                show_tracebacks=False,
                value_max_bytes=value_max_bytes,
            )
        )


def test_isolated_probe_rejects_an_oversized_request(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="request exceeds 262144 bytes"):
        asyncio.run(
            runtime_process.probe_runtime_isolated(
                tmp_path / "analysis.py",
                cell_ids=(),
                variables=("x" * 262_144,),
                output_selector_groups=(),
                show_tracebacks=False,
            )
        )


def test_isolated_probe_enforces_the_process_request_budget(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        runtime_process,
        "encode_runtime_request",
        lambda *_args, **_kwargs: b"x" * 2_000_001,
    )

    with pytest.raises(
        ProtocolError,
        match="Process request exceeds 2000000 bytes",
    ):
        asyncio.run(
            runtime_process.probe_runtime_isolated(
                tmp_path / "analysis.py",
                cell_ids=(),
                variables=(),
                output_selector_groups=(),
                show_tracebacks=False,
            )
        )


def test_isolated_probe_runs_request_files_outside_the_event_loop(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    event_loop_thread = threading.get_ident()
    worker_threads: list[int] = []
    heartbeat = 0
    prepare = isolated_module._prepare_request_workspace
    read = isolated_module.read_process_response
    remove = isolated_module._remove_request_workspace

    def record(operation):
        def invoke(*args, **kwargs):
            worker_threads.append(threading.get_ident())
            return operation(*args, **kwargs)

        return invoke

    class Supervisor:
        def run(self, command: list[str], _timeout: float):
            Path(command[-1]).write_bytes(_empty_response())
            return SimpleNamespace(
                timed_out=False,
                output_too_large=False,
                returncode=0,
                stdout=b"",
                stderr=b"",
            )

        def cancel(self) -> None:
            return

    monkeypatch.setattr(isolated_module, "_prepare_request_workspace", record(prepare))
    monkeypatch.setattr(isolated_module, "read_process_response", record(read))
    monkeypatch.setattr(isolated_module, "_remove_request_workspace", record(remove))
    monkeypatch.setattr(async_command, "ProcessSupervisor", Supervisor)

    async def exercise() -> None:
        nonlocal heartbeat

        async def beat() -> None:
            nonlocal heartbeat
            while True:
                heartbeat += 1
                await asyncio.sleep(0)

        beating = asyncio.create_task(beat())
        try:
            await runtime_process.probe_runtime_isolated(
                tmp_path / "analysis.py",
                cell_ids=(),
                variables=(),
                output_selector_groups=(),
                show_tracebacks=False,
            )
        finally:
            beating.cancel()
            with pytest.raises(asyncio.CancelledError):
                await beating

    asyncio.run(exercise())

    assert heartbeat > 0
    assert len(worker_threads) == 3
    assert all(thread != event_loop_thread for thread in worker_threads)


def test_isolated_probe_maps_the_process_deadline_to_the_runtime_budget(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_paths: tuple[Path, Path] | None = None

    class Supervisor:
        def run(self, command: list[str], _timeout: float):
            nonlocal captured_paths
            captured_paths = (Path(command[-2]), Path(command[-1]))
            return SimpleNamespace(
                timed_out=True,
                output_too_large=False,
                returncode=-1,
                stdout=b"",
                stderr=b"",
            )

        def cancel(self) -> None:
            return

    monkeypatch.setattr(async_command, "ProcessSupervisor", Supervisor)
    with pytest.raises(
        RuntimeTimeoutError,
        match="inspection exceeded 3 seconds",
    ):
        asyncio.run(
            runtime_process.probe_runtime_isolated(
                tmp_path / "analysis.py",
                cell_ids=(),
                variables=(),
                output_selector_groups=(),
                show_tracebacks=False,
                timeout=3,
            )
        )
    assert captured_paths is not None
    assert all(not path.exists() for path in captured_paths)


@pytest.mark.parametrize(
    ("response", "message"),
    (
        (None, "response could not be read"),
        (b"{", "returned invalid JSON"),
        (b"x" * 2_000_001, "response exceeds 2000000 bytes"),
    ),
    ids=("missing", "malformed", "oversized"),
)
def test_isolated_probe_rejects_invalid_process_responses(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    response: bytes | None,
    message: str,
) -> None:
    class Supervisor:
        def run(self, command: list[str], _timeout: float):
            if response is not None:
                Path(command[-1]).write_bytes(response)
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

    with pytest.raises(ProtocolError, match=message):
        asyncio.run(
            runtime_process.probe_runtime_isolated(
                tmp_path / "analysis.py",
                cell_ids=(),
                variables=(),
                output_selector_groups=(),
                show_tracebacks=False,
            )
        )


def test_isolated_probe_does_not_expose_worker_stderr(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Supervisor:
        def run(self, _command: list[str], _timeout: float):
            return SimpleNamespace(
                timed_out=False,
                output_too_large=False,
                returncode=7,
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
    with pytest.raises(ProtocolError) as raised:
        asyncio.run(
            runtime_process.probe_runtime_isolated(
                tmp_path / "analysis.py",
                cell_ids=(),
                variables=(),
                output_selector_groups=(),
                show_tracebacks=False,
            )
        )

    assert str(raised.value) == "Isolated notebook runtime exited with status 7"


def test_isolated_probe_rejects_a_changed_source_generation(
    notebook_path: Path,
) -> None:
    source = notebook_path.read_bytes()
    generation = capture_notebook_source_generation(
        notebook_path,
        hashlib.sha256(source).hexdigest(),
    )
    notebook_path.write_bytes(source + b"\n# changed\n")
    try:
        with pytest.raises(ConfigurationError, match="changed during inspection"):
            asyncio.run(
                runtime_process.probe_runtime_isolated(
                    notebook_path,
                    cell_ids=(),
                    variables=(),
                    output_selector_groups=(),
                    show_tracebacks=False,
                    source_generation=generation,
                )
            )
    finally:
        notebook_path.write_bytes(source)


def test_cancelled_probe_surfaces_process_tree_cleanup_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = threading.Event()
    cancelled = threading.Event()

    class Supervisor:
        def run(self, _command: list[str], _timeout: float):
            started.set()
            assert cancelled.wait(timeout=2)
            raise ProcessCleanupError("runtime process tree survived")

        def cancel(self) -> None:
            cancelled.set()

    monkeypatch.setattr(async_command, "ProcessSupervisor", Supervisor)

    async def exercise() -> None:
        task = asyncio.create_task(
            runtime_process.probe_runtime_isolated(
                tmp_path / "analysis.py",
                cell_ids=(),
                variables=(),
                output_selector_groups=(),
                show_tracebacks=False,
            )
        )
        assert await asyncio.to_thread(started.wait, 1)
        task.cancel()
        with pytest.raises(
            ProcessCleanupError,
            match="runtime process tree survived",
        ):
            await task

    asyncio.run(exercise())
