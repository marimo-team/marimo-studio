"""Call authoring routes on a running Studio server."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from urllib.parse import quote

from marimo_studio._browser_client.limits import (
    VIEW_ACTIVATION_HTTP_TIMEOUT,
    VIEW_REMOVAL_HTTP_TIMEOUT,
)
from marimo_studio._browser_client.protocol import (
    ViewShowRequest,
    parse_connection_token,
    parse_removal_result,
    parse_show_result,
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
from marimo_studio._views.api import ViewRemovalResult
from marimo_studio._workspace.models import StudioWorkspace
from marimo_studio._workspace.ownership import ObservedViewOwner, require_view_owner
from marimo_studio.errors import (
    AgentRequestError,
    CapabilityInputError,
    ProtocolError,
    ViewDeletionError,
)


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


async def request_view_removal(
    connection: StudioServerConnection,
    notebook: Path,
    view: str,
    *,
    catalog_generation: str,
    view_generation: str,
) -> ViewRemovalResult:
    """Remove one view through the server that serves its artifacts."""
    connection = await _authorized_connection(connection, notebook)
    payload = await request_json(
        connection,
        f"{SUPPORT_PATH}/views/{quote(view, safe='')}",
        method="DELETE",
        body={
            "catalog_generation": catalog_generation,
            "name": view,
            "view_generation": view_generation,
        },
        timeout=VIEW_REMOVAL_HTTP_TIMEOUT,
    )
    cleanup = payload.get("cleanup")
    if isinstance(cleanup, str) and cleanup:
        raise ViewDeletionError(Path(cleanup))
    return parse_removal_result(payload, notebook, view)


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
