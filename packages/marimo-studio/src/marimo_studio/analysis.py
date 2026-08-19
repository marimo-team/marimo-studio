"""Build one agent-facing validation report for authored views."""

from __future__ import annotations

import asyncio
import math
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Literal, Protocol, cast

from marimo_studio._runtime_limits import DEFAULT_RUNTIME_TIMEOUT, MAX_RUNTIME_TIMEOUT
from marimo_studio._workspace.models import StudioWorkspace
from marimo_studio._workspace.revisions import capture_studio_sources
from marimo_studio.agent_models import (
    AnalysisAction,
    AnalysisReport,
    BrowserObservation,
)
from marimo_studio.checks import check_runtime_studio, check_studio
from marimo_studio.errors import (
    CapabilityInputError,
    MarimoStudioError,
    ViewNotFoundError,
)
from marimo_studio.types import CheckResult

BrowserObserver = Callable[
    [StudioWorkspace, tuple[str, ...], dict[str, str]],
    Awaitable[tuple[BrowserObservation, ...]],
]

DEFAULT_BROWSER_TIMEOUT = 10.0
MAX_BROWSER_TIMEOUT = 300.0


@dataclass(frozen=True)
class AnalysisOptions:
    """Select views and evidence budgets for one analysis."""

    view: str | None = None
    browser_timeout: float = DEFAULT_BROWSER_TIMEOUT
    runtime_timeout: float = DEFAULT_RUNTIME_TIMEOUT
    require_browser: bool = True

    def __post_init__(self) -> None:
        if self.view is not None and not isinstance(self.view, str):
            raise CapabilityInputError(
                "invalid-analysis-request",
                "view",
                "view must be a string or null",
            )
        _validate_timeout(
            "browser_timeout",
            self.browser_timeout,
            MAX_BROWSER_TIMEOUT,
        )
        _validate_timeout(
            "runtime_timeout",
            self.runtime_timeout,
            MAX_RUNTIME_TIMEOUT,
        )
        if not isinstance(self.require_browser, bool):
            raise CapabilityInputError(
                "invalid-analysis-request",
                "require_browser",
                "require_browser must be a boolean",
            )


@dataclass(frozen=True)
class AnalysisRequest:
    """Analysis options plus an optional external browser selector."""

    view: str | None = None
    browser_timeout: float = DEFAULT_BROWSER_TIMEOUT
    runtime_timeout: float = DEFAULT_RUNTIME_TIMEOUT
    require_browser: bool = True
    browser_client: str | None = None

    def __post_init__(self) -> None:
        _ = self.options
        if self.browser_client is not None and (
            not isinstance(self.browser_client, str) or not self.browser_client
        ):
            raise CapabilityInputError(
                "invalid-analysis-request",
                "browser_client",
                "browser_client must be a non-empty string or null",
            )

    @property
    def options(self) -> AnalysisOptions:
        return AnalysisOptions(
            view=self.view,
            browser_timeout=self.browser_timeout,
            runtime_timeout=self.runtime_timeout,
            require_browser=self.require_browser,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": 1,
            "view": self.view,
            "browser_timeout": self.browser_timeout,
            "runtime_timeout": self.runtime_timeout,
            "require_browser": self.require_browser,
            "browser_client": self.browser_client,
        }

    @classmethod
    def from_dict(cls, payload: object) -> AnalysisRequest:
        schema = payload.get("schema") if isinstance(payload, dict) else None
        if (
            not isinstance(payload, dict)
            or type(schema) is not int
            or schema != 1
            or not set(payload).issubset(
                {
                    "schema",
                    "view",
                    "browser_timeout",
                    "runtime_timeout",
                    "require_browser",
                    "browser_client",
                }
            )
        ):
            raise CapabilityInputError(
                "invalid-analysis-request",
                "request",
                "The analysis request must use schema 1 and supported fields",
            )
        return cls(
            view=payload.get("view"),
            browser_timeout=payload.get("browser_timeout", DEFAULT_BROWSER_TIMEOUT),
            runtime_timeout=payload.get("runtime_timeout", DEFAULT_RUNTIME_TIMEOUT),
            require_browser=payload.get("require_browser", True),
            browser_client=payload.get("browser_client"),
        )

    def require_focused_view(self) -> None:
        if self.require_browser and self.view is None:
            raise CapabilityInputError(
                "focused-analysis-required",
                "view",
                "Code-mode browser analysis requires one active view. "
                "Activate it in one call, then analyze it in the next call.",
            )


