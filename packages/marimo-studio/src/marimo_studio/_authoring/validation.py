"""Progressive validation shared by CLI and code-mode adapters."""

from __future__ import annotations

import asyncio
from pathlib import Path

from marimo_studio._browser_client.client import (
    observe_browser_views,
    request_browser_validation,
)
from marimo_studio._browser_client.transport import StudioServerConnection
from marimo_studio._processes.limits import DEFAULT_RUNTIME_TIMEOUT
from marimo_studio._validation.limits import DEFAULT_BROWSER_TIMEOUT
from marimo_studio._validation.progressive import (
    ValidationRequest,
    validate_progressively,
)
from marimo_studio._validation.records import ValidationLevel, ValidationReport
from marimo_studio._validation.runtime_process import check_runtime_studio_isolated
from marimo_studio._validation.service import validate_studio
from marimo_studio._workspace import load_studio
from marimo_studio._workspace.models import StudioWorkspace
from marimo_studio.errors import (
    ProtocolError,
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
    connection: StudioServerConnection | None = None,
    browser_timeout: float = DEFAULT_BROWSER_TIMEOUT,
    runtime_timeout: float = DEFAULT_RUNTIME_TIMEOUT,
    expected_catalog_generation: str | None = None,
    expected_generation: str | None = None,
) -> ValidationReport:
    """Validate saved source, isolated execution, or rendered browser evidence."""
    if level not in {"static", "runtime", "browser"}:
        raise ValueError("level must be static, runtime, or browser")
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
    if level != "browser":
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
    if connection is None:
        raise ProtocolError("Browser validation requires an attached Studio browser.")
    request = ValidationRequest(
        view=view,
        browser_timeout=browser_timeout,
        runtime_timeout=runtime_timeout,
        require_browser=True,
        browser_client=connection.browser_client or None,
        catalog_generation=expected_catalog_generation,
        view_generation=expected_generation,
    )
    if connection.session_id:
        request.require_focused_view()
        evidence = await request_browser_validation(connection, notebook, request)
    else:
        evidence = await _validate_connected(
            studio,
            connection,
            request,
            expected_catalog_generation,
            expected_generations,
        )
    report = ValidationReport.from_evidence(evidence)
    if revalidate_owner:
        current = await asyncio.to_thread(load_studio, notebook)
        _require_owner(
            current,
            view,
            expected_catalog_generation,
            expected_generation,
        )
    return report


async def _validate_connected(
    studio: StudioWorkspace,
    connection: StudioServerConnection,
    request: ValidationRequest,
    expected_catalog_generation: str | None,
    expected_generations: dict[str, str] | None,
):
    async def observe(
        _selected: object,
        views: tuple[str, ...],
        revisions: dict[str, str],
    ):
        return await observe_browser_views(
            connection,
            studio.notebook,
            views,
            revisions=revisions,
            runtime=studio.default_runtime,
            timeout=request.browser_timeout,
        )

    return await validate_progressively(
        studio,
        request.options,
        observe_browser=observe,
        runtime_checker=check_runtime_studio_isolated,
        expected_catalog_generation=expected_catalog_generation,
        expected_generations=expected_generations,
    )
