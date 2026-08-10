"""Build one agent-facing validation report for authored views."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Literal, cast

from marimo_studio._workspace.models import StudioWorkspace
from marimo_studio.checks import check_runtime_studio, check_studio
from marimo_studio.errors import ConfigurationError, MarimoStudioError
from marimo_studio.types import (
    AnalysisAction,
    AnalysisReport,
    BrowserObservation,
    CheckResult,
)

BrowserObserver = Callable[
    [StudioWorkspace, tuple[str, ...]],
    Awaitable[tuple[BrowserObservation, ...]],
]


async def analyze_studio(
    studio: StudioWorkspace,
    *,
    view_name: str | None = None,
    observe_browser: BrowserObserver | None = None,
    require_browser: bool = False,
) -> AnalysisReport:
    """Validate selected views and return a repair-oriented report.

    Static validation always runs. Runtime validation runs after the static
    stage succeeds. Pass ``observe_browser`` to include readiness reported by
    rendered Studio pages.
    """
    views = _selected_views(studio, view_name)
    static_checks = check_studio(studio, view_name=view_name)
    static_failed = any(result.status == "fail" for result in static_checks)
    if static_failed:
        runtime_checks: tuple[CheckResult, ...] = ()
        runtime_skipped = "Static validation failed. Fix those errors first."
    else:
        runtime_checks = await check_runtime_studio(studio, view_name=view_name)
        runtime_skipped = None

    if observe_browser is None:
        observations = tuple(
            BrowserObservation(
                view=view,
                state="not-observed",
                message="No rendered browser observation was requested.",
            )
            for view in views
        )
    else:
        try:
            observations = await observe_browser(studio, views)
        except MarimoStudioError as error:
            observations = tuple(
                BrowserObservation(
                    view=view,
                    state="not-observed",
                    message=str(error),
                )
                for view in views
            )
    actions = _actions(
        static_checks,
        runtime_checks,
        observations,
        browser_required=require_browser,
    )
    return AnalysisReport(
        notebook=studio.notebook,
        views=views,
        static_checks=static_checks,
        runtime_checks=runtime_checks,
        runtime_skipped=runtime_skipped,
        browser_observations=observations,
        browser_required=require_browser,
        actions=actions,
    )


def _selected_views(
    studio: StudioWorkspace,
    view_name: str | None,
) -> tuple[str, ...]:
    if view_name is None:
        return tuple(studio.views)
    if view_name not in studio.views:
        available = ", ".join(studio.views)
        raise ConfigurationError(
            f"Unknown view {view_name!r}. Available views: {available}."
        )
    return (view_name,)


def _actions(
    static_checks: tuple[CheckResult, ...],
    runtime_checks: tuple[CheckResult, ...],
    observations: tuple[BrowserObservation, ...],
    *,
    browser_required: bool,
) -> tuple[AnalysisAction, ...]:
    actions = [
        _check_action(stage, result)
        for stage, checks in (
            ("static", static_checks),
            ("runtime", runtime_checks),
        )
        for result in checks
        if result.status != "pass"
    ]
    for observation in observations:
        actions.extend(
            AnalysisAction(
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
            and not any(
                diagnostic.severity == "error" for diagnostic in observation.diagnostics
            )
        ):
            actions.append(
                AnalysisAction(
                    stage="browser",
                    severity="error",
                    code=f"browser-{observation.state}",
                    message=observation.message
                    or f"Rendered view {observation.view!r} is {observation.state}.",
                    advice=_default_browser_advice(observation.state),
                    view=observation.view,
                )
            )
    return tuple(actions)


def _check_action(
    stage: Literal["static", "runtime"],
    result: CheckResult,
) -> AnalysisAction:
    details = result.details or {}
    view = details.get("view")
    if not isinstance(view, str):
        views = details.get("views")
        view = views[0] if isinstance(views, list) and views else None
    target = details.get("target")
    source = details.get("source")
    hint = details.get("hint")
    return AnalysisAction(
        stage=stage,
        severity="error" if result.status == "fail" else "warning",
        code=result.code or result.name,
        message=result.message,
        advice=(
            hint
            if isinstance(hint, str) and hint
            else _default_check_advice(stage, result)
        ),
        view=view if isinstance(view, str) else None,
        target=target if isinstance(target, str) else None,
        source=source if _string_keyed_mapping(source) else None,
    )


def _string_keyed_mapping(value: object) -> dict[str, object] | None:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        return None
    return cast(dict[str, object], value)


def _default_check_advice(stage: str, result: CheckResult) -> str:
    if result.name == "runtime-assets":
        return "Rebuild the Studio browser assets, then rerun the analysis."
    if stage == "static":
        return "Fix the referenced notebook or view source, then rerun the analysis."
    return "Fix the projected notebook output, then rerun the analysis."


def _default_browser_advice(state: str) -> str:
    if state == "not-observed":
        return (
            "Open and authenticate Studio for this notebook, select the view, "
            "wait for it to settle, then rerun the analysis."
        )
    if state == "stale":
        return (
            "Wait for Studio to reload the saved view revision, then rerun "
            "the analysis."
        )
    if state == "loading":
        return "Wait for the rendered view to settle, then rerun the analysis."
    return "Fix the rendered view diagnostic, then rerun the analysis."


__all__ = ["BrowserObserver", "analyze_studio"]
