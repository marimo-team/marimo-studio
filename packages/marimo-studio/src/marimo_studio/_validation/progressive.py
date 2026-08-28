"""Collect static, runtime, and browser evidence for authored views."""

from __future__ import annotations

import asyncio
import math
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from functools import partial
from typing import TYPE_CHECKING

from marimo_studio._processes.limits import DEFAULT_RUNTIME_TIMEOUT, MAX_RUNTIME_TIMEOUT
from marimo_studio._processes.ownership import settle_ownership
from marimo_studio._processes.provider_operation import (
    process_cleanup_errors,
    raise_process_cleanup,
    run_provider_operation,
)
from marimo_studio._validation.evidence import (
    BrowserObservation,
    ValidationEvidence,
    ValidationIssue,
)
from marimo_studio._validation.issues import check_issue, validation_issues
from marimo_studio._validation.limits import (
    DEFAULT_BROWSER_TIMEOUT,
    MAX_BROWSER_TIMEOUT,
)
from marimo_studio._validation.ports import RuntimeChecker
from marimo_studio._validation.results import CheckResult
from marimo_studio._validation.runtime_process import check_runtime_studio_isolated
from marimo_studio._validation.service import (
    RuntimeValidation,
    ValidationPreparation,
    prepare_validation,
    run_runtime_validation,
    verify_source_revisions,
)
from marimo_studio._workspace.models import StudioWorkspace
from marimo_studio.errors import (
    CapabilityInputError,
    MarimoStudioError,
)

if TYPE_CHECKING:
    from marimo_studio._server.development.coordinator import DevelopmentCoordinator

BrowserObserver = Callable[
    [StudioWorkspace, tuple[str, ...], dict[str, str]],
    Awaitable[tuple[BrowserObservation, ...]],
]


@dataclass(frozen=True)
class ValidationOptions:
    """Select views and evidence budgets for one validation."""

    view: str | None = None
    browser_timeout: float = DEFAULT_BROWSER_TIMEOUT
    runtime_timeout: float = DEFAULT_RUNTIME_TIMEOUT
    require_browser: bool = True

    def __post_init__(self) -> None:
        if self.view is not None and not isinstance(self.view, str):
            raise CapabilityInputError(
                "invalid-validation-request",
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
                "invalid-validation-request",
                "require_browser",
                "require_browser must be a boolean",
            )


@dataclass(frozen=True)
class ValidationRequest:
    """Validation options plus an optional external browser selector."""

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
                "invalid-validation-request",
                "browser_client",
                "browser_client must be a non-empty string or null",
            )

    @property
    def options(self) -> ValidationOptions:
        return ValidationOptions(
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
    def from_dict(cls, payload: object) -> ValidationRequest:
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
                "invalid-validation-request",
                "request",
                "The validation request must use schema 1 and supported fields",
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
                "focused-view-required",
                "view",
                "Code-mode browser validation requires one active view. "
                "Show it in one call, then validate it in the next call.",
            )


def _validate_timeout(field: str, value: object, maximum: float) -> None:
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not 0 <= value <= maximum
        or not math.isfinite(value)
    ):
        raise CapabilityInputError(
            "invalid-validation-request",
            field,
            f"{field} must be a finite number between 0 and {maximum:g} seconds",
        )


