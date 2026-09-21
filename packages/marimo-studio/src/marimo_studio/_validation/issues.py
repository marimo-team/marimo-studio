"""Map validation evidence to actionable issues."""

from __future__ import annotations

from typing import Literal, cast

from marimo_studio._validation.evidence import ValidationIssue
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
