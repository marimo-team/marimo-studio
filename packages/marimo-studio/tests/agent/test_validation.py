from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

import marimo_studio._validation.service as validation_service
from marimo_studio._validation.records import ValidationReport
from marimo_studio._validation.results import CheckResult
from marimo_studio._validation.runtime_process import check_runtime_studio_isolated
from marimo_studio._validation.service import validate_studio
from marimo_studio._validation.static import CheckReport
from marimo_studio._views.api import prepare_view
from marimo_studio._views.presentation_publication import publish_presentation
from marimo_studio._workspace import load_studio
from marimo_studio._workspace.models import StudioWorkspace


def _check_report(
    studio: StudioWorkspace,
    *checks: CheckResult,
) -> CheckReport:
    return CheckReport(studio.notebook, None, checks)


def _passing_studio(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> StudioWorkspace:
    prepare_view(notebook_path)
    studio = load_studio(notebook_path)
    monkeypatch.setattr(
        validation_service,
        "check_studio",
        lambda studio, *_args, **_kwargs: _check_report(
            studio,
            CheckResult("static", "pass", "ready"),
        ),
    )
    return studio


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
    ).issues[0]
    runtime = ValidationReport.from_checks(
        CheckReport(notebook_path, None, ()),
        level="runtime",
        runtime=(check,),
    ).issues[0]
    for action in (static, runtime):
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


def test_validation_skips_runtime_and_builds_repair_issues(
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

    run = asyncio.run(
        validate_studio(
            studio,
            level="runtime",
            runtime_checker=runtime,
        )
    )

    report = run.report
    assert not runtime_called
    report = run.report
    assert report.ok is False
    assert run.runtime == ()
    assert report.issues[0].to_dict() == {
        "stage": "static",
        "severity": "error",
        "code": "missing-variable",
        "message": "missing is unavailable",
        "advice": "Restore missing in the notebook.",
        "view": "dashboard",
        "target": "missing",
    }
    assert len(report.issues) == 1


def test_validation_rejects_evidence_collected_across_source_revisions(
    notebook_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    studio = _passing_studio(notebook_path, monkeypatch)

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

    run = asyncio.run(
        validate_studio(
            studio,
            level="runtime",
            runtime_checker=runtime,
        )
    )

    report = run.report
    assert not report.ok
    assert "validation-source-changed" in {action.code for action in report.issues}


def test_focused_analysis_ignores_an_unrelated_view_edit(
    notebook_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    studio = _passing_studio(notebook_path, monkeypatch)
    prepare_view(notebook_path, "executive")
    studio = load_studio(notebook_path)

    async def runtime(*_args, **_kwargs):
        template = studio.views["executive"].root / "index.html"
        template.write_text(
            template.read_text(encoding="utf-8") + "\n<!-- edited -->\n",
            encoding="utf-8",
        )
        return (CheckResult("runtime", "pass", "ready"),)

    run = asyncio.run(
        validate_studio(
            studio,
            level="runtime",
            view_name="dashboard",
            runtime_checker=runtime,
        )
    )

    report = run.report
    assert report.ok
    assert report.issues == ()


def test_selected_view_deletion_becomes_a_source_unavailable_action(
    notebook_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    studio = _passing_studio(notebook_path, monkeypatch)

    async def runtime(*_args, **_kwargs):
        (studio.views["dashboard"].root / "index.html").unlink()
        return (CheckResult("runtime", "pass", "ready"),)

    run = asyncio.run(
        validate_studio(
            studio,
            level="runtime",
            view_name="dashboard",
            runtime_checker=runtime,
        )
    )

    report = run.report
    assert not report.ok
    assert "validation-source-changed" in {issue.code for issue in report.issues}


def test_missing_view_source_becomes_a_static_repair_action(notebook_path) -> None:
    prepare_view(notebook_path)
    studio = load_studio(notebook_path)
    (studio.views["dashboard"].root / "index.html").unlink()

    run = asyncio.run(
        validate_studio(
            studio,
            level="static",
            view_name="dashboard",
            runtime_checker=check_runtime_studio_isolated,
        )
    )

    report = run.report
    assert not report.ok
    assert "view-project-error" in {action.code for action in report.issues}
