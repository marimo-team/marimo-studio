"""Call agent-facing routes on a running Studio server."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from urllib.parse import quote

from marimo_studio._delivery.urls import SUPPORT_PATH
from marimo_studio._processes.limits import runtime_process_timeout
from marimo_studio._validation.analysis import AnalysisReport, AnalysisRequest
from marimo_studio._validation.evidence import BrowserObservation
from marimo_studio._workspace.models import StudioWorkspace
from marimo_studio.agent._limits import VIEW_ACTIVATION_HTTP_TIMEOUT
from marimo_studio.agent._protocol import (
    ViewActivationRequest,
    parse_activation_result,
    parse_analysis_report,
    parse_connection_token,
    parse_observation_response,
)
from marimo_studio.agent._records import ViewActivationResult
from marimo_studio.agent._transport import (
    StudioServerConnection,
    request_json,
)
from marimo_studio.agent._transport import (
    studio_server_connection as studio_server_connection,
)
from marimo_studio.errors import AgentRequestError, CapabilityInputError, ProtocolError

_STATIC_ANALYSIS_BUDGET = 15.0
_TRANSPORT_GRACE = 5.0


async def request_view_activation(
    connection: StudioServerConnection,
    notebook: Path,
    request: ViewActivationRequest,
) -> ViewActivationResult:
    """Select one view in a session-bound or external Studio browser."""
    if connection.session_id and request.browser_client:
        raise CapabilityInputError(
            "invalid-activation-request",
            "browser_client",
            "Session-bound activation cannot select another browser client",
        )
    connection = await _authorized_connection(connection, notebook)
    payload = await request_json(
        connection,
        f"{SUPPORT_PATH}/views/{quote(request.view, safe='')}/activate",
        method="PATCH",
        body=request.to_dict(),
        timeout=VIEW_ACTIVATION_HTTP_TIMEOUT,
    )
    _require_notebook(payload, notebook)
    result = parse_activation_result(payload, notebook, request.view)
    if connection.session_id and result.session_id != connection.session_id:
        raise ProtocolError("The Studio activation response targets another session.")
    if request.browser_client and result.client_id != request.browser_client:
        raise ProtocolError("The Studio activation response targets another browser.")
    return result


async def activate_view(
    studio: StudioWorkspace,
    connection: StudioServerConnection,
    name: str,
) -> ViewActivationResult:
    """Select a configured view in one connected Studio browser."""
    return await request_view_activation(
        connection,
        studio.notebook,
        ViewActivationRequest(
            view=name,
            browser_client=connection.browser_client or None,
        ),
    )


async def request_analysis(
    connection: StudioServerConnection,
    notebook: Path,
    request: AnalysisRequest,
) -> AnalysisReport:
    """Run bounded Studio analysis through the active notebook server."""
    if connection.browser_client:
        if request.browser_client not in {None, connection.browser_client}:
            raise CapabilityInputError(
                "invalid-analysis-request",
                "browser_client",
                "The request and connection select different browser clients",
            )
        request = replace(request, browser_client=connection.browser_client)
    connection = await _authorized_connection(connection, notebook)
    payload = await request_json(
        connection,
        f"{SUPPORT_PATH}/analyze",
        method="POST",
        body=request.to_dict(),
        timeout=(
            max(
                request.browser_timeout,
                runtime_process_timeout(request.runtime_timeout),
            )
            + _STATIC_ANALYSIS_BUDGET
            + _TRANSPORT_GRACE
        ),
    )
    _require_notebook(payload, notebook)
    report = parse_analysis_report(payload)
    if request.view is not None and report.views != (request.view,):
        raise ProtocolError("The Studio analysis response is invalid.")
    if report.browser_required != request.require_browser:
        raise ProtocolError("The Studio analysis response is invalid.")
    if connection.session_id and any(
        observation.session_id is not None
        and observation.session_id != connection.session_id
        for observation in report.browser_observations
    ):
        raise ProtocolError("The Studio analysis response targets another session.")
    if request.browser_client and any(
        observation.client_id is not None
        and observation.client_id != request.browser_client
        for observation in report.browser_observations
    ):
        raise ProtocolError("The Studio analysis response targets another browser.")
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
    observations = parse_observation_response(payload, views)
    if any(
        observation.revision != revisions.get(observation.view)
        for observation in observations
    ):
        raise ProtocolError("The Studio observation response targets another revision.")
    if runtime is not None and any(
        observation.runtime != runtime for observation in observations
    ):
        raise ProtocolError("The Studio observation response targets another runtime.")
    if connection.browser_client and any(
        observation.client_id != connection.browser_client
        for observation in observations
    ):
        raise ProtocolError("The Studio observation response targets another browser.")
    return observations


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
