from __future__ import annotations

import asyncio
import json
from pathlib import Path

from marimo_studio._artifacts.paths import artifact_root
from marimo_studio._views.inspect import inspect_view
from marimo_studio._views.inspection import (
    inspect_view_project_sync,
    view_project_state,
)

from ..app_helpers import configured


def test_source_revert_restores_freshness_without_erasing_the_failed_attempt(
    notebook_path: Path,
) -> None:
    studio = configured(notebook_path)
    project = studio.view("dashboard")
    receipt_path = artifact_root(project) / "development.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    published_duration = receipt["published"]["duration_ms"]
    attempt_duration = published_duration + 100
    receipt["published"]["diagnostics"] = [
        {
            "code": "published-warning",
            "severity": "warning",
            "message": "The published artifact retained a warning.",
            "hint": "Review the published page.",
            "source": None,
        }
    ]
    failed_revision = "sha256:" + "f" * 64
    receipt["build"].update(
        phase="failed",
        project_revision=failed_revision,
        diagnostics=[
            {
                "code": "later-build-failed",
                "severity": "error",
                "message": "A later build attempt failed.",
                "hint": "Repair the source and build again.",
                "source": None,
            }
        ],
        duration_ms=attempt_duration,
    )
    receipt_path.write_text(
        json.dumps(receipt, sort_keys=True) + "\n", encoding="utf-8"
    )

    inspected = asyncio.run(inspect_view(studio, "dashboard"))
    state = view_project_state(project, inspect_view_project_sync(project))

    retained = json.loads(receipt_path.read_text(encoding="utf-8"))

    assert inspected.freshness == "current"
    assert inspected.build is not None
    assert state.artifact is not None
    assert [item.code for item in inspected.build.issues] == ["published-warning"]
    assert inspected.build.revision == state.artifact.artifact_revision
    assert retained["build"]["phase"] == "failed"
    assert retained["build"]["project_revision"] == failed_revision
    assert retained["published"]["duration_ms"] == published_duration
    assert state.build.phase == "failed"
    assert state.build.project_revision == failed_revision
