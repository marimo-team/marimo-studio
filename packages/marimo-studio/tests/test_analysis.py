from __future__ import annotations

import asyncio
from dataclasses import replace

import pytest

import marimo_studio.analysis as analysis_module
from marimo_studio._runtime_process import check_runtime_studio_isolated
from marimo_studio._workspace import load_studio
from marimo_studio._workspace.models import StudioWorkspace
from marimo_studio.agent_models import BrowserObservation
from marimo_studio.analysis import analyze_studio
from marimo_studio.errors import ProtocolError
from marimo_studio.types import CheckResult
from marimo_studio.workspace import ensure_view

from .helpers import ready_runtime_status


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
    report = asyncio.run(analyze_studio(studio, require_browser=True))

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
    assert len(report.actions) == 1


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

    async def observe(_studio, views, revisions):
        return tuple(
            BrowserObservation(
                view=view,
                runtime="server",
                revision=revisions[view],
                state="ready",
                client_id="browser-client-1234",
                runtime_instance="runtime-instance",
                session_id="s_123456",
                request_id=f"request-{view}",
                sequence=index,
                runtime_status=ready_runtime_status(view, revisions[view]),
            )
            for index, view in enumerate(views)
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
    missing_session = replace(
        observed,
        browser_observations=(
            replace(observed.browser_observations[0], session_id=None),
        ),
    )
    assert missing_session.handoff_ready is False
    assert unobserved.ok is False
    assert unobserved.handoff_ready is False
    assert unobserved.actions[0].code == "browser-not-requested"
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

    async def observe(_studio, _views, _revisions):
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
    assert report.actions[0].code == "protocol-error"


@pytest.mark.parametrize("failing_stage", ["runtime", "browser"])
def test_unexpected_stage_failure_cancels_sibling_analysis_work(
    notebook_path,
    monkeypatch: pytest.MonkeyPatch,
    failing_stage: str,
) -> None:
    ensure_view(notebook_path)
    studio = load_studio(notebook_path)
    monkeypatch.setattr(
        analysis_module,
        "check_studio",
        lambda *_args, **_kwargs: (CheckResult("static", "pass", "ready"),),
    )
    sibling_cancelled = False

    async def exercise() -> None:
        started = asyncio.Event()

        async def runtime(
            studio: StudioWorkspace,
            *,
            view_name: str | None = None,
            expected_revisions: dict[str, str] | None = None,
            timeout: float = 30,
        ) -> tuple[CheckResult, ...]:
            nonlocal sibling_cancelled
            del studio, view_name, expected_revisions, timeout
            if failing_stage == "runtime":
                await started.wait()
                raise RuntimeError("runtime failed")
            started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                sibling_cancelled = True
                raise
            raise AssertionError("runtime sibling unexpectedly finished")

        async def observe(
            _studio: StudioWorkspace,
            _views: tuple[str, ...],
            _revisions: dict[str, str],
        ) -> tuple[BrowserObservation, ...]:
            nonlocal sibling_cancelled
            if failing_stage == "browser":
                await started.wait()
                raise RuntimeError("browser failed")
            started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                sibling_cancelled = True
                raise
            raise AssertionError("browser sibling unexpectedly finished")

        with pytest.raises(RuntimeError, match=f"{failing_stage} failed"):
            await analyze_studio(
                studio,
                observe_browser=observe,
                require_browser=True,
                runtime_checker=runtime,
            )

    asyncio.run(exercise())

    assert sibling_cancelled


def test_analysis_rejects_evidence_collected_across_source_revisions(
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

    async def runtime(
        studio,
        *,
        view_name=None,
        expected_revisions=None,
        timeout=60,
    ):
        assert view_name is None
        assert timeout == 60
        assert expected_revisions is not None
        assert set(expected_revisions) == {"dashboard"}
        template = studio.views["dashboard"].template
        template.write_text(
            template.read_text(encoding="utf-8") + "\n<!-- newer -->\n",
            encoding="utf-8",
        )
        return (CheckResult("runtime", "pass", "ready"),)

    async def observe(_studio, views, revisions):
        return tuple(
            BrowserObservation(
                view=view,
                runtime="server",
                revision=revisions[view],
                state="ready",
                client_id="browser-client-1234",
                runtime_instance="runtime-instance",
                session_id="s_123456",
                request_id=f"request-{view}",
                sequence=index,
                runtime_status=ready_runtime_status(view, revisions[view]),
            )
            for index, view in enumerate(views)
        )

    report = asyncio.run(
        analyze_studio(
            studio,
            observe_browser=observe,
            require_browser=True,
            runtime_checker=runtime,
        )
    )

    assert not report.handoff_ready
    assert report.actions[-1].code == "analysis-source-changed"


def test_analysis_rejects_a_source_change_during_static_validation(
    notebook_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ensure_view(notebook_path)
    studio = load_studio(notebook_path)

    def static(*_args, **_kwargs):
        template = studio.views["dashboard"].template
        template.write_text(
            template.read_text(encoding="utf-8") + "\n<!-- newer -->\n",
            encoding="utf-8",
        )
        return (CheckResult("static", "pass", "ready"),)

    monkeypatch.setattr(analysis_module, "check_studio", static)
    report = asyncio.run(analyze_studio(studio, require_browser=True))

    assert not report.handoff_ready
    assert report.runtime_checks == ()
    assert {action.code for action in report.actions} == {"analysis-source-changed"}


def test_focused_analysis_ignores_an_unrelated_view_edit(
    notebook_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ensure_view(notebook_path)
    ensure_view(notebook_path, "executive")
    studio = load_studio(notebook_path)
    monkeypatch.setattr(
        analysis_module,
        "check_studio",
        lambda *_args, **_kwargs: (CheckResult("static", "pass", "ready"),),
    )

    async def runtime(*_args, **_kwargs):
        template = studio.views["executive"].template
        template.write_text(
            template.read_text(encoding="utf-8") + "\n<!-- edited -->\n",
            encoding="utf-8",
        )
        return (CheckResult("runtime", "pass", "ready"),)

    async def observe(_studio, views, revisions):
        return (
            BrowserObservation(
                view=views[0],
                runtime="server",
                revision=revisions[views[0]],
                state="ready",
                client_id="browser-client-1234",
                runtime_instance="runtime-instance",
                session_id="s_123456",
                request_id="request-dashboard",
                sequence=1,
                runtime_status=ready_runtime_status(
                    views[0],
                    revisions[views[0]],
                ),
            ),
        )

    report = asyncio.run(
        analyze_studio(
            studio,
            view_name="dashboard",
            observe_browser=observe,
            require_browser=True,
            runtime_checker=runtime,
        )
    )

    assert report.handoff_ready
    assert report.actions == ()


def test_selected_view_deletion_becomes_a_source_unavailable_action(
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
        studio.views["dashboard"].template.unlink()
        return (CheckResult("runtime", "pass", "ready"),)

    async def observe(_studio, views, revisions):
        return (
            BrowserObservation(
                view=views[0],
                runtime="server",
                revision=revisions[views[0]],
                state="ready",
                client_id="browser-client-1234",
                runtime_instance="runtime-instance",
                session_id="s_123456",
                request_id="request-dashboard",
                sequence=1,
                runtime_status=ready_runtime_status(
                    views[0],
                    revisions[views[0]],
                ),
            ),
        )

    report = asyncio.run(
        analyze_studio(
            studio,
            view_name="dashboard",
            observe_browser=observe,
            require_browser=True,
            runtime_checker=runtime,
        )
    )

    assert not report.handoff_ready
    assert report.actions[-1].code == "analysis-source-unavailable"
    assert report.actions[-1].source == {"path": str(studio.notebook)}
    assert "Restore the missing source" in report.actions[-1].advice


def test_missing_view_source_becomes_a_static_repair_action(notebook_path) -> None:
    ensure_view(notebook_path)
    studio = load_studio(notebook_path)
    studio.views["dashboard"].template.unlink()

    report = asyncio.run(analyze_studio(studio, view_name="dashboard"))

    assert not report.handoff_ready
    assert "analysis-source-unavailable" in {action.code for action in report.actions}
