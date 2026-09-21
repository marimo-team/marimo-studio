"""Progressive validation shared by CLI and code-mode adapters."""

from __future__ import annotations

import asyncio
from pathlib import Path

from marimo_studio._processes.limits import DEFAULT_RUNTIME_TIMEOUT
from marimo_studio._validation.records import ValidationLevel, ValidationReport
from marimo_studio._validation.runtime_process import check_runtime_studio_isolated
from marimo_studio._validation.service import validate_studio
from marimo_studio._workspace import load_studio
from marimo_studio._workspace.models import StudioWorkspace
from marimo_studio.errors import (
    ViewGenerationConflictError,
    WorkspaceGenerationConflictError,
)


def _require_owner(
    studio: StudioWorkspace,
    view: str | None,
    expected_catalog_generation: str | None,
    expected_generation: str | None,
) -> None:
    if view is not None:
        current_generation = studio.view_generations.get(view)
        if (
            expected_generation is not None
            and current_generation != expected_generation
        ):
            raise ViewGenerationConflictError(view, current_generation)
    if (
        expected_catalog_generation is not None
        and studio.catalog_generation != expected_catalog_generation
    ):
        raise WorkspaceGenerationConflictError()


async def validate(
    notebook: Path,
    *,
    level: ValidationLevel = "static",
    view: str | None = None,
    runtime_timeout: float = DEFAULT_RUNTIME_TIMEOUT,
    expected_catalog_generation: str | None = None,
    expected_generation: str | None = None,
) -> ValidationReport:
    """Validate saved source or isolated notebook execution."""
    if level not in {"static", "runtime"}:
        raise ValueError("level must be static or runtime")
    studio = await asyncio.to_thread(load_studio, notebook)
    _require_owner(
        studio,
        view,
        expected_catalog_generation,
        expected_generation,
    )
    revalidate_owner = (
        expected_catalog_generation is not None or expected_generation is not None
    )
    expected_generations = (
        {view: expected_generation}
        if view is not None and expected_generation is not None
        else None
    )
    report = (
        await validate_studio(
            studio,
            level="runtime" if level == "runtime" else "static",
            view_name=view,
            runtime_timeout=runtime_timeout,
            runtime_checker=check_runtime_studio_isolated,
            expected_generations=expected_generations,
        )
    ).report
    if revalidate_owner:
        current = await asyncio.to_thread(load_studio, notebook)
        _require_owner(
            current,
            view,
            expected_catalog_generation,
            expected_generation,
        )
    return report