def _validate_timeout(field: str, value: object, maximum: float) -> None:
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not 0 <= value <= maximum
        or not math.isfinite(value)
    ):
        raise CapabilityInputError(
            "invalid-analysis-request",
            field,
            f"{field} must be a finite number between 0 and {maximum:g} seconds",
        )


class RuntimeChecker(Protocol):
    async def __call__(
        self,
        studio: StudioWorkspace,
        *,
        view_name: str | None = None,
        expected_revisions: dict[str, str] | None = None,
        timeout: float = DEFAULT_RUNTIME_TIMEOUT,
    ) -> tuple[CheckResult, ...]: ...


async def analyze_studio(
    studio: StudioWorkspace,
    options: AnalysisOptions | None = None,
    *,
    observe_browser: BrowserObserver | None = None,
    runtime_checker: RuntimeChecker | None = None,
) -> AnalysisReport:
    """Validate selected views and return a repair-oriented report.

    Static validation always runs. Runtime validation runs after the static
    stage succeeds. Pass ``observe_browser`` to include readiness reported by
    rendered Studio pages.
    """
    options = options or AnalysisOptions()
    views = _selected_views(studio, options.view)
    before, before_error, static_checks, after, after_error = await asyncio.to_thread(
        _static_stage,
        studio,
        views,
        options.view,
    )
    source_stable = before is not None and before == after
    revisions = after or before or {view: "unavailable" for view in views}
    source_error = before_error or after_error
    if source_error is not None:
        static_checks = (
            *static_checks,
            CheckResult(
                "analysis-source-revision",
                "fail",
                f"Studio sources could not be captured: {source_error}",
                code="analysis-source-unavailable",
                details={
                    "source": {"path": str(studio.notebook)},
                    "hint": (
                        "Restore the missing source, save it, then rerun the analysis."
                    ),
                },
            ),
        )
    elif not source_stable:
        static_checks = (
            *static_checks,
            CheckResult(
                "analysis-source-revision",
                "fail",
                "Studio sources changed during static validation.",
                code="analysis-source-changed",
                details={
                    "source": {"path": str(studio.notebook)},
                    "hint": (
                        "Wait for the current edits to save, then rerun the analysis."
                    ),
                },
            ),
        )
    static_failed = any(result.status == "fail" for result in static_checks)
    if static_failed:
        runtime_checks: tuple[CheckResult, ...] = ()
        runtime_skipped = "Static validation failed. Fix those errors first."
        observations = _unobserved(
            views,
            "Browser validation waits for static validation to pass.",
            code="browser-skipped",
        )
    else:
        runtime_result, observations = await _runtime_and_browser(
            studio,
            views,
            revisions,
            view_name=options.view,
            observe_browser=observe_browser,
            runtime_checker=runtime_checker,
            runtime_timeout=options.runtime_timeout,
        )
        runtime_checks = runtime_result
        runtime_skipped = None
    actions = _actions(
        static_checks,
        runtime_checks,
        observations,
        browser_required=options.require_browser,
    )
    current_revisions, current_error = await asyncio.to_thread(
        _try_selected_revisions,
        studio,
        views,
    )
    if source_stable:
        if current_error is not None:
            actions = (
                *actions,
                AnalysisAction(
                    stage="analysis",
                    severity="error",
                    code="analysis-source-unavailable",
                    message=(
                        "Studio sources could not be captured after validation: "
                        f"{current_error}"
                    ),
                    advice=(
                        "Restore the missing source, save it, then rerun the analysis."
                    ),
                    source={"path": str(studio.notebook)},
                ),
            )
        elif current_revisions != revisions:
            actions = (
                *actions,
                AnalysisAction(
                    stage="analysis",
                    severity="error",
                    code="analysis-source-changed",
                    message="Studio sources changed while the analysis was running.",
                    advice=(
                        "Wait for the current edits to save, then rerun the analysis."
                    ),
                ),
            )
    return AnalysisReport(
        notebook=studio.notebook,
        views=views,
        runtime=studio.default_runtime,
        revisions=revisions,
        static_checks=static_checks,
        runtime_checks=runtime_checks,
        runtime_skipped=runtime_skipped,
        browser_observations=observations,
        browser_required=options.require_browser,
        actions=actions,
    )


def _static_stage(
    studio: StudioWorkspace,
    views: tuple[str, ...],
    view_name: str | None,
) -> tuple[
    dict[str, str] | None,
    Exception | None,
    tuple[CheckResult, ...],
    dict[str, str] | None,
    Exception | None,
]:
    before, before_error = _try_selected_revisions(studio, views)
    static_checks = check_studio(studio, view_name=view_name).checks
    after, after_error = _try_selected_revisions(studio, views)
    return before, before_error, static_checks, after, after_error


