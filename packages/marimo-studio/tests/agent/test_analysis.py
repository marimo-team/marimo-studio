from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path, PurePosixPath

import pytest

import marimo_studio._validation.analysis as analysis_module
import marimo_studio._validation.service as validation_service
from marimo_studio._validation.actions import validation_actions
from marimo_studio._validation.analysis import (
    AnalysisOptions,
    AnalysisRequest,
    analyze_studio,
)
from marimo_studio._validation.evidence import (
    AnalysisReport,
    BrowserDiagnostic,
    BrowserObservation,
)
from marimo_studio._validation.records import ValidationReport
from marimo_studio._validation.results import CheckResult
from marimo_studio._validation.runtime_process import check_runtime_studio_isolated
from marimo_studio._validation.static import CheckReport
from marimo_studio._views.api import prepare_view
from marimo_studio._views.presentation_publication import publish_presentation
from marimo_studio._workspace import load_studio
from marimo_studio._workspace.models import StudioWorkspace
from marimo_studio.errors import CapabilityInputError, ProtocolError
from marimo_studio.view_providers import (
    MountDeclaration,
    SourceLocation,
)

from ..async_test_support import wait_for_event
from ..helpers import ready_runtime_status


@pytest.mark.parametrize(
    ("field", "create", "value"),
    [
        (
            "browser_timeout",
            lambda value: AnalysisOptions(browser_timeout=value),
            10**1000,
        ),
        (
            "runtime_timeout",
            lambda value: AnalysisOptions(runtime_timeout=value),
            -(10**1000),
        ),
    ],
)
def test_analysis_options_reject_oversized_timeout_integers(
    field: str,
    create: Callable[[int], AnalysisOptions],
    value: int,
) -> None:
    with pytest.raises(CapabilityInputError) as raised:
        create(value)

    assert raised.value.code == "invalid-analysis-request"
    assert raised.value.field == field


def test_analysis_request_round_trips_its_versioned_record() -> None:
    request = AnalysisRequest(
        view="dashboard",
        browser_timeout=20,
        runtime_timeout=75,
        require_browser=False,
        browser_client="browser-client-1234",
    )

    assert AnalysisRequest.from_dict(request.to_dict()) == request
    assert request.to_dict()["schema"] == 1
    with pytest.raises(CapabilityInputError) as raised:
        AnalysisRequest.from_dict({})
    assert raised.value.field == "request"


def _check_report(
    studio: StudioWorkspace,
    *checks: CheckResult,
) -> CheckReport:
    return CheckReport(studio.notebook, None, checks)


def test_validation_levels_preserve_projection_repair_context(
    notebook_path: Path,
) -> None:
    source: dict[str, object] = {
        "path": "views/dashboard.tsx",
        "line": 7,
        "column": 3,
    }
    details = {
        "views": ["dashboard"],
        "target": "summary.total",
        "source": source,
        "hint": "Restore the projected summary value.",
    }
    check = CheckResult(
        "projection-summary",
        "fail",
        "Projected summary is unavailable",
        code="missing-variable",
        details=details,
    )
    static = ValidationReport.from_checks(
        CheckReport(notebook_path, None, (check,)),
        level="static",
    ).actions[0]
    runtime = ValidationReport.from_checks(
        CheckReport(notebook_path, None, ()),
        level="runtime",
        runtime=(check,),
    ).actions[0]
    browser = validation_actions(
        (),
        (),
        (
            BrowserObservation(
                view="dashboard",
                state="error",
                diagnostics=(
                    BrowserDiagnostic(
                        code="missing-variable",
                        severity="error",
                        message="Projected summary is unavailable",
                        hint="Restore the projected summary value.",
                        view="dashboard",
                        scope="projection",
                        target="summary.total",
                        source=source,
                    ),
                ),
            ),
        ),
        browser_required=True,
        default_view=None,
    )[0]

    for action in (static, runtime, browser):
        assert action.code == "missing-variable"
        assert action.view == "dashboard"
        assert action.target == "summary.total"
        assert action.source == source
        assert action.advice == "Restore the projected summary value."


