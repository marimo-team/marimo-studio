"""Assign one server-authored runtime session to a presentation document."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from starlette.requests import Request
from starlette.responses import RedirectResponse

from marimo_studio._delivery.urls import (
    DOCUMENT_REPLAY_QUERY_PARAM,
    EDITOR_BINDING_CAPABILITY_QUERY_PARAM,
    PRESENTATION_RENEWAL_QUERY_PARAM,
    WORKSPACE_EVENTS_CAPABILITY_QUERY_PARAM,
)
from marimo_studio._server.ports import SessionState
from marimo_studio._server.presentation.capability import (
    PresentationCapabilityRoute,
    capability_matches,
    parse_presentation_capability,
    presentation_renewal_capability,
)
from marimo_studio._server.presentation.session_ids import SessionIdAllocator
from marimo_studio._server.records import ServerContext


@dataclass(frozen=True)
class PresentationSession:
    """The server-assigned presentation and native runtime sessions."""

    session_id: str
    runtime_session_id: str
    renewal_token: str


def resolve_presentation_session(
    request: Request,
    context: ServerContext,
    view_name: str,
    capability_route: PresentationCapabilityRoute | None,
) -> PresentationSession | None:
    """Resolve a session from signed server state, never caller input alone."""
    if capability_route is not None:
        capability = capability_route.capability
        if capability.kind != "renewal":
            return None
        runtime_session_id = capability.runtime_session_id
        if runtime_session_id is None:
            return None
        return PresentationSession(
            capability.session_id,
            runtime_session_id,
            presentation_renewal_capability(
                context,
                view_name,
                capability.session_id,
                runtime_session_id,
            ),
        )
    token = request.query_params.get(PRESENTATION_RENEWAL_QUERY_PARAM)
    if token is None:
        return None
    capability = parse_presentation_capability(token)
    if (
        capability is None
        or capability.kind != "renewal"
        or capability.view != view_name
        or not capability_matches(capability, context)
    ):
        return None
    runtime_session_id = capability.runtime_session_id
    if runtime_session_id is None:
        return None
    return PresentationSession(capability.session_id, runtime_session_id, token)


def presentation_session_redirect(
    request: Request,
    context: ServerContext,
    view_name: str,
    sessions: SessionState,
    session_ids: SessionIdAllocator,
    *,
    preserve_session: bool,
) -> RedirectResponse:
    """Commit server-owned presentation and native sessions to a signed URL."""
    presentation_session, replay = _assign_presentation_session(
        request,
        context,
        view_name,
        sessions,
        session_ids,
        preserve_session=preserve_session,
    )
    parts = urlsplit(str(request.url))
    query = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if key
        not in {
            DOCUMENT_REPLAY_QUERY_PARAM,
            EDITOR_BINDING_CAPABILITY_QUERY_PARAM,
            PRESENTATION_RENEWAL_QUERY_PARAM,
            WORKSPACE_EVENTS_CAPABILITY_QUERY_PARAM,
            "session_id",
        }
    ]
    query.extend(
        (
            (PRESENTATION_RENEWAL_QUERY_PARAM, presentation_session.renewal_token),
            ("session_id", presentation_session.runtime_session_id),
        )
    )
    if replay:
        query.append((DOCUMENT_REPLAY_QUERY_PARAM, "1"))
    target = urlunsplit((*parts[:3], urlencode(query), parts.fragment))
    return RedirectResponse(target, status_code=307)


def assign_presentation_session(
    request: Request,
    context: ServerContext,
    view_name: str,
    sessions: SessionState,
    session_ids: SessionIdAllocator,
    *,
    preserve_session: bool,
) -> PresentationSession:
    """Assign a server-owned presentation and native runtime pair."""
    presentation, _replay = _assign_presentation_session(
        request,
        context,
        view_name,
        sessions,
        session_ids,
        preserve_session=preserve_session,
    )
    return presentation


def valid_presentation_replay(
    request: Request,
    context: ServerContext,
    presentation: PresentationSession,
    sessions: SessionState,
    *,
    preserve_session: bool,
) -> bool:
    """Validate a stored renewal against the current native session."""
    return _runtime_replay_matches(
        request,
        context,
        sessions,
        presentation.runtime_session_id,
        preserve_session=preserve_session,
    )


def _assign_presentation_session(
    request: Request,
    context: ServerContext,
    view_name: str,
    sessions: SessionState,
    session_ids: SessionIdAllocator,
    *,
    preserve_session: bool,
) -> tuple[PresentationSession, bool]:
    runtime_session_id = _replay_runtime_session(
        request,
        context,
        sessions,
        preserve_session=preserve_session,
    )
    replay = runtime_session_id is not None
    if runtime_session_id is None:
        session_id, runtime_session_id = session_ids.assign_pair(
            context,
            sessions,
            view_name,
        )
    else:
        session_id = session_ids.assign_existing(
            context,
            sessions,
            view_name,
            runtime_session_id,
        )
    token = presentation_renewal_capability(
        context,
        view_name,
        session_id,
        runtime_session_id,
    )
    return PresentationSession(session_id, runtime_session_id, token), replay


def _replay_runtime_session(
    request: Request,
    context: ServerContext,
    sessions: SessionState,
    *,
    preserve_session: bool,
) -> str | None:
    requested = request.query_params.getlist("session_id")
    if len(requested) != 1:
        return None
    runtime_session_id = requested[0]
    return (
        runtime_session_id
        if _runtime_replay_matches(
            request,
            context,
            sessions,
            runtime_session_id,
            preserve_session=preserve_session,
        )
        else None
    )


def _runtime_replay_matches(
    request: Request,
    context: ServerContext,
    sessions: SessionState,
    runtime_session_id: str,
    *,
    preserve_session: bool,
) -> bool:
    return (
        context.mode == "run"
        and preserve_session
        and request.query_params.getlist(DOCUMENT_REPLAY_QUERY_PARAM) == ["1"]
        and request.query_params.getlist("session_id") == [runtime_session_id]
        and sessions.is_session_id(runtime_session_id)
        and sessions.exists(context, runtime_session_id)
        and sessions.matches_creation_query(
            context,
            runtime_session_id,
            request.query_params.multi_items(),
        )
    )
