"""Keep long CLI operations observable between producer progress events."""

from __future__ import annotations

import sys
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from threading import Event, Lock, Thread
from typing import TYPE_CHECKING

from marimo_studio._delivery.progress import StaticExportProgress

if TYPE_CHECKING:
    from marimo_studio._cli.diagnostics import DiagnosticStream


@contextmanager
def activity(
    stream: DiagnosticStream,
    *,
    phase: str,
    view: str | None,
    interval: float = 5.0,
) -> Iterator[Callable[[StaticExportProgress], None]]:
    started = time.monotonic()
    stopped = Event()
    lock = Lock()
    failures: list[BaseException] = []
    current: dict[str, object] = {
        "view": view,
        "phase": phase,
        "state": None,
        "cache": None,
        "cell": None,
    }

    def progress(event: StaticExportProgress) -> None:
        with lock:
            record = event.event.to_dict()
            current["phase"] = record["kind"]
            for key in ("state", "cache"):
                if record.get(key) is not None:
                    current[key] = record[key]
            stream.emit_progress(event)

    def heartbeat() -> None:
        try:
            run_heartbeat()
        except BaseException as error:
            failures.append(error)

    def run_heartbeat() -> None:
        while not stopped.wait(interval):
            with lock:
                elapsed = time.monotonic() - started
                details = {**current, "elapsed_seconds": elapsed}
                message = (
                    f"{current['phase']} | state {current['state'] or 'unavailable'}"
                    f" | {elapsed:.1f}s | cache {current['cache'] or 'unavailable'}"
                    " | cell unavailable"
                )
                if not stream.emit(
                    code="heartbeat", severity="info", message=message, details=details
                ):
                    stream.write_activity(message)

    worker = Thread(target=heartbeat, name="studio-progress")
    worker.start()
    try:
        yield progress
    finally:
        stopped.set()
        worker.join()
        if failures and sys.exc_info()[0] is None:
            raise failures[0]
