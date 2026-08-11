"""Call agent-facing routes on a running Studio server."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from urllib.parse import quote

from marimo_studio._agent_protocol import (
    parse_activation_result,
    parse_analysis_report,
    parse_connection_token,
    parse_observation_response,
)
from marimo_studio._agent_transport import (
    StudioServerConnection,
    request_json,
    studio_server_connection,
)
from marimo_studio._runtime_limits import (
    DEFAULT_RUNTIME_TIMEOUT,
    runtime_process_timeout,
)
from marimo_studio._urls import SUPPORT_PATH
from marimo_studio.agent_models import (
    AnalysisReport,
    BrowserObservation,
    ViewActivationResult,
)
from marimo_studio.errors import AgentRequestError, ProtocolError

_STATIC_ANALYSIS_BUDGET = 15.0
_TRANSPORT_GRACE = 5.0


async def request_view_activation(
    connection: StudioServerConnection,
    notebook: Path,
    view: str,
) -> ViewActivationResult:
    """Select one view in the browser attached to the calling code session."""
    connection = await _authorized_connection(connection, notebook)
    payload = await request_json(
        connection,
        f"{SUPPORT_PATH}/views/{quote(view, safe='')}/activate",
        method="PATCH",
    )
    _require_notebook(payload, notebook)
    return parse_activation_result(payload, notebook, view)


async def request_analysis(
    connection: StudioServerConnection,
    notebook: Path,
    *,
    view_name: str | None = None,
    timeout: float = 10.0,
    runtime_timeout: float = DEFAULT_RUNTIME_TIMEOUT,
    require_browser: bool = True,
) -> AnalysisReport:
    """Run bounded Studio analysis through the active notebook server."""
    connection = await _authorized_connection(connection, notebook)
    payload = await request_json(
        connection,
        f"{SUPPORT_PATH}/analyze",
        method="POST",
        body={
            "view": view_name,
            "timeout": timeout,
            "runtime_timeout": runtime_timeout,
            "require_browser": require_browser,
            "browser_client": connection.browser_client or None,
        },
        timeout=(
            max(timeout, runtime_process_timeout(runtime_timeout))
            + _STATIC_ANALYSIS_BUDGET
            + _TRANSPORT_GRACE
        ),
    )
    _require_notebook(payload, notebook)
    report = parse_analysis_report(payload)
    if view_name is not None and report.views != (view_name,):
        raise ProtocolError("The Studio analysis response is invalid.")
    if connection.session_id and any(
        observation.session_id is not None
        and observation.session_id != connection.session_id
        for observation in report.browser_observations
    ):
        raise ProtocolError("The Studio analysis response targets another session.")
    return report


async def observe_browser_views(
    connection: StudioServerConnection,
    notebook: Path,
    views: tuple[str, ...],
    *,
    revisions: dict[str, str],
    runtime: str | None = None,
    timeout: float = 10.0,
) -> tuple[BrowserObservation, ...]:
    """Request fresh rendered evidence from one connected Studio browser."""
    connection = await _authorized_connection(connection, notebook)
    payload = await request_json(
        connection,
        f"{SUPPORT_PATH}/observations",
        method="POST",
        body={
            "schema": 1,
            "views": list(views),
            "revisions": revisions,
            "runtime": runtime,
            "timeout": timeout,
            "browserClient": connection.browser_client or None,
        },
        timeout=min(315.0, timeout + 15.0),
    )
    _require_notebook(payload, notebook)
    return parse_observation_response(payload, views)


async def _authorized_connection(
    connection: StudioServerConnection,
    notebook: Path,
) -> StudioServerConnection:
    if connection.server_token:
        return connection
    payload = await request_json(
        connection,
        f"{SUPPORT_PATH}/agent/connection",
    )
    _require_notebook(payload, notebook)
    return replace(
        connection,
        server_token=parse_connection_token(payload, notebook),
    )


def _require_notebook(payload: dict[str, object], notebook: Path) -> None:
    reported = payload.get("notebook")
    if not isinstance(reported, str) or Path(reported).resolve() != notebook.resolve():
        raise AgentRequestError(
            "notebook-mismatch",
            "The Studio server is attached to a different notebook.",
        )


__all__ = [
    "StudioServerConnection",
    "observe_browser_views",
    "request_analysis",
    "request_view_activation",
    "studio_server_connection",
]
