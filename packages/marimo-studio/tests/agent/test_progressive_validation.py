from __future__ import annotations

import asyncio
import shutil
from dataclasses import replace
from pathlib import Path, PurePosixPath

import pytest

import marimo_studio._validation.service as validation_service
from marimo_studio._validation.evidence import (
    BrowserDiagnostic,
    BrowserObservation,
    ValidationEvidence,
)
from marimo_studio._validation.issues import validation_issues
from marimo_studio._validation.progressive import (
    ValidationOptions,
    ValidationRequest,
    validate_progressively,
)
from marimo_studio._validation.records import ValidationReport
from marimo_studio._validation.results import CheckResult
from marimo_studio._validation.runtime_process import check_runtime_studio_isolated
from marimo_studio._validation.static import CheckReport
from marimo_studio._views.api import prepare_view
from marimo_studio._views.presentation_publication import publish_presentation
from marimo_studio._workspace import load_studio
from marimo_studio._workspace.models import StudioWorkspace
from marimo_studio.errors import (
    CapabilityInputError,
    ProtocolError,
    ViewGenerationConflictError,
)
from marimo_studio.view_providers import (
    MountDeclaration,
    SourceLocation,
)

from ..async_test_support import wait_for_event
from ..helpers import ready_runtime_status


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("browser_timeout", 10**1000),
        ("runtime_timeout", -(10**1000)),
    ],
)
def test_validation_request_rejects_oversized_timeout_integers(
    field: str,
    value: int,
) -> None:
    with pytest.raises(CapabilityInputError) as raised:
        ValidationRequest.from_dict({"schema": 1, field: value})

    assert raised.value.code == "invalid-validation-request"
    assert raised.value.field == field


def test_validation_request_round_trips_its_versioned_record() -> None:
    request = ValidationRequest(
        view="dashboard",
        browser_timeout=20,
        runtime_timeout=75,
        require_browser=False,
        browser_client="browser-client-1234",
        catalog_generation="a" * 64,
        view_generation="b" * 64,
    )

    assert ValidationRequest.from_dict(request.to_dict()) == request
    assert request.to_dict()["schema"] == 1
    assert "catalog_generation" not in ValidationRequest(view="dashboard").to_dict()
    with pytest.raises(CapabilityInputError) as raised:
        ValidationRequest.from_dict({})
    assert raised.value.field == "request"


@pytest.mark.parametrize(
    ("payload", "field"),
    [
        ({"catalog_generation": "a" * 64}, "view_generation"),
        ({"view_generation": "b" * 64}, "catalog_generation"),
        (
            {
                "catalog_generation": "invalid",
                "view_generation": "b" * 64,
            },
            "catalog_generation",
        ),
        (
            {
                "catalog_generation": "a" * 64,
                "view_generation": "b" * 64,
            },
            "view",
        ),
    ],
)
def test_validation_request_rejects_incomplete_owner_records(
    payload: dict[str, str],
    field: str,
) -> None:
    with pytest.raises(CapabilityInputError) as raised:
        ValidationRequest.from_dict({"schema": 1, **payload})

    assert raised.value.field == field


def test_strict_validation_rechecks_the_view_owner_before_return(
    notebook_path: Path,
) -> None:
    prepare_view(notebook_path)
    studio = load_studio(notebook_path)
    root = studio.views["dashboard"].root
    retired = root.with_name("retired-dashboard")

    async def runtime(*_args: object, **_kwargs: object) -> tuple[CheckResult, ...]:
        return (CheckResult("runtime", "pass", "ready"),)

    async def observe(
        _studio: StudioWorkspace,
        views: tuple[str, ...],
        revisions: dict[str, str],
    ) -> tuple[BrowserObservation, ...]:
        root.rename(retired)
        shutil.copytree(retired, root)
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

    with pytest.raises(ViewGenerationConflictError):
        asyncio.run(
            validate_progressively(
                studio,
                ValidationOptions(view="dashboard", require_browser=True),
                observe_browser=observe,
                runtime_checker=runtime,
                expected_catalog_generation=studio.catalog_generation,
                expected_generations={
                    "dashboard": studio.view_generations["dashboard"]
                },
            )
        )


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


async def _passing_runtime(
    *_args: object,
    **_kwargs: object,
) -> tuple[CheckResult, ...]:
    return (CheckResult("runtime", "pass", "ready"),)


def _ready_observation(
    view: str,
    revision: str,
    sequence: int = 0,
) -> BrowserObservation:
    return BrowserObservation(
        view=view,
        runtime="server",
        revision=revision,
        state="ready",
        client_id="browser-client-1234",
        runtime_instance="runtime-instance",
        session_id="s_123456",
        request_id=f"request-{view}",
        sequence=sequence,
        runtime_status=ready_runtime_status(view, revision),
    )


