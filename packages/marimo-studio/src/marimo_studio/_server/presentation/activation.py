"""Select a Studio browser and activate one authored view."""

from __future__ import annotations

from dataclasses import dataclass

from marimo_studio._browser_client.limits import VIEW_ACTIVATION_TIMEOUT
from marimo_studio._browser_client.records import ViewActivationResult
from marimo_studio._server.agent.clients import PeerTarget
from marimo_studio._server.notebook_scope import NotebookScope
from marimo_studio._server.ports import SessionState
from marimo_studio._server.records import ServerContext
from marimo_studio._workspace.models import StudioWorkspace
from marimo_studio.errors import AgentRequestError, ViewNotFoundError

_CLIENT_CONNECT_TIMEOUT = 1.0


@dataclass(frozen=True)
class SessionViewTarget:
    session_id: str


@dataclass(frozen=True)
class BrowserViewTarget:
    client_id: str | None


ViewTarget = SessionViewTarget | BrowserViewTarget


async def activate_studio_view(
    context: ServerContext,
    studio: StudioWorkspace,
    notebook_scope: NotebookScope,
    sessions: SessionState,
    view_name: str,
    target: ViewTarget,
) -> ViewActivationResult:
    """Activate one view for a session or selected browser client."""
    if view_name not in studio.views:
        raise ViewNotFoundError(view_name, available=tuple(studio.views))

    if isinstance(target, SessionViewTarget):
        return await _activate_session_view(
            context,
            studio,
            notebook_scope,
            sessions,
            view_name,
            target.session_id,
        )

    browser = await notebook_scope.clients.select_target(client_id=target.client_id)
    session_id = browser.session_id
    if session_id is None or not sessions.exists(context, session_id):
        raise AgentRequestError(
            "browser-session-unavailable",
            "The selected Studio browser has no active Marimo session.",
            status_code=409,
        )
    return await _activate_connected_view(
        studio,
        notebook_scope,
        view_name,
        browser,
        session_id,
    )


async def _activate_session_view(
    context: ServerContext,
    studio: StudioWorkspace,
    notebook_scope: NotebookScope,
    sessions: SessionState,
    view_name: str,
    session_id: str,
) -> ViewActivationResult:
    if not sessions.exists(context, session_id):
        raise AgentRequestError(
            "unknown-session",
            "View activation requires the active Marimo session.",
            status_code=409,
        )
    target = await notebook_scope.clients.wait_for_session_target(
        session_id,
        _CLIENT_CONNECT_TIMEOUT,
    )
    if target is not None:
        return await _activate_connected_view(
            studio,
            notebook_scope,
            view_name,
            target,
            session_id,
        )

    retained = await notebook_scope.clients.binding_for_session(session_id)
    if retained is not None:
        raise AgentRequestError(
            "browser-client-unavailable",
            "The Studio browser is reconnecting. Retry view activation shortly.",
            status_code=409,
        )
    raise AgentRequestError(
        "browser-client-unavailable",
        "The Studio host for this Marimo session is not connected.",
        status_code=409,
    )


async def _activate_connected_view(
    studio: StudioWorkspace,
    notebook_scope: NotebookScope,
    view_name: str,
    target: PeerTarget,
    session_id: str,
) -> ViewActivationResult:
    activation = await notebook_scope.agents.activate(target, view_name)
    await notebook_scope.agents.wait_for_activation(
        activation,
        VIEW_ACTIVATION_TIMEOUT,
    )
    return ViewActivationResult(
        notebook=studio.notebook,
        view=view_name,
        generation=activation.generation,
        session_id=session_id,
        client_id=target.client_id,
    )
