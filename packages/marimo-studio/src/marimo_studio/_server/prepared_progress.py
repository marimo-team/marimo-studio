"""Translate export notifications into runtime preparation progress."""

from __future__ import annotations

from marimo_export.progress import ProgressEvent

from marimo_studio._server.runtime.progress import RuntimeProgress, RuntimeProgressSink


class PreparedProgress:
    def __init__(self, sink: RuntimeProgressSink) -> None:
        self._sink = sink

    def __call__(self, event: ProgressEvent) -> None:
        completed, total = event.completed, event.total
        if event.kind == "inspection_started":
            message = "Inspecting notebook states"
        elif event.kind == "plan_ready":
            message = "Preparing notebook states"
            if total is not None and completed == total:
                message = "Checking cached notebook states"
            completed, total = None, None
        elif event.kind in {"state_started", "state_finished"}:
            message = "Capturing notebook states"
            if total is not None and completed == total:
                message = "Finalizing prepared notebook states"
                completed, total = None, None
        elif event.kind == "prepared_reused":
            message = "Reusing prepared notebook states"
            completed, total = None, None
        elif event.kind == "prepared_committed":
            message = "Notebook states prepared"
            completed, total = None, None
        else:
            return
        if total is None or total <= 0 or completed is None:
            completed, total = None, None
        self._sink(
            RuntimeProgress(
                message=(event.message or message)[:2048],
                completed=completed,
                total=total,
            )
        )
