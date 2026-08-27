"""Protect the shared Python and browser runtime configuration contract."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from marimo_studio._delivery.runtime_config import (
    RuntimeConfigInputs,
    runtime_projection_revision,
)
from marimo_studio._projections.resolution import projection_policy

_FIXTURE = (
    Path(__file__).resolve().parents[4]
    / "packages"
    / "protocol"
    / "fixtures"
    / "runtime-config.json"
)

pytestmark = pytest.mark.supported_python


def test_runtime_config_matches_the_browser_protocol_fixture() -> None:
    inputs = RuntimeConfigInputs(
        view="dashboard",
        views=("dashboard", "executive"),
        runtime_id="server",
        runtime_instance="server-instance",
        runtime_data={"url": "/proxy/app/"},
        root_url="/proxy/app/",
        public_root_url="/proxy/app/",
        document_root_url="/proxy/app/",
        support_url="/proxy/app/_marimo-studio/views/dashboard",
        projection_revision="a" * 64,
        show_cell_logs=True,
        projection_targets={
            "cells": {
                "result": {
                    "status": "ready",
                    "producer": "cell:v1:result",
                    "dependencyClosure": ["cell:v1:result"],
                }
            },
            "variables": {},
        },
        mounts=(
            {
                "id": "site:result",
                "kind": "cell",
                "source": {
                    "path": "src/index.html",
                    "line": 12,
                    "column": 5,
                },
                "allowedTargets": ["result"],
            },
        ),
        projection_policy=projection_policy(),
        runtime_cell_refs={"cell:v1:result": "runtime-result"},
        diagnostics=(
            {
                "code": "cell-not-found",
                "severity": "error",
                "message": "Cell 'summary' is unavailable.",
                "hint": "Restore the cell or update the view.",
                "view": "dashboard",
                "projection": "cell",
                "target": "summary",
                "source": {
                    "path": "src/index.html",
                    "line": 18,
                    "column": 7,
                },
            },
        ),
        app_config={"width": "medium"},
        user_config={"theme": "system"},
        config_overrides={},
        dev=True,
        mode="edit",
    )

    expected = json.loads(_FIXTURE.read_text(encoding="utf-8"))

    assert inputs.to_dict(revision="presentation-revision") == expected


def test_projection_revision_tracks_its_runtime_contract() -> None:
    mounts: tuple[dict[str, object], ...] = (
        {
            "id": "site:result",
            "kind": "cell",
            "source": {"path": "index.html", "line": 1, "column": 1},
            "allowedTargets": ["result"],
        },
    )
    targets = {
        "cells": {
            "result": {
                "status": "ready",
                "producer": "cell:v1:result",
                "dependencyClosure": ["cell:v1:result"],
            }
        },
        "variables": {},
    }
    policy = projection_policy()

    def revision(
        *,
        source_revision: str = "source-a",
        runtime_id: str = "server",
        runtime_instance: str = "runtime-a",
        selected_mounts: tuple[dict[str, object], ...] = mounts,
        runtime_cell_refs: dict[str, str] | None = None,
        diagnostics: tuple[dict[str, object], ...] = (),
    ) -> str:
        return runtime_projection_revision(
            source_revision=source_revision,
            view="dashboard",
            runtime_id=runtime_id,
            runtime_instance=runtime_instance,
            mounts=selected_mounts,
            projection_targets=targets,
            projection_policy=policy,
            runtime_cell_refs=(
                runtime_cell_refs
                if runtime_cell_refs is not None
                else {"cell:v1:result": "runtime-result"}
            ),
            diagnostics=diagnostics,
        )

    baseline = revision()

    assert len(baseline) == 64
    assert revision() == baseline
    assert revision(source_revision="source-b") != baseline
    assert revision(runtime_id="wasm") != baseline
    assert revision(runtime_instance="runtime-b") != baseline
    assert revision(runtime_cell_refs={"cell:v1:result": "runtime-rebound"}) != baseline
    diagnostic: dict[str, object] = {
        "code": "projection-target-missing",
        "severity": "error",
        "message": "The projection target is unavailable.",
        "hint": "Restore the target.",
        "view": "dashboard",
        "projection": "cell",
        "target": "result",
        "source": {"path": "index.html", "line": 1, "column": 1},
    }
    assert revision(diagnostics=(diagnostic,)) != baseline
    assert revision(diagnostics=(diagnostic,)) == revision(
        diagnostics=(
            {
                **diagnostic,
                "source": {"path": "index.html", "line": 12, "column": 8},
            },
        )
    )
    assert (
        revision(
            selected_mounts=(
                {
                    **mounts[0],
                    "source": {"path": "index.html", "line": 8, "column": 5},
                },
            )
        )
        == baseline
    )
    assert (
        revision(
            selected_mounts=(
                {
                    **mounts[0],
                    "allowedTargets": ["summary"],
                },
            )
        )
        != baseline
    )
