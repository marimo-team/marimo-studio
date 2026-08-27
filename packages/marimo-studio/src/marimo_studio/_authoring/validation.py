"""Progressive validation shared by CLI and code-mode adapters."""

from __future__ import annotations

import asyncio
from pathlib import Path

from marimo_studio._browser_client.client import (
    observe_browser_views,
    request_analysis,
)
from marimo_studio._browser_client.transport import StudioServerConnection
from marimo_studio._processes.limits import DEFAULT_RUNTIME_TIMEOUT
from marimo_studio._validation.analysis import AnalysisRequest, analyze_studio
from marimo_studio._validation.limits import DEFAULT_BROWSER_TIMEOUT
from marimo_studio._validation.records import ValidationLevel, ValidationReport
from marimo_studio._validation.runtime_process import check_runtime_studio_isolated
from marimo_studio._validation.service import validate_studio
from marimo_studio._workspace import load_studio
from marimo_studio._workspace.models import StudioWorkspace
from marimo_studio.errors import ProtocolError


async def validate(
    notebook: Path,
    *,
    level: ValidationLevel = "static",
    view: str | None = None,
    connection: StudioServerConnection | None = None,
    browser_timeout: float = DEFAULT_BROWSER_TIMEOUT,
    runtime_timeout: float = DEFAULT_RUNTIME_TIMEOUT,
) -> ValidationReport:
    """Validate saved source, isolated execution, or rendered browser evidence."""
    if level not in {"static", "runtime", "browser"}:
        raise ValueError("level must be static, runtime, or browser")
    studio = await asyncio.to_thread(load_studio, notebook)
    if level != "browser":
        return (
            await validate_studio(
                studio,
                level="runtime" if level == "runtime" else "static",
                view_name=view,
                runtime_timeout=runtime_timeout,
                runtime_checker=check_runtime_studio_isolated,
            )
        ).report
    if connection is None:
        raise ProtocolError("Browser validation requires an attached Studio browser.")
    request = AnalysisRequest(
        view=view,
        browser_timeout=browser_timeout,
        runtime_timeout=runtime_timeout,
        require_browser=True,
        browser_client=connection.browser_client or None,
    )
    if connection.session_id:
        request.require_focused_view()
        analysis = await request_analysis(connection, notebook, request)
    else:
        analysis = await _analyze_connected(studio, connection, request)
    return ValidationReport.from_analysis(analysis)


async def _analyze_connected(
    studio: StudioWorkspace,
    connection: StudioServerConnection,
    request: AnalysisRequest,
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

    return await analyze_studio(
        studio,
        request.options,
        observe_browser=observe,
        runtime_checker=check_runtime_studio_isolated,
    )
