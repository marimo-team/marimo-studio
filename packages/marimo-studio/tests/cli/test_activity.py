from __future__ import annotations

import json
import os
import sys
from io import StringIO
from pathlib import Path
from threading import Event
from typing import TextIO

from marimo_export.progress import CacheActivity, ProgressEvent

from marimo_studio._cli.activity import activity
from marimo_studio._cli.diagnostics import DiagnosticStream
from marimo_studio._cli.environment import _run_command
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
