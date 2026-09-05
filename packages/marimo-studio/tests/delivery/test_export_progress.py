from __future__ import annotations

from typing import cast

import pytest
from marimo_export.progress import ProgressEvent

from marimo_studio._delivery.portability import StaticRuntime
from marimo_studio._delivery.progress import (
    StaticExportProgress,
    StaticExportStep,
)


def test_export_progress_preserves_the_marimo_export_event() -> None:
    progress = StaticExportProgress.from_export(
        ProgressEvent(
            "state_finished",
            completed=2,
            total=3,
            state="reviewed",
            elapsed_seconds=0.25,
            message="prepared",
        ),
        view="dashboard",
        runtime="zero-python",
    )

    assert progress.to_dict() == {
        "view": "dashboard",
        "runtime": "zero-python",
        "source": "marimo-export",
        "event": {
            "kind": "state_finished",
            "completed": 2,
            "total": 3,
            "state": "reviewed",
            "cache": None,
            "elapsed_seconds": 0.25,
            "message": "prepared",
        },
    }
    assert progress.format_message() == (
        "State finished: reviewed (2/3) | 0.250s | prepared"
    )


def test_export_progress_serializes_a_studio_owned_step() -> None:
    progress = StaticExportProgress.from_step(
        "preflight_finished",
        view="dashboard",
        runtime="wasm",
        completed=3,
        total=3,
        elapsed_seconds=0.1,
        message="0 diagnostics",
    )

    assert progress.to_dict() == {
        "view": "dashboard",
        "runtime": "wasm",
        "source": "marimo-studio",
        "event": {
            "kind": "preflight_finished",
            "completed": 3,
            "total": 3,
            "elapsed_seconds": 0.1,
            "message": "0 diagnostics",
        },
    }


def test_export_progress_rejects_invalid_studio_identity() -> None:
    event = ProgressEvent("inspection_started")

    with pytest.raises(ValueError, match="view"):
        StaticExportProgress("", "wasm", event)
    with pytest.raises(ValueError, match="runtime"):
        StaticExportProgress("dashboard", cast(StaticRuntime, "server"), event)


def test_static_export_step_rejects_invalid_counts() -> None:
    with pytest.raises(ValueError, match="cannot exceed"):
        StaticExportStep("bundle_finished", completed=2, total=1)
