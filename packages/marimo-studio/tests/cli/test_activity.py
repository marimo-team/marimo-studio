from __future__ import annotations

import json
import os
import sys
from io import StringIO
from pathlib import Path
from threading import Event, Thread, current_thread
from typing import TextIO

import pytest
from marimo_export.progress import CacheActivity, ProgressEvent

from marimo_studio._cli.activity import activity
from marimo_studio._cli.diagnostics import DiagnosticStream
from marimo_studio._cli.environment import _live_diagnostics, _run_command
from marimo_studio._delivery.progress import StaticExportProgress


def test_environment_progress_reaches_parent_before_child_completes(
    tmp_path: Path,
) -> None:
    release = tmp_path / "release"
    received: list[str] = []

    def relay(source: TextIO) -> None:
        received.extend(source.readlines())
        release.touch()

    script = """
import os, sys, time
from pathlib import Path
with open(os.environ['MARIMO_STUDIO_DIAGNOSTIC_CHANNEL'], 'w') as output:
    output.write('progress\\n')
    output.flush()
deadline = time.monotonic() + 5
while not Path(sys.argv[1]).exists():
    if time.monotonic() > deadline:
        sys.exit(7)
    time.sleep(0.01)
Path(os.environ['MARIMO_STUDIO_RESULT_CHANNEL']).write_text('{"ok":true}')
"""
    result = _run_command(
        [sys.executable, "-c", script, str(release)],
        dict(os.environ),
        True,
        relay,
        None,
    )
    assert result.returncode == 0
    assert result.result == '{"ok":true}'
    assert received == ["progress\n"]


def test_heartbeat_reports_last_observed_state_and_stops_on_exit() -> None:
    observed = Event()

    class Output(StringIO):
        def write(self, value: str) -> int:
            written = super().write(value)
            if '"heartbeat"' in value:
                observed.set()
            return written

    output = Output()
    stream = DiagnosticStream(
        format="jsonl", command="view export", diagnostic_stream=output
    )
    with activity(stream, phase="prepare", view="report", interval=0.01) as progress:
        progress(
            StaticExportProgress.from_export(
                ProgressEvent(
                    kind="state_started",
                    state="reviewed",
                    cache=CacheActivity(authored_hits=2),
                ),
                view="report",
                runtime="zero-python",
            )
        )
        assert observed.wait(2), "heartbeat did not arrive during active preparation"
    events = [json.loads(line) for line in output.getvalue().splitlines()]
    heartbeat = next(item for item in events if item.get("code") == "heartbeat")
    assert heartbeat["details"]["state"] == "reviewed"
    assert heartbeat["details"]["cache"]["authored_hits"] == 2
    assert heartbeat["details"]["cell"] is None
    assert heartbeat["details"]["elapsed_seconds"] >= 0


def test_operation_failure_stops_the_heartbeat_before_propagating() -> None:
    observed = Event()
    workers: list[Thread] = []

    class Output(StringIO):
        def write(self, value: str) -> int:
            written = super().write(value)
            if '"heartbeat"' in value:
                workers.append(current_thread())
                observed.set()
            return written

    failure = RuntimeError("operation failed")
    stream = DiagnosticStream(format="jsonl", diagnostic_stream=Output())
    with (
        pytest.raises(RuntimeError) as raised,
        activity(stream, phase="prepare", view="report", interval=0.01),
    ):
        assert observed.wait(2), "heartbeat did not start"
        raise failure

    assert raised.value is failure
    assert workers and all(not worker.is_alive() for worker in workers)


def test_diagnostic_relay_failure_is_propagated_after_worker_exit(
    tmp_path: Path,
) -> None:
    channel = tmp_path / "diagnostics"
    channel.write_text("progress\n")
    observed = Event()
    workers: list[Thread] = []
    failure = OSError("diagnostic destination closed")

    def relay(source: TextIO) -> None:
        assert source.read() == "progress\n"
        workers.append(current_thread())
        observed.set()
        raise failure

    with pytest.raises(OSError) as raised, _live_diagnostics(channel, relay):
        assert observed.wait(2), "relay did not receive the diagnostic"

    assert raised.value is failure
    assert workers and all(not worker.is_alive() for worker in workers)
