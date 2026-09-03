"""Call authoring routes on a running Studio server."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from urllib.parse import quote

from marimo_studio._browser_client.limits import VIEW_ACTIVATION_HTTP_TIMEOUT
from marimo_studio._browser_client.protocol import (
    ViewShowRequest,
    parse_connection_token,
    parse_observation_response,
    parse_show_result,
    parse_validation_evidence,
)
from marimo_studio._browser_client.records import ShowResult
from marimo_studio._browser_client.transport import (
    StudioServerConnection,
    request_json,
)
from marimo_studio._browser_client.transport import (
    studio_server_connection as studio_server_connection,
)
from marimo_studio._delivery.urls import SUPPORT_PATH
from marimo_studio._processes.limits import runtime_process_timeout
from marimo_studio._validation.evidence import BrowserObservation, ValidationEvidence
from marimo_studio._validation.progressive import ValidationRequest
from marimo_studio._workspace.models import StudioWorkspace
from marimo_studio._workspace.ownership import ObservedViewOwner, require_view_owner
from marimo_studio.errors import AgentRequestError, CapabilityInputError, ProtocolError

_STATIC_VALIDATION_BUDGET = 15.0
_TRANSPORT_GRACE = 5.0


async def request_view_show(
    connection: StudioServerConnection,
    notebook: Path,
    request: ViewShowRequest,
) -> ShowResult:
    """Select one view in a session-bound or external Studio browser."""
    if connection.session_id and request.browser_client:
        raise CapabilityInputError(
            "invalid-show-request",
            "browser_client",
            "A session-bound show request cannot select another browser client",
        )
    connection = await _authorized_connection(connection, notebook)
    payload = await request_json(
        connection,
        f"{SUPPORT_PATH}/views/{quote(request.view, safe='')}/show",
        method="PATCH",
        body=request.to_dict(),
        timeout=VIEW_ACTIVATION_HTTP_TIMEOUT,
    )
    _require_notebook(payload, notebook)
    result = parse_show_result(payload, notebook, request.view)
    if connection.session_id and result.session_id != connection.session_id:
        raise ProtocolError("The Studio show response targets another session.")
    if request.browser_client and result.client_id != request.browser_client:
        raise ProtocolError("The Studio show response targets another browser.")
    return result


async def show_view(
    studio: StudioWorkspace,
    connection: StudioServerConnection,
    name: str,
    *,
    owner: ObservedViewOwner | None = None,
) -> ShowResult:
    """Select a configured view in one connected Studio browser."""
    require_view_owner(studio, name, owner)
    return await request_view_show(
        connection,
        studio.notebook,
        ViewShowRequest(
            view=name,
            browser_client=connection.browser_client or None,
            owner=owner,
        ),
    )


async def request_browser_validation(
    connection: StudioServerConnection,
    notebook: Path,
    request: ValidationRequest,
) -> ValidationEvidence:
    """Run bounded browser validation through the active notebook server."""
    if connection.browser_client:
        if request.browser_client not in {None, connection.browser_client}:
            raise CapabilityInputError(
                "invalid-validation-request",
                "browser_client",
                "The request and connection select different browser clients",
            )
        request = replace(request, browser_client=connection.browser_client)
    connection = await _authorized_connection(connection, notebook)
    payload = await request_json(
        connection,
        f"{SUPPORT_PATH}/validate",
        method="POST",
        body=request.to_dict(),
        timeout=(
            max(
                request.browser_timeout,
                runtime_process_timeout(request.runtime_timeout),
            )
            + _STATIC_VALIDATION_BUDGET
            + _TRANSPORT_GRACE
        ),
    )
    _require_notebook(payload, notebook)
    report = parse_validation_evidence(payload)
    if request.view is not None and report.views != (request.view,):
        raise ProtocolError("The Studio validation response is invalid.")
    if report.browser_required != request.require_browser:
        raise ProtocolError("The Studio validation response is invalid.")
    if connection.session_id and any(
        observation.session_id is not None
        and observation.session_id != connection.session_id
        for observation in report.browser_observations
    ):
        raise ProtocolError("The Studio validation response targets another session.")
    if request.browser_client and any(
        observation.client_id is not None
        and observation.client_id != request.browser_client
        for observation in report.browser_observations
    ):
        raise ProtocolError("The Studio validation response targets another browser.")
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
