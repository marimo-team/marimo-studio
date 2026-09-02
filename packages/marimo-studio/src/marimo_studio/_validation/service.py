"""Validate selected views against source that stays unchanged during the run.

Validation captures the selected views' source revisions, inspects their
notebook mounts, runs static checks, and optionally executes the complete
notebook in an isolated runtime. Live-development validation first publishes
the presentation revisions being checked.

Source identity is checked again after each later stage. A concurrent edit
becomes an explicit stale-source result instead of mixing static evidence from
one revision with runtime evidence from another. CLI and agent workflows share
these check results, while browser validation adds rendered observations on top.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
from functools import partial
from typing import TYPE_CHECKING, Literal

from marimo_studio._processes.limits import DEFAULT_RUNTIME_TIMEOUT
from marimo_studio._processes.provider_operation import (
    raise_process_cleanup,
    run_provider_operation,
)
from marimo_studio._validation.ownership import require_validation_owner
from marimo_studio._validation.ports import RuntimeChecker
from marimo_studio._validation.records import ValidationReport
from marimo_studio._validation.results import CheckResult
from marimo_studio._validation.static import CheckReport, check_studio
from marimo_studio._views.presentation_publication import publish_presentation
from marimo_studio._views.revisions import (
    PreparedViewProject,
    capture_presentations,
    capture_published_presentations,
    capture_source_revisions,
)
from marimo_studio._workspace import load_studio
from marimo_studio._workspace.models import StudioWorkspace
from marimo_studio.errors import MarimoStudioError, ViewNotFoundError

if TYPE_CHECKING:
    from marimo_studio._server.development.coordinator import DevelopmentCoordinator

ValidationStage = Literal["static", "runtime"]


@dataclass(frozen=True)
class ValidationPreparation:
    """One revision-coherent static stage shared by every validation adapter."""

    views: tuple[str, ...]
    view_name: str | None
    revisions: dict[str, str]
    source_revisions: dict[str, str]
    static: CheckReport
    dynamic_browser_required: bool
    source_stable: bool


@dataclass(frozen=True)
class RuntimeValidation:
    """Runtime checks and the reason they were skipped, when applicable."""

    checks: tuple[CheckResult, ...]
    skipped: str | None


@dataclass(frozen=True)
class ValidationRun:
    """Typed result retained by adapters that render individual checks."""

    report: ValidationReport
    static: CheckReport
    runtime: tuple[CheckResult, ...]


def _views(studio: StudioWorkspace, view_name: str | None) -> tuple[str, ...]:
    if view_name is None:
        return tuple(studio.views)
    if view_name not in studio.views:
        raise ViewNotFoundError(view_name, available=tuple(studio.views))
    return (view_name,)


def _source_revisions(
    studio: StudioWorkspace,
    views: tuple[str, ...],
) -> dict[str, str]:
    return capture_source_revisions(studio, views)


def _presentation_revisions(
    studio: StudioWorkspace,
    views: tuple[str, ...],
    expected_generations: Mapping[str, str] | None = None,
) -> dict[str, str]:
    with capture_presentations(
        studio,
        views,
        expected_generations=expected_generations,
    ) as snapshot:
        return {view: snapshot.revisions[view] for view in views}


def _published_presentation_revisions(
    studio: StudioWorkspace,
    views: tuple[str, ...],
) -> dict[str, str]:
    snapshot = capture_published_presentations(studio, views)
    if snapshot is None:
        raise RuntimeError("Validation presentation publication is unavailable")
    with snapshot:
        return {view: snapshot.revisions[view] for view in views}


def _try_source_revisions(
    studio: StudioWorkspace,
    views: tuple[str, ...],
) -> tuple[dict[str, str] | None, Exception | None]:
    try:
        return _source_revisions(studio, views), None
    except (KeyError, OSError, MarimoStudioError) as error:
        raise_process_cleanup(error)
        return None, error


def source_revision_check(
    studio: StudioWorkspace,
    message: str,
    *,
    code: Literal["validation-source-changed", "validation-source-unavailable"],
) -> CheckResult:
    """Return the canonical source-coherence failure for every adapter."""
    hint = (
        "Restore the missing source, save it, then rerun validation."
        if code == "validation-source-unavailable"
        else "Wait for the current edits to save, then rerun validation."
    )
    return CheckResult(
        "validation-source-revision",
        "fail",
        message,
        code=code,
        details={
            "source": {"path": str(studio.notebook)},
            "hint": hint,
        },
    )


def _prepare_validation(
    studio: StudioWorkspace,
    view_name: str | None,
    revisions: dict[str, str] | None = None,
    expected_generations: Mapping[str, str] | None = None,
) -> ValidationPreparation:
    from marimo_studio._views.inspection import inspect_view_mounts

    selected = _views(studio, view_name)
    before, before_error = _try_source_revisions(studio, selected)
    try:
        mounts = {view: inspect_view_mounts(studio.views[view]) for view in selected}
    except (OSError, MarimoStudioError, UnicodeError, ValueError) as error:
        raise_process_cleanup(error)
        mounts = None
    static = check_studio(
        studio,
        view_name=view_name,
        _published_mounts=mounts,
    )
    after, after_error = _try_source_revisions(studio, selected)
    source_error = before_error or after_error
    source_stable = source_error is None and before is not None and before == after
    if source_error is not None:
        static = static.extend(
            (
                source_revision_check(
                    studio,
                    f"Studio sources could not be captured: {source_error}",
                    code="validation-source-unavailable",
                ),
            )
        )
    elif not source_stable:
        static = static.extend(
            (
                source_revision_check(
                    studio,
                    "Studio sources changed during static validation.",
                    code="validation-source-changed",
                ),
            )
        )
    source_revisions = after or before or {view: "unavailable" for view in selected}
    try:
        revisions = (
            _presentation_revisions(studio, selected, expected_generations)
            if revisions is None
            else revisions
        )
    except (KeyError, OSError, MarimoStudioError) as error:
        raise_process_cleanup(error)
        revisions = {view: "unavailable" for view in selected}
        if static.ok:
            static = static.extend(
                (
                    CheckResult(
                        "validation-page-revision",
                        "fail",
                        f"Studio presentations could not be captured: {error}",
                        code="validation-page-unavailable",
                        details={
                            "source": {"path": str(studio.notebook)},
                            "hint": (
                                "Fix the view build diagnostics, publish it, then "
                                "rerun validation."
                            ),
                        },
                    ),
                )
            )
    dynamic_browser_required = mounts is not None and any(
        site.allowed_targets is None for sites in mounts.values() for site in sites
    )
    return ValidationPreparation(
        views=selected,
        view_name=view_name,
        revisions=revisions,
        source_revisions=source_revisions,
        static=static,
        dynamic_browser_required=dynamic_browser_required,
        source_stable=source_stable,
    )


async def prepare_validation(
    studio: StudioWorkspace,
    *,
    view_name: str | None,
    development: DevelopmentCoordinator | None = None,
    expected_catalog_generation: str | None = None,
    expected_generations: Mapping[str, str] | None = None,
) -> ValidationPreparation:
    """Capture source identity and run the canonical static stage."""
    revisions = (
        None
        if development is None
        else await _publish_validation_presentations(
            studio,
            view_name,
            development,
            expected_catalog_generation=expected_catalog_generation,
            expected_generations=expected_generations,
        )
    )
    return await run_provider_operation(
        partial(
            _prepare_validation,
            studio,
            view_name,
            revisions,
            expected_generations,
        )
    )


async def _publish_validation_presentations(
    studio: StudioWorkspace,
    view_name: str | None,
    development: DevelopmentCoordinator,
    *,
    expected_catalog_generation: str | None = None,
    expected_generations: Mapping[str, str] | None = None,
) -> dict[str, str]:
    views = _views(studio, view_name)
    for view in views:
        catalog = await development.project_catalog(studio, view)
        prepared = PreparedViewProject(catalog.inspection, catalog.input_id)
        await development.publish(
            view,
            catalog.generation,
            partial(
                publish_presentation,
                studio,
                view,
                prepared,
                expected_catalog_generation=expected_catalog_generation,
                expected_generation=(
                    expected_generations.get(view)
                    if expected_generations is not None
                    else None
                ),
            ),
        )
        if expected_catalog_generation is not None or expected_generations is not None:
            current = await asyncio.to_thread(load_studio, studio.config_path)
            require_validation_owner(
                current,
                expected_catalog_generation=expected_catalog_generation,
                expected_generations=expected_generations,
            )
    return await asyncio.to_thread(_published_presentation_revisions, studio, views)


async def verify_source_revisions(
    studio: StudioWorkspace,
    preparation: ValidationPreparation,
    *,
    phase: Literal["runtime validation", "validation"],
) -> CheckResult | None:
    """Compare current sources with the stage's accepted revision identity."""
    current, error = await run_provider_operation(
        partial(
            _try_source_revisions,
            studio,
            preparation.views,
        )
    )
    if error is not None:
        return source_revision_check(
            studio,
            f"Studio sources could not be captured after {phase}: {error}",
            code="validation-source-unavailable",
        )
    if current != preparation.source_revisions:
        return source_revision_check(
            studio,
            f"Studio sources changed while {phase} was running.",
            code="validation-source-changed",
        )
    return None