async def _observe_ready(
    _studio: StudioWorkspace,
    views: tuple[str, ...],
    revisions: dict[str, str],
) -> tuple[BrowserObservation, ...]:
    return tuple(
        _ready_observation(view, revisions[view], index)
        for index, view in enumerate(views)
    )


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
    browser = validation_issues(
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

    report = asyncio.run(
        validate_progressively(
            studio,
            ValidationOptions(require_browser=True),
            runtime_checker=runtime,
        )
    )

    assert not runtime_called
    assert report.ok is False
    assert report.runtime_skipped is not None
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


def test_required_browser_evidence_controls_handoff_readiness(
    notebook_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    studio = _passing_studio(notebook_path, monkeypatch)
    observed = asyncio.run(
        validate_progressively(
            studio,
            ValidationOptions(require_browser=True),
            observe_browser=_observe_ready,
            runtime_checker=_passing_runtime,
        )
    )
    unobserved = asyncio.run(
        validate_progressively(
            studio,
            ValidationOptions(require_browser=True),
            runtime_checker=_passing_runtime,
        )
    )

    assert observed.ok is True
    missing_session = replace(
        observed,
        browser_observations=(
            replace(observed.browser_observations[0], session_id=None),
        ),
    )
    assert missing_session.ok is False
    assert unobserved.ok is False
    assert unobserved.issues[0].code == "browser-not-requested"
    assert unobserved.to_dict()["summary"] == {
        "pass": 2,
        "warn": 0,
        "fail": 1,
    }


def _analyze_mounts(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    allowed_targets: tuple[tuple[str, ...] | None, ...],
) -> ValidationEvidence:
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

    return asyncio.run(
        validate_progressively(
            studio,
            ValidationOptions(require_browser=False),
            runtime_checker=_passing_runtime,
        )
    )


def test_validation_without_browser_uses_complete_runtime_evidence(
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
    assert report.issues == ()
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
    assert [action.code for action in report.issues] == ["browser-not-requested"]
    stages = report.to_dict()["stages"]
    assert isinstance(stages, dict)
    browser = stages["browser"]
    assert isinstance(browser, dict)
    assert browser["required"] is False
    assert browser["required_for_dynamic_sites"] is True


def test_browser_connection_errors_become_repair_issues(
    notebook_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    studio = _passing_studio(notebook_path, monkeypatch)

    async def observe(_studio, _views, _revisions):
        raise ProtocolError("The running Studio server is unavailable.")

    report = asyncio.run(
        validate_progressively(
            studio,
            ValidationOptions(require_browser=True),
            observe_browser=observe,
            runtime_checker=_passing_runtime,
        )
    )

    assert report.ok is False
    assert report.browser_observations[0].message == (
        "The running Studio server is unavailable."
    )
    assert report.issues[0].code == "protocol-error"


@pytest.mark.parametrize("failing_stage", ["runtime", "browser"])
def test_unexpected_stage_failure_cancels_sibling_analysis_work(
    notebook_path,
    monkeypatch: pytest.MonkeyPatch,
    failing_stage: str,
) -> None:
    studio = _passing_studio(notebook_path, monkeypatch)
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
            await validate_progressively(
                studio,
                ValidationOptions(require_browser=True),
                observe_browser=observe,
                runtime_checker=runtime,
            )

    asyncio.run(exercise())

    assert sibling_cancelled


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

    report = asyncio.run(
        validate_progressively(
            studio,
            ValidationOptions(require_browser=True),
            observe_browser=_observe_ready,
            runtime_checker=runtime,
        )
    )

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

    report = asyncio.run(
        validate_progressively(
            studio,
            ValidationOptions(view="dashboard", require_browser=True),
            observe_browser=_observe_ready,
            runtime_checker=runtime,
        )
    )

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

    report = asyncio.run(
        validate_progressively(
            studio,
            ValidationOptions(view="dashboard", require_browser=True),
            observe_browser=_observe_ready,
            runtime_checker=runtime,
        )
    )

    assert not report.ok
    assert report.issues[-1].code == "validation-project-stale"
    assert report.issues[-1].source == {"path": str(studio.views["dashboard"].manifest)}
    assert "build diagnostics" in report.issues[-1].advice


def test_missing_view_source_becomes_a_static_repair_action(notebook_path) -> None:
    prepare_view(notebook_path)
    studio = load_studio(notebook_path)
    (studio.views["dashboard"].root / "index.html").unlink()

    report = asyncio.run(
        validate_progressively(studio, ValidationOptions(view="dashboard"))
    )

    assert not report.ok
    assert "view-project-error" in {action.code for action in report.issues}