async def validate_progressively(
    studio: StudioWorkspace,
    options: ValidationOptions | None = None,
    *,
    observe_browser: BrowserObserver | None = None,
    runtime_checker: RuntimeChecker | None = None,
    development: DevelopmentCoordinator | None = None,
) -> ValidationEvidence:
    """Validate selected views and return a repair-oriented report.

    Static validation always runs. Runtime validation runs after the static
    stage succeeds. Pass ``observe_browser`` to include readiness reported by
    rendered Studio pages.
    """
    options = options or ValidationOptions()
    preparation = await prepare_validation(
        studio,
        view_name=options.view,
        development=development,
    )
    views = preparation.views
    revisions = preparation.revisions
    static_checks = preparation.static.checks
    if not preparation.static.ok:
        runtime_checks: tuple[CheckResult, ...] = ()
        runtime_skipped = "Static validation failed. Fix those errors first."
        observations = _unobserved(
            views,
            "Browser validation waits for static validation to pass.",
            code="browser-skipped",
        )
    else:
        runtime, observations = await _runtime_and_browser(
            studio,
            preparation,
            observe_browser=observe_browser,
            runtime_checker=runtime_checker,
            runtime_timeout=options.runtime_timeout,
        )
        runtime_checks = runtime.checks
        runtime_skipped = runtime.skipped
    issues = validation_issues(
        static_checks,
        runtime_checks,
        observations,
        browser_required=(
            options.require_browser or preparation.dynamic_browser_required
        ),
        default_view=views[0] if len(views) == 1 else None,
    )
    if preparation.source_stable:
        source_check = await verify_source_revisions(
            studio,
            preparation,
            phase="validation",
        )
        if source_check is not None and not any(
            issue.code == source_check.code for issue in issues
        ):
            issues = (
                *issues,
                check_issue(
                    "validation",
                    source_check,
                    default_view=views[0] if len(views) == 1 else None,
                ),
            )
    project_issues = await run_provider_operation(
        partial(
            _project_state_issues,
            studio,
            views,
        )
    )
    issues = (*issues, *project_issues)
    return ValidationEvidence(
        notebook=studio.notebook,
        views=views,
        runtime=studio.default_runtime,
        revisions=revisions,
        static_checks=static_checks,
        runtime_checks=runtime_checks,
        runtime_skipped=runtime_skipped,
        browser_observations=observations,
        browser_required=options.require_browser,
        issues=issues,
        dynamic_browser_required=preparation.dynamic_browser_required,
    )


def _project_state_issues(
    studio: StudioWorkspace,
    views: tuple[str, ...],
) -> tuple[ValidationIssue, ...]:
    from marimo_studio._views.inspection import (
        inspect_view_project_sync,
        view_project_state,
    )

    issues: list[ValidationIssue] = []
    for name in views:
        project = studio.views[name]
        try:
            inspection = inspect_view_project_sync(project)
            state = view_project_state(project, inspection)
        except (OSError, MarimoStudioError, UnicodeError, ValueError) as error:
            raise_process_cleanup(error)
            issues.append(
                ValidationIssue(
                    stage="validation",
                    severity="error",
                    code="validation-project-unavailable",
                    message=f"View project {name!r} could not be inspected: {error}",
                    advice=(
                        "Restore the provider project, then build and validate "
                        "it again."
                    ),
                    view=name,
                    source={"path": str(project.manifest)},
                )
            )
            continue
        if state.build.phase != "published":
            issues.append(
                ValidationIssue(
                    stage="validation",
                    severity="error",
                    code="validation-project-stale",
                    message=(
                        f"View project {name!r} has no current published artifact."
                    ),
                    advice=(
                        "Fix its build diagnostics, publish it, then validate again."
                    ),
                    view=name,
                    source={"path": str(project.manifest)},
                )
            )
    return tuple(issues)


async def _runtime_and_browser(
    studio: StudioWorkspace,
    preparation: ValidationPreparation,
    *,
    observe_browser: BrowserObserver | None,
    runtime_checker: RuntimeChecker | None,
    runtime_timeout: float,
) -> tuple[RuntimeValidation, tuple[BrowserObservation, ...]]:
    async def check_runtime() -> RuntimeValidation:
        checker = runtime_checker or check_runtime_studio_isolated
        return await run_runtime_validation(
            studio,
            preparation,
            runtime_timeout=runtime_timeout,
            runtime_checker=checker,
        )

    async def observe() -> tuple[BrowserObservation, ...]:
        if observe_browser is None:
            return _unobserved(
                preparation.views,
                "No rendered browser observation was requested.",
                code="browser-not-requested",
            )
        try:
            return await observe_browser(
                studio,
                preparation.views,
                preparation.revisions,
            )
        except MarimoStudioError as error:
            raise_process_cleanup(error)
            return _unobserved(preparation.views, str(error), code=error.code)

    runtime_task = asyncio.create_task(check_runtime())
    browser_task = asyncio.create_task(observe())
    tasks = (runtime_task, browser_task)
    try:
        runtime, observations = await asyncio.gather(*tasks)
        return runtime, observations
    except BaseException as failure:
        for task in tasks:
            task.cancel()
        results, _cancellation = await settle_ownership(
            asyncio.gather(*tasks, return_exceptions=True)
        )
        cleanup = process_cleanup_errors(results)
        if cleanup:
            raise cleanup[0] from failure
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
