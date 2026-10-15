"""Exercise public runtime inspection through owned native processes."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import marimo
import psutil
import pytest

from marimo_studio._notebook.inspection import inspect_runtime
from marimo_studio.errors import RuntimeTimeoutError

pytestmark = pytest.mark.native_process


def _hanging_notebook(notebook: Path, marker: Path) -> None:
    notebook.write_text(
        f'''\
import marimo

__generated_with = "{marimo.__version__}"
app = marimo.App()


@app.cell
def _():
    child = __import__("subprocess").Popen(
        [__import__("sys").executable, "-c", "import time; time.sleep(60)"]
    )
    _marker = __import__("pathlib").Path(r"{marker}.tmp")
    _marker.write_text(str(child.pid))
    _marker.replace(r"{marker}")
    while True:
        __import__("time").sleep(0.01)


if __name__ == "__main__":
    app.run()
''',
        encoding="utf-8",
    )


async def _notebook_child_pid(marker: Path, runtime: asyncio.Task[object]) -> int:
    """Wait until the running notebook records its child, or surface why it stopped."""

    async def wait() -> int:
        while not marker.is_file():
            if runtime.done():
                await runtime
                raise AssertionError(
                    "The runtime finished before the notebook child started."
                )
            await asyncio.sleep(0.01)
        return int(marker.read_text(encoding="utf-8"))

    return await asyncio.wait_for(wait(), timeout=60)


@pytest.mark.supported_python
def test_public_runtime_inspection_executes_in_a_child_process(
    tmp_path: Path,
) -> None:
    notebook = tmp_path / "process.py"
    notebook.write_text(
        f'''\
import marimo

__generated_with = "{marimo.__version__}"
app = marimo.App()


@app.cell
def _():
    __import__("os").write(1, b"not protocol data\\n")
    inspected_pid = __import__("os").getpid()
    spawned = __import__("subprocess").Popen(
        [__import__("sys").executable, "-c", "import time; time.sleep(60)"]
    )
    spawned_pid = spawned.pid
    return inspected_pid, spawned, spawned_pid


if __name__ == "__main__":
    app.run()
''',
        encoding="utf-8",
    )

    result = asyncio.run(inspect_runtime(notebook, selectors=(0,), runtime_timeout=10))

    assert result.runtime is not None
    assert result.runtime.values.values["inspected_pid"] != os.getpid()
    spawned_pid = result.runtime.values.values["spawned_pid"]
    assert isinstance(spawned_pid, int)
    assert not psutil.pid_exists(spawned_pid)


def test_runtime_timeout_removes_notebook_descendants(tmp_path: Path) -> None:
    notebook = tmp_path / "timeout.py"
    marker = tmp_path / "timeout-child"
    _hanging_notebook(notebook, marker)

    async def exercise() -> int:
        task = asyncio.create_task(
            inspect_runtime(notebook, selectors=(0,), runtime_timeout=15)
        )
        pid = await _notebook_child_pid(marker, task)
        with pytest.raises(RuntimeTimeoutError):
            await task
        return pid

    pid = asyncio.run(exercise())

    assert not psutil.pid_exists(pid)


def test_runtime_cancellation_removes_notebook_descendants(tmp_path: Path) -> None:
    notebook = tmp_path / "cancel.py"
    marker = tmp_path / "cancel-child"
    _hanging_notebook(notebook, marker)

    async def exercise() -> int:
        task = asyncio.create_task(
            inspect_runtime(notebook, selectors=(0,), runtime_timeout=60)
        )
        pid = await _notebook_child_pid(marker, task)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        return pid

    pid = asyncio.run(exercise())

    assert not psutil.pid_exists(pid)