@pytest.mark.native_process
def test_runtime_analysis_runs_in_a_dedicated_process(notebook_path) -> None:
    prepare_view(notebook_path)
    studio = load_studio(notebook_path)
    _build, presentation_revision, artifact_revision = publish_presentation(
        studio,
        "dashboard",
    )

    assert presentation_revision is not None
    assert artifact_revision is not None

    checks = asyncio.run(check_runtime_studio_isolated(studio, view_name="dashboard"))

    assert not [check for check in checks if check.status == "fail"]
    assert (notebook_path.parent / "cell-executed").read_text() == "executed"


def test_analysis_skips_runtime_and_builds_repair_actions(
    notebook_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepare_view(notebook_path)
    studio = load_studio(notebook_path)
    runtime_called = False

    monkeypatch.setattr(
        validation_service,
        "check_studio",
        lambda studio, *_args, **_kwargs: _check_report(
            studio,
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

    monkeypatch.setattr(analysis_module, "check_runtime_studio_isolated", runtime)
    report = asyncio.run(analyze_studio(studio, AnalysisOptions(require_browser=True)))

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
    prepare_view(notebook_path)
    studio = load_studio(notebook_path)
    monkeypatch.setattr(
        validation_service,
        "check_studio",
        lambda studio, *_args, **_kwargs: _check_report(
            studio, CheckResult("static", "pass", "ready")
        ),
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

    monkeypatch.setattr(analysis_module, "check_runtime_studio_isolated", runtime)
    observed = asyncio.run(
        analyze_studio(
            studio,
            AnalysisOptions(require_browser=True),
            observe_browser=observe,
        )
    )
    unobserved = asyncio.run(
        analyze_studio(studio, AnalysisOptions(require_browser=True))
    )

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


def _analyze_mounts(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    allowed_targets: tuple[tuple[str, ...] | None, ...],
) -> AnalysisReport:
    prepare_view(notebook_path)
    studio = load_studio(notebook_path)
    sites = tuple(
        MountDeclaration(
            id=f"site:value:{index}",
            kind="value",
            source=SourceLocation(PurePosixPath("src/App.tsx"), index + 1, 1),
            allowed_targets=targets,
        )
        for index, targets in enumerate(allowed_targets)
    )
    monkeypatch.setattr(
        "marimo_studio._views.inspection.inspect_view_mounts",
        lambda _project: sites,
    )
    monkeypatch.setattr(
        validation_service,
        "check_studio",
        lambda studio, *_args, **_kwargs: _check_report(
            studio, CheckResult("static", "pass", "ready")
        ),
    )

    async def runtime(*_args, **_kwargs):
        return (CheckResult("runtime", "pass", "ready"),)

    monkeypatch.setattr(analysis_module, "check_runtime_studio_isolated", runtime)
    return asyncio.run(analyze_studio(studio, AnalysisOptions(require_browser=False)))


def test_set_only_analysis_is_handoff_ready_without_browser(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = _analyze_mounts(
        notebook_path,
        monkeypatch,
        (("report", "summary"),),
    )

    assert report.dynamic_browser_required is False
    assert report.ok is True
    assert report.handoff_ready is True
    assert report.actions == ()
    stages = report.to_dict()["stages"]
    assert isinstance(stages, dict)
    assert stages["browser"] == {
        "required": False,
        "required_for_dynamic_sites": False,
        "status": "not-observed",
        "observations": [
            {
                "view": "dashboard",
                "state": "not-observed",
                "diagnostics": [],
                "message": "No rendered browser observation was requested.",
                "code": "browser-not-requested",
            }
        ],
    }


def test_wildcard_mounts_require_browser_evidence_and_a_repair_action(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = _analyze_mounts(
        notebook_path,
        monkeypatch,
        (
            ("report",),
            ("report", "summary"),
            None,
        ),
    )

    assert report.dynamic_browser_required is True
    assert report.ok is False
    assert report.handoff_ready is False
    assert [action.code for action in report.actions] == ["browser-not-requested"]
    stages = report.to_dict()["stages"]
    assert isinstance(stages, dict)
    browser = stages["browser"]
    assert isinstance(browser, dict)
    assert browser["required"] is False
    assert browser["required_for_dynamic_sites"] is True


def test_browser_connection_errors_become_repair_actions(
    notebook_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepare_view(notebook_path)
    studio = load_studio(notebook_path)
    monkeypatch.setattr(
        validation_service,
        "check_studio",
        lambda studio, *_args, **_kwargs: _check_report(
            studio, CheckResult("static", "pass", "ready")
        ),
    )

    async def runtime(*_args, **_kwargs):
        return (CheckResult("runtime", "pass", "ready"),)

    async def observe(_studio, _views, _revisions):
        raise ProtocolError("The running Studio server is unavailable.")

    monkeypatch.setattr(analysis_module, "check_runtime_studio_isolated", runtime)
    report = asyncio.run(
        analyze_studio(
            studio,
            AnalysisOptions(require_browser=True),
            observe_browser=observe,
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
    prepare_view(notebook_path)
    studio = load_studio(notebook_path)
    monkeypatch.setattr(
        validation_service,
        "check_studio",
        lambda studio, *_args, **_kwargs: _check_report(
            studio, CheckResult("static", "pass", "ready")
        ),
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
                await wait_for_event(started)
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
                await wait_for_event(started)
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
                AnalysisOptions(require_browser=True),
                observe_browser=observe,
                runtime_checker=runtime,
            )

    asyncio.run(exercise())

    assert sibling_cancelled


def test_analysis_rejects_evidence_collected_across_source_revisions(
    notebook_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepare_view(notebook_path)
    studio = load_studio(notebook_path)
    monkeypatch.setattr(
        validation_service,
        "check_studio",
        lambda studio, *_args, **_kwargs: _check_report(
            studio, CheckResult("static", "pass", "ready")
        ),
    )

    async def runtime(
        studio: StudioWorkspace,
        *,
        view_name: str | None = None,
        expected_revisions: dict[str, str] | None = None,
        timeout: float = 60.0,
    ) -> tuple[CheckResult, ...]:
        assert view_name is None
        assert timeout == 60
        assert expected_revisions is not None
        assert set(expected_revisions) == {"dashboard"}
        template = studio.views["dashboard"].root / "index.html"
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
            AnalysisOptions(require_browser=True),
            observe_browser=observe,
            runtime_checker=runtime,
        )
    )

    assert not report.handoff_ready
    assert "analysis-source-changed" in {action.code for action in report.actions}


def test_focused_analysis_ignores_an_unrelated_view_edit(
    notebook_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepare_view(notebook_path)
    prepare_view(notebook_path, "executive")
    studio = load_studio(notebook_path)
    monkeypatch.setattr(
        validation_service,
        "check_studio",
        lambda studio, *_args, **_kwargs: _check_report(
            studio, CheckResult("static", "pass", "ready")
        ),
    )

    async def runtime(*_args, **_kwargs):
        template = studio.views["executive"].root / "index.html"
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
            AnalysisOptions(view="dashboard", require_browser=True),
            observe_browser=observe,
            runtime_checker=runtime,
        )
    )

    assert report.handoff_ready
    assert report.actions == ()


def test_selected_view_deletion_becomes_a_source_unavailable_action(
    notebook_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepare_view(notebook_path)
    studio = load_studio(notebook_path)
    monkeypatch.setattr(
        validation_service,
        "check_studio",
        lambda studio, *_args, **_kwargs: _check_report(
            studio, CheckResult("static", "pass", "ready")
        ),
    )

    async def runtime(*_args, **_kwargs):
        (studio.views["dashboard"].root / "index.html").unlink()
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
            AnalysisOptions(view="dashboard", require_browser=True),
            observe_browser=observe,
            runtime_checker=runtime,
        )
    )

    assert not report.handoff_ready
    assert report.actions[-1].code == "analysis-project-stale"
    assert report.actions[-1].source == {
        "path": str(studio.views["dashboard"].manifest)
    }
    assert "build diagnostics" in report.actions[-1].advice


def test_missing_view_source_becomes_a_static_repair_action(notebook_path) -> None:
    prepare_view(notebook_path)
    studio = load_studio(notebook_path)
    (studio.views["dashboard"].root / "index.html").unlink()

    report = asyncio.run(analyze_studio(studio, AnalysisOptions(view="dashboard")))

    assert not report.handoff_ready
    assert "view-project-error" in {action.code for action in report.actions}
