"""Map validation evidence to actionable issues."""

from __future__ import annotations

from typing import Literal, cast

from marimo_studio._validation.evidence import (
    BrowserObservation,
    ValidationIssue,
)
from marimo_studio._validation.results import CheckResult

CheckStage = Literal["validation", "static", "runtime"]


def check_issue(
    stage: CheckStage,
    result: CheckResult,
    *,
    default_view: str | None,
) -> ValidationIssue:
    """Preserve one failed check's repair context."""
    details = result.details or {}
    view = details.get("view")
    if not isinstance(view, str):
        views = details.get("views")
        view = views[0] if isinstance(views, list) and views else None
    target = details.get("target")
    source = details.get("source")
    hint = details.get("hint")
    return ValidationIssue(
        stage=stage,
        severity="error" if result.status == "fail" else "warning",
        code=result.code or result.name,
        message=result.message,
        advice=(
            hint
            if isinstance(hint, str) and hint
            else _default_check_advice(stage, result)
        ),
        view=view if isinstance(view, str) else default_view,
        target=target if isinstance(target, str) else None,
        source=_string_keyed_mapping(source),
    )


def check_issues(
    checks: tuple[CheckResult, ...],
    stage: CheckStage,
    *,
    default_view: str | None,
) -> tuple[ValidationIssue, ...]:
    """Return issues for every failed or warning check."""
    return tuple(
        check_issue(stage, result, default_view=default_view)
        for result in checks
        if result.status != "pass"
    )


def validation_issues(
    static_checks: tuple[CheckResult, ...],
    runtime_checks: tuple[CheckResult, ...],
    observations: tuple[BrowserObservation, ...],
    *,
    browser_required: bool,
    default_view: str | None,
) -> tuple[ValidationIssue, ...]:
    """Return one ordered issue list across every validation level."""
    issues = [
        *check_issues(static_checks, "static", default_view=default_view),
        *check_issues(runtime_checks, "runtime", default_view=default_view),
    ]
    for observation in observations:
        issues.extend(
            ValidationIssue(
                stage="browser",
                severity=diagnostic.severity,
                code=diagnostic.code,
                message=diagnostic.message,
                advice=diagnostic.hint or _default_browser_advice(observation.state),
                view=diagnostic.view,
                target=diagnostic.target,
                source=diagnostic.source,
            )
            for diagnostic in observation.diagnostics
        )
        if (
            browser_required
            and observation.state != "ready"
            and observation.code != "browser-skipped"
            and not any(
                diagnostic.severity == "error" for diagnostic in observation.diagnostics
            )
        ):
            issues.append(
                ValidationIssue(
                    stage="browser",
                    severity="error",
                    code=observation.code or f"browser-{observation.state}",
                    message=observation.message
                    or f"Rendered view {observation.view!r} is {observation.state}.",
                    advice=_default_browser_advice(
                        observation.state,
                        observation.code,
                    ),
                    view=observation.view,
                )
            )
    return tuple(issues)


def _string_keyed_mapping(value: object) -> dict[str, object] | None:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        return None
    return cast(dict[str, object], value)


def _default_check_advice(stage: str, result: CheckResult) -> str:
    if result.name == "runtime-assets":
        return "Rebuild the Studio browser assets, then rerun validation."
    if stage == "static":
        return "Fix the referenced notebook or view source, then rerun validation."
    return "Fix the projected notebook output, then rerun validation."


def _default_browser_advice(state: str, code: str | None = None) -> str:
    if code == "authentication-required":
        return "Authenticate to the notebook server, then rerun validation."
    if code == "notebook-mismatch":
        return "Use the server URL for this notebook, then rerun validation."
    if code == "browser-client-ambiguous":
        return (
            "Close the extra Studio tab or select its browser client, then rerun "
            "validation."
        )
    if code == "browser-client-unavailable":
        return "Open Studio for this notebook, then rerun validation."
    if code == "server-unavailable":
        return "Start or reconnect the requested Studio server, then rerun validation."
    if code == "browser-observation-timeout":
        return (
            "Check the Studio browser connection and rendered-view errors, then "
            "rerun validation."
        )
    if code == "browser-session-changed":
        return "Rerun validation from the Studio tab for the current Marimo session."
    if code == "browser-session-unavailable":
        return "Wait for the Studio editor session to connect, then rerun validation."
    if code == "browser-view-not-active":
        return (
            "Show the view in one code-mode call, wait for it to render, "
            "then validate it in the next call."
        )
    if code == "browser-operation-in-progress":
        return "Wait for the current Studio browser operation, then rerun validation."
    if state == "not-observed":
        return "Open Studio for this notebook, select the view, then rerun validation."
    if state == "stale":
        return (
            "Wait for Studio to reload the saved view revision, then rerun validation."
        )
    if state == "loading":
        return "Wait for the rendered view to settle, then rerun validation."
    return "Fix the rendered view diagnostic, then rerun validation."
