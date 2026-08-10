from __future__ import annotations

import asyncio

import pytest

import marimo_studio.analysis as analysis_module
from marimo_studio._runtime_process import check_runtime_studio_isolated
from marimo_studio._workspace import load_studio
from marimo_studio.analysis import analyze_studio
from marimo_studio.errors import ProtocolError
from marimo_studio.types import BrowserObservation, CheckResult
from marimo_studio.workspace import ensure_view


def test_runtime_analysis_runs_in_a_dedicated_process(notebook_path) -> None:
    ensure_view(notebook_path)
    studio = load_studio(notebook_path)

    checks = asyncio.run(check_runtime_studio_isolated(studio, view_name="dashboard"))

    assert not [check for check in checks if check.status == "fail"]
    assert (notebook_path.parent / "cell-executed").read_text() == "executed"


def test_analysis_skips_runtime_and_builds_repair_actions(
    notebook_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ensure_view(notebook_path)
    studio = load_studio(notebook_path)
    runtime_called = False

    monkeypatch.setattr(
        analysis_module,
        "check_studio",
        lambda *_args, **_kwargs: (
            CheckResult(
                "view:dashboard:value:missing",
                "fail",
                "missing is unavailable",
                code="missing-variable",
                details={
                    "view": "dashboard",
                    "target": "missing",
                    "hint": "Restore missing in the notebook.",
                },
            ),
        ),
    )

    async def runtime(*_args, **_kwargs):
        nonlocal runtime_called
        runtime_called = True
        return ()

    monkeypatch.setattr(analysis_module, "check_runtime_studio", runtime)
    report = asyncio.run(analyze_studio(studio, require_browser=False))

    assert not runtime_called
    assert report.ok is False
    assert report.handoff_ready is False
    assert report.runtime_skipped is not None
    assert report.actions[0].to_dict() == {
        "stage": "static",
        "severity": "error",
        "code": "missing-variable",
        "message": "missing is unavailable",
        "advice": "Restore missing in the notebook.",
        "view": "dashboard",
        "target": "missing",
    }


def test_required_browser_evidence_controls_handoff_readiness(
    notebook_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ensure_view(notebook_path)
    studio = load_studio(notebook_path)
    monkeypatch.setattr(
        analysis_module,
        "check_studio",
        lambda *_args, **_kwargs: (CheckResult("static", "pass", "ready"),),
    )

    async def runtime(*_args, **_kwargs):
        return (CheckResult("runtime", "pass", "ready"),)

    async def observe(_studio, views):
        return tuple(
            BrowserObservation(
                view=view,
                runtime="server",
                revision="revision-1",
                state="ready",
            )
            for view in views
        )

    monkeypatch.setattr(analysis_module, "check_runtime_studio", runtime)
    observed = asyncio.run(
        analyze_studio(
            studio,
            observe_browser=observe,
            require_browser=True,
        )
    )
    unobserved = asyncio.run(analyze_studio(studio, require_browser=True))

    assert observed.ok is True
    assert observed.handoff_ready is True
    assert unobserved.ok is True
    assert unobserved.handoff_ready is False
    assert unobserved.actions[0].code == "browser-not-observed"
    assert unobserved.to_dict()["summary"] == {
        "pass": 2,
        "warn": 0,
        "fail": 1,
    }


def test_browser_connection_errors_become_repair_actions(
    notebook_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ensure_view(notebook_path)
    studio = load_studio(notebook_path)
    monkeypatch.setattr(
        analysis_module,
        "check_studio",
        lambda *_args, **_kwargs: (CheckResult("static", "pass", "ready"),),
    )

    async def runtime(*_args, **_kwargs):
        return (CheckResult("runtime", "pass", "ready"),)

    async def observe(_studio, _views):
        raise ProtocolError("The running Studio server is unavailable.")

    monkeypatch.setattr(analysis_module, "check_runtime_studio", runtime)
    report = asyncio.run(
        analyze_studio(
            studio,
            observe_browser=observe,
            require_browser=True,
        )
    )

    assert report.handoff_ready is False
    assert report.browser_observations[0].message == (
        "The running Studio server is unavailable."
    )
    assert report.actions[0].code == "browser-not-observed"