def _selected_revisions(
    studio: StudioWorkspace,
    views: tuple[str, ...],
) -> dict[str, str]:
    revisions = capture_studio_sources(studio, views).revisions
    return {view: revisions[view] for view in views}


def _try_selected_revisions(
    studio: StudioWorkspace,
    views: tuple[str, ...],
) -> tuple[dict[str, str] | None, Exception | None]:
    try:
        return _selected_revisions(studio, views), None
    except (KeyError, OSError, MarimoStudioError) as error:
        return None, error


async def _runtime_and_browser(
    studio: StudioWorkspace,
    views: tuple[str, ...],
    revisions: dict[str, str],
    *,
    view_name: str | None,
    observe_browser: BrowserObserver | None,
    runtime_checker: RuntimeChecker | None,
    runtime_timeout: float,
) -> tuple[tuple[CheckResult, ...], tuple[BrowserObservation, ...]]:
    async def check_runtime() -> tuple[CheckResult, ...]:
        if runtime_checker is None:
            return await check_runtime_studio(
                studio,
                view_name=view_name,
                timeout=runtime_timeout,
            )
        return await runtime_checker(
            studio,
            view_name=view_name,
            expected_revisions=revisions,
            timeout=runtime_timeout,
        )

    async def observe() -> tuple[BrowserObservation, ...]:
        if observe_browser is None:
            return _unobserved(
                views,
                "No rendered browser observation was requested.",
                code="browser-not-requested",
            )
        try:
            return await observe_browser(studio, views, revisions)
        except MarimoStudioError as error:
            return _unobserved(views, str(error), code=error.code)

    runtime_task = asyncio.create_task(check_runtime())
    browser_task = asyncio.create_task(observe())
    tasks = (runtime_task, browser_task)
    try:
        runtime_checks, observations = await asyncio.gather(*tasks)
        return runtime_checks, observations
    except BaseException:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise


def _unobserved(
    views: tuple[str, ...],
    message: str,
    *,
    code: str,
) -> tuple[BrowserObservation, ...]:
    return tuple(
        BrowserObservation(
            view=view,
            state="not-observed",
            message=message,
            code=code,
        )
        for view in views
    )


def _selected_views(
    studio: StudioWorkspace,
    view_name: str | None,
) -> tuple[str, ...]:
    if view_name is None:
        return tuple(studio.views)
    if view_name not in studio.views:
        raise ViewNotFoundError(view_name, available=tuple(studio.views))
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
            and observation.code != "browser-skipped"
            and not any(
                diagnostic.severity == "error" for diagnostic in observation.diagnostics
            )
        ):
            actions.append(
                AnalysisAction(
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


def _default_browser_advice(state: str, code: str | None = None) -> str:
    if code == "authentication-required":
        return "Authenticate to the notebook server, then rerun the analysis."
    if code == "notebook-mismatch":
        return "Use the server URL for this notebook, then rerun the analysis."
    if code == "browser-client-ambiguous":
        return (
            "Close the extra Studio tab or select its browser client, then rerun "
            "the analysis."
        )
    if code == "browser-client-unavailable":
        return "Open Studio for this notebook, then rerun the analysis."
    if code == "server-unavailable":
        return (
            "Start or reconnect the requested Studio server, then rerun the analysis."
        )
    if code == "browser-observation-timeout":
        return (
            "Check the Studio browser connection and rendered-view errors, then "
            "rerun the analysis."
        )
    if code == "browser-session-changed":
        return "Rerun the analysis from the Studio tab for the current Marimo session."
    if code == "browser-session-unavailable":
        return "Wait for the Studio editor session to connect, then rerun the analysis."
    if code == "browser-view-not-active":
        return (
            "Activate the view in one code-mode call, wait for it to render, "
            "then analyze it in the next call."
        )
    if code == "browser-operation-in-progress":
        return "Wait for the current Studio browser operation, then rerun the analysis."
    if state == "not-observed":
        return (
            "Open Studio for this notebook, select the view, then rerun the analysis."
        )
    if state == "stale":
        return (
            "Wait for Studio to reload the saved view revision, then rerun "
            "the analysis."
        )
    if state == "loading":
        return "Wait for the rendered view to settle, then rerun the analysis."
    return "Fix the rendered view diagnostic, then rerun the analysis."


__all__ = [
    "DEFAULT_BROWSER_TIMEOUT",
    "MAX_BROWSER_TIMEOUT",
    "AnalysisOptions",
    "AnalysisReport",
    "AnalysisRequest",
    "BrowserObserver",
    "RuntimeChecker",
    "analyze_studio",
]