async def run_runtime_validation(
    studio: StudioWorkspace,
    preparation: ValidationPreparation,
    *,
    runtime_timeout: float,
    runtime_checker: RuntimeChecker,
) -> RuntimeValidation:
    """Run the isolated runtime stage against the accepted source revision."""
    if not preparation.static.ok:
        return RuntimeValidation(
            (),
            "Static validation failed. Fix those errors first.",
        )
    checks = await runtime_checker(
        studio,
        view_name=preparation.view_name,
        expected_revisions=preparation.source_revisions,
        timeout=runtime_timeout,
    )
    source_check = await verify_source_revisions(
        studio,
        preparation,
        phase="runtime validation",
    )
    if source_check is not None and not any(
        check.code == source_check.code for check in checks
    ):
        checks = (*checks, source_check)
    return RuntimeValidation(checks, None)


async def validate_studio(
    studio: StudioWorkspace,
    *,
    level: ValidationStage,
    view_name: str | None = None,
    runtime_timeout: float = DEFAULT_RUNTIME_TIMEOUT,
    runtime_checker: RuntimeChecker,
    development: DevelopmentCoordinator | None = None,
    expected_catalog_generation: str | None = None,
    expected_generations: Mapping[str, str] | None = None,
) -> ValidationRun:
    """Run revision-coherent static and optional runtime validation."""
    preparation = await prepare_validation(
        studio,
        view_name=view_name,
        development=development,
        expected_catalog_generation=expected_catalog_generation,
        expected_generations=expected_generations,
    )
    runtime = (
        await run_runtime_validation(
            studio,
            preparation,
            runtime_timeout=runtime_timeout,
            runtime_checker=runtime_checker,
        )
        if level == "runtime"
        else RuntimeValidation((), None)
    )
    return ValidationRun(
        report=ValidationReport.from_checks(
            preparation.static,
            level=level,
            runtime=runtime.checks,
        ),
        static=preparation.static,
        runtime=runtime.checks,
    )
