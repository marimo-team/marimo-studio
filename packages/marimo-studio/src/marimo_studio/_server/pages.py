"""Build Studio page, redirect, and page-level error responses."""

from __future__ import annotations

import re
import secrets
from collections.abc import Sequence
from pathlib import Path
from urllib.parse import urlencode

from starlette.requests import Request
from starlette.responses import (
    HTMLResponse,
    JSONResponse,
    PlainTextResponse,
    RedirectResponse,
    Response,
)

from marimo_studio._delivery.urls import (
    DOCUMENT_LIFECYCLE_QUERY_PARAM,
    DOCUMENT_REPLAY_QUERY_PARAM,
    EDITOR_BINDING_CAPABILITY_QUERY_PARAM,
    EDITOR_SESSION_QUERY_PARAM,
    HOST_SESSION_HANDOFF_QUERY_PARAM,
    PRESENTATION_RENEWAL_QUERY_PARAM,
    PRESENTATION_REVISION_QUERY_PARAM,
    PRIVATE_QUERY_KEYS,
    SERVER_INSTANCE_QUERY_PARAM,
    STUDIO_CLIENT_QUERY_PARAM,
    SUPPORT_PATH,
    UNFRAMED_QUERY_PARAM,
    WORKSPACE_EVENTS_CAPABILITY_QUERY_PARAM,
    relative_url,
    studio_path,
    view_path,
    with_notebook_query,
    with_query,
)
from marimo_studio._server.agent.clients import StudioClientRegistry
from marimo_studio._server.headers import DOCUMENT_HEADERS, edit_document_headers
from marimo_studio._server.ports import SessionReplay, SessionState
from marimo_studio._server.presentation.capability import (
    PRESENTATION_PATH,
    presentation_renewal_path,
    presentation_response_headers,
    presentation_revision_path,
    presentation_storage_scope,
)
from marimo_studio._server.presentation.isolation import (
    isolated_presentation_document,
    isolation_content_security_policy,
)
from marimo_studio._server.presentation.ownership import (
    studio_frame_identity,
    studio_owned_request,
)
from marimo_studio._server.presentation.payload import (
    presentation_support_path,
    render_presentation_document,
)
from marimo_studio._server.presentation.service import NotebookPresentation
from marimo_studio._server.presentation.session import (
    PresentationSession,
    valid_presentation_replay,
)
from marimo_studio._server.presentation.session_ids import SessionIdAllocator
from marimo_studio._server.records import ServerContext
from marimo_studio._server.request_path import request_path, request_reference
from marimo_studio._server.runtime.catalog import RuntimeRegistry
from marimo_studio._server.security import SecurityPolicy
from marimo_studio._server.server_instance import server_instance_id
from marimo_studio._server.studio import (
    repair_document,
    studio_document,
    waiting_document,
)
from marimo_studio._server.studio.session_handoff import (
    host_session_handoff_capability_matches,
)
from marimo_studio._workspace.models import DEFAULT_VIEW_NAME, StudioWorkspace
from marimo_studio.errors import AgentRequestError, MarimoStudioError


def authentication_redirect(request: Request, login_path: str) -> Response:
    """Redirect a Studio page request through Marimo authentication."""
    path = request_path(request)
    query = request.query_params.multi_items()
    if "access_token" in request.query_params:
        stripped = [(key, value) for key, value in query if key != "access_token"]
        target = request_reference(request, with_query(path, stripped))
    else:
        next_url = relative_url(login_path, with_query(path, query))
        target = request_reference(
            request, with_query(login_path, [("next", next_url)])
        )
    return RedirectResponse(target, status_code=303, headers=DOCUMENT_HEADERS)


def page_redirect(request: Request, relative: str, page: bool) -> Response | None:
    """Canonicalize page routes with a trailing slash."""
    if not page or relative.endswith("/"):
        return None
    target = request_reference(
        request,
        with_query(f"{request_path(request)}/", request.query_params.multi_items()),
    )
    return RedirectResponse(target, status_code=307, headers=DOCUMENT_HEADERS)


def run_view_redirect(request: Request, target: str) -> Response:
    """Redirect a workspace path to the view that run mode serves at `target`.

    Marimo's authentication sets its session cookie on this response, so the
    redirect drops `access_token` from the query.
    """
    query = [
        (key, value)
        for key, value in request.query_params.multi_items()
        if key != "access_token"
    ]
    reference = request_reference(request, with_query(target, query))
    return RedirectResponse(reference, status_code=307, headers=DOCUMENT_HEADERS)


def studio_landing_redirect(
    request: Request,
    view_name: str,
    routing_query: Sequence[tuple[str, str]] = (),
) -> Response:
    """Redirect the edit root to its configured Studio workspace."""
    target = request_reference(
        request,
        with_notebook_query(
            studio_path(view_name),
            request.query_params.multi_items(),
            routing_query,
        ),
    )
    return RedirectResponse(target, status_code=307, headers=DOCUMENT_HEADERS)


def authored_document_redirect(
    request: Request,
    context: ServerContext,
    view_name: str,
) -> Response:
    """Canonicalize an authored document route to its public view URL."""
    target = request_reference(
        request,
        with_notebook_query(
            view_path(view_name),
            request.query_params.multi_items(),
            context.routing_query,
        ),
    )
    return RedirectResponse(target, status_code=307, headers=DOCUMENT_HEADERS)


async def document_response(
    request: Request,
    context: ServerContext,
    presentation: NotebookPresentation,
    relative: str,
    view_name: str,
    *,
    sessions: SessionState,
    clients: StudioClientRegistry,
    replay: SessionReplay,
    runtimes: RuntimeRegistry,
    marimo_version: str,
    presentation_session: PresentationSession,
    security_policy: SecurityPolicy,
    trusted_shell: bool = True,
) -> Response:
    """Render one custom view document against the active Marimo server."""
    if request.method not in {"GET", "HEAD"}:
        return Response(status_code=405)
    expected_revisions = request.query_params.getlist(PRESENTATION_REVISION_QUERY_PARAM)
    if expected_revisions and (
        len(expected_revisions) != 1
        or re.fullmatch(r"[0-9a-f]{64}", expected_revisions[0]) is None
    ):
        raise AgentRequestError(
            "invalid-presentation-revision",
            "Specify one presentation revision from an exact preview URL.",
            status_code=400,
        )
    client_id: str | None = None
    selected = None if context.mode == "run" and relative == "/" else view_name
    if expected_revisions:
        snapshot = await presentation.current_published_snapshot_async(
            view_name, profile="development" if context.mode == "edit" else "production"
        )
    elif context.mode == "edit":
        snapshot = await presentation.display_snapshot_async(view_name)
    else:
        snapshot = await presentation.snapshot_async(selected, profile="production")
    runtime, _ = runtimes.select(
        snapshot.resolved.workspace,
        context,
        request.query_params.get("runtime"),
    )
    runtime_explicit = request.query_params.get("runtime") is not None
    same_origin_server = (
        security_policy.trusted_server_runtime and runtime.id == "server"
    )
    if expected_revisions and snapshot.revision != expected_revisions[0]:
        raise AgentRequestError(
            "presentation-revision-mismatch",
            "This exact preview is stale. "
            "Open a new preview URL for the current build.",
            status_code=409,
        )
    if context.mode == "edit":
        if runtime.id == "server" and not sessions.has_notebook_session(context):
            return _waiting_response(
                request,
                context,
                view_name,
                presentation_session,
                head=request.method == "HEAD",
            )
        client_id = request.query_params.get(STUDIO_CLIENT_QUERY_PARAM)
        if client_id is not None:
            session_id = await clients.session_for_client(client_id)
            expected_sessions = request.query_params.getlist(EDITOR_SESSION_QUERY_PARAM)
            # A disconnected editor tab reports no session and waits below.
            if (
                expected_sessions
                and session_id is not None
                and (len(expected_sessions) != 1 or session_id != expected_sessions[0])
            ):
                raise AgentRequestError(
                    "preview-session-changed",
                    "The notebook session changed. Open a new preview URL.",
                    status_code=409,
                )
            if (
                session_id is None
                or not sessions.exists(context, session_id)
                or not sessions.ensure_started(context, session_id)
            ):
                return _waiting_response(
                    request,
                    context,
                    view_name,
                    presentation_session,
                    head=request.method == "HEAD",
                )
    frame_identity = studio_frame_identity(request) if context.mode == "edit" else None
    if frame_identity is not None and frame_identity[0] != client_id:
        frame_identity = None
    replaying = False
    if context.mode == "run" and request.query_params.getlist(
        DOCUMENT_REPLAY_QUERY_PARAM
    ):
        replaying = runtime.id == "server" and valid_presentation_replay(
            request,
            context,
            presentation_session,
            sessions,
            preserve_session=snapshot.resolved.workspace.preserve_session,
        )
        if not replaying:
            return JSONResponse(
                {
                    "error": "presentation-replay-unavailable",
                    "message": "The stored presentation session is unavailable.",
                    "transient": False,
                },
                status_code=409,
                headers=DOCUMENT_HEADERS,
            )
    if context.mode == "run":
        replay.configure(context, snapshot.resolved.workspace.preserve_session)
    headers = {
        **DOCUMENT_HEADERS,
        "Marimo-Studio-Revision": snapshot.revision,
        "Marimo-Studio-Support-Url": request_reference(
            request,
            presentation_support_path(
                context,
                snapshot,
                presentation_session.session_id,
                presentation_session.runtime_session_id,
                editor_session_id=request.query_params.get(EDITOR_SESSION_QUERY_PARAM),
            ),
        ),
    }
    if request.method == "HEAD":
        return Response(headers=headers)
    unframed_values = request.query_params.getlist(UNFRAMED_QUERY_PARAM)
    unframed = bool(unframed_values) and unframed_values[0] == "1"
    isolated = (
        trusted_shell
        and not unframed
        and not (context.mode == "edit" and studio_owned_request(request))
        and not same_origin_server
    )
    # A host frames run-mode views as its app pages. Its trusted head, such as
    # marimohub's notebook bridge, runs in the top-level view document as it
    # would on marimo's own page. Opaque child and preview documents skip it.
    host_head = (
        context.trusted_html_head
        if context.mode == "run" and trusted_shell and not unframed
        else None
    )
    if isolated:
        nonce = secrets.token_urlsafe(18)
        shell_headers = {
            **headers,
            "Content-Security-Policy": isolation_content_security_policy(nonce),
            "Cross-Origin-Opener-Policy": "same-origin",
        }
        return HTMLResponse(
            isolated_presentation_document(
                child_url=request_reference(
                    request,
                    _presentation_document_path(
                        request,
                        context,
                        snapshot.view_name,
                        presentation_session,
                    ),
                ),
                internal_root_url=request_reference(
                    request,
                    presentation_revision_path(
                        context,
                        snapshot,
                        presentation_session.session_id,
                        runtime_session_id=presentation_session.runtime_session_id,
                    ),
                ),
                public_root_url=request_reference(request, "/"),
                replay_root_url=request_reference(request, f"{PRESENTATION_PATH}/d."),
                icon_url=request_reference(request, "/favicon.ico"),
                routing_query=urlencode(context.routing_query),
                view_name=snapshot.view_name,
                views=tuple(snapshot.resolved.workspace.views),
                private_query_keys=tuple(sorted(PRIVATE_QUERY_KEYS)),
                replay_enabled=(
                    context.mode == "run"
                    and snapshot.resolved.workspace.preserve_session
                    and runtime.id == "server"
                ),
                replay_scope=(
                    presentation_storage_scope(context)
                    if context.mode == "run"
                    else None
                ),
                runtime=runtime.id,
                runtime_explicit=runtime_explicit,
                title_text=f"{snapshot.view_name} view",
                nonce=nonce,
                host_head=host_head,
            ),
            headers=shell_headers,
        )
    runtime_headers = dict(headers)
    if context.mode == "edit" or unframed or not trusted_shell:
        runtime_headers.update(
            presentation_response_headers(sandbox=not same_origin_server)
        )
    return HTMLResponse(
        render_presentation_document(
            snapshot,
            context,
            request_path=request_path(request),
            marimo_version=marimo_version,
            runtime=runtime.id,
            runtime_explicit=runtime_explicit,
            replay=replaying,
            renewal_token=presentation_session.renewal_token,
            session_id=presentation_session.session_id,
            runtime_session_id=presentation_session.runtime_session_id,
            client_id=(
                frame_identity[0]
                if frame_identity is not None
                else client_id
                if unframed and request.query_params.get(EDITOR_SESSION_QUERY_PARAM)
                else None
            ),
            editor_session_id=request.query_params.get(EDITOR_SESSION_QUERY_PARAM),
            lifecycle_id=frame_identity[1] if frame_identity is not None else None,
            host_head=host_head,
        ),
        headers=runtime_headers,
    )


def studio_response(
    request: Request,
    context: ServerContext,
    studio: StudioWorkspace,
    selected: str,
    runtimes: tuple[tuple[str, str], ...],
    sessions: SessionState,
    session_ids: SessionIdAllocator,
    security_policy: SecurityPolicy,
) -> Response:
    """Render the edit workspace for one selected view."""
    if context.mode != "edit":
        return Response(status_code=404)
    if request.method not in {"GET", "HEAD"}:
        return Response(status_code=405)
    if selected not in studio.views:
        return PlainTextResponse(
            f"Unknown view {selected!r}",
            status_code=404,
            headers=edit_document_headers(security_policy),
        )
    client_id = secrets.token_urlsafe(18)
    native_session_id = _editor_session_id(request, context, sessions, session_ids)
    return HTMLResponse(
        studio_document(
            context,
            request.query_params.multi_items(),
            runtimes,
            client_id,
            native_session_id,
            request_path=request_path(request),
            state="ready",
            config=studio,
            selected=selected,
            trusted_server_runtime=security_policy.trusted_server_runtime,
        ),
        headers=edit_document_headers(security_policy),
    )


def initialization_response(
    request: Request,
    context: ServerContext,
    notebook: Path,
    default_view: str,
    generation: str,
    runtimes: tuple[tuple[str, str], ...],
    sessions: SessionState,
    session_ids: SessionIdAllocator,
    security_policy: SecurityPolicy,
) -> Response:
    """Render the authenticated first-view initializer in edit mode."""
    if context.mode != "edit":
        return Response(status_code=404)
    if request.method not in {"GET", "HEAD"}:
        return Response(status_code=405)
    client_id = secrets.token_urlsafe(18)
    native_session_id = _editor_session_id(request, context, sessions, session_ids)
    return HTMLResponse(
        studio_document(
            context,
            request.query_params.multi_items(),
            runtimes,
            client_id,
            native_session_id,
            request_path=request_path(request),
            state="needs-view",
            default_view=default_view,
            generation=generation,
            trusted_server_runtime=security_policy.trusted_server_runtime,
        ),
        headers=edit_document_headers(security_policy),
    )


def unconfigured_response(
    request: Request,
    context: ServerContext,
    notebook: Path,
    runtimes: tuple[tuple[str, str], ...],
    sessions: SessionState,
    session_ids: SessionIdAllocator,
    security_policy: SecurityPolicy,
) -> Response:
    """Render the stable editor host before Studio is configured."""
    if context.mode != "edit":
        return Response(status_code=404)
    if request.method not in {"GET", "HEAD"}:
        return Response(status_code=405)
    client_id = secrets.token_urlsafe(18)
    native_session_id = _editor_session_id(request, context, sessions, session_ids)
    first_save = request.query_params.get(DOCUMENT_REPLAY_QUERY_PARAM) == "1" and (
        host_session_handoff_capability_matches(
            request.query_params.get(HOST_SESSION_HANDOFF_QUERY_PARAM),
            context,
            native_session_id,
            request.query_params.multi_items(),
        )
    )
    if first_save:
        return RedirectResponse(
            request_reference(
                request,
                with_query(
                    studio_path(DEFAULT_VIEW_NAME),
                    request.query_params.multi_items(),
                ),
            ),
            status_code=307,
            headers=edit_document_headers(security_policy),
        )
    return HTMLResponse(
        studio_document(
            context,
            request.query_params.multi_items(),
            runtimes,
            client_id,
            native_session_id,
            request_path=request_path(request),
            state="unconfigured",
            trusted_server_runtime=security_policy.trusted_server_runtime,
        ),
        headers=edit_document_headers(security_policy),
    )


def _editor_session_id(
    request: Request,
    context: ServerContext,
    sessions: SessionState,
    session_ids: SessionIdAllocator,
) -> str:
    requested = request.query_params.get("session_id")
    if request.query_params.get(DOCUMENT_REPLAY_QUERY_PARAM) == "1" and (
        requested is not None and sessions.is_session_id(requested)
    ):
        query = request.query_params.multi_items()
        if sessions.exists(context, requested) and sessions.matches_creation_query(
            context,
            requested,
            query,
        ):
            return requested
        if sessions.ownership(context, requested) in {
            "current",
            "unclaimed",
        } and host_session_handoff_capability_matches(
            request.query_params.get(HOST_SESSION_HANDOFF_QUERY_PARAM),
            context,
            requested,
            query,
        ):
            return requested
    return session_ids.allocate(context, sessions)


def error_response(
    relative: str,
    error: MarimoStudioError,
    notebook: Path,
    *,
    requested_path: str,
    dev: bool,
    edit_mode: bool,
    structured: bool,
    server_token: str,
    routing_query: Sequence[tuple[str, str]] = (),
    presentation_events_path: str | None = None,
    lifecycle_id: int | None = None,
    runtime: str = "server",
    security_policy: SecurityPolicy,
    view_name: str = "",
) -> Response:
    """Translate a domain error for the requested page or support route."""
    code = getattr(error, "code", "configuration-error")
    status_code = getattr(error, "status_code", 500)
    transient = getattr(error, "transient", False)
    message = error.public_message()
    for root in {notebook.parent, notebook.parent.resolve()}:
        message = message.replace(f"{root}/", "")
    hint = error.public_hint
    payload: dict[str, object] = {
        "error": code,
        "message": message,
        **error.diagnostic_details(),
    }
    if hint:
        payload["hint"] = hint
    if transient:
        payload["transient"] = True
    if relative.startswith(SUPPORT_PATH):
        return JSONResponse(
            payload,
            status_code=status_code,
            headers={"Cache-Control": "no-store"},
        )
    document_headers = (
        edit_document_headers(security_policy) if edit_mode else DOCUMENT_HEADERS
    )
    headers = {**document_headers, "Marimo-Studio-Error": code}
    # New HTTP fields carry visible ASCII only (RFC 9110, section 5.5), and
    # clients decode other header bytes inconsistently. The body always carries
    # the hint, including one that names a non-ASCII notebook file.
    if hint and hint.isascii():
        headers["Marimo-Studio-Hint"] = hint
    if transient:
        headers.update(
            {
                "Marimo-Studio-Transient": "true",
                "Retry-After": "1",
            }
        )
    if structured:
        return JSONResponse(payload, status_code=status_code, headers=headers)
    terminal_preview = code in {
        "invalid-presentation-revision",
        "presentation-revision-mismatch",
        "preview-session-changed",
        "preview-source-changed",
        "preview-source-not-current",
    }
    if dev or terminal_preview:
        return HTMLResponse(
            repair_document(
                message,
                hint,
                relative_url(
                    requested_path,
                    with_query(
                        presentation_events_path or f"{SUPPORT_PATH}/dev/events",
                        (
                            *routing_query,
                            (
                                SERVER_INSTANCE_QUERY_PARAM,
                                server_instance_id(server_token),
                            ),
                        ),
                    ),
                ),
                icon_url=relative_url(requested_path, "/favicon.ico"),
                code=code,
                lifecycle_id=lifecycle_id,
                runtime=runtime,
                view=view_name,
                recoverable=not terminal_preview,
            ),
            status_code=status_code,
            headers=headers,
        )
    detail = f"\n\n{hint}" if hint else ""
    return PlainTextResponse(
        f"Marimo Studio configuration error\n\n{message}{detail}",
        status_code=status_code,
        headers=headers,
    )


def _waiting_response(
    request: Request,
    context: ServerContext,
    view_name: str,
    presentation_session: PresentationSession,
    *,
    head: bool = False,
) -> Response:
    headers = {**DOCUMENT_HEADERS, "Retry-After": "1"}
    if head:
        return Response(status_code=202, headers=headers)
    return HTMLResponse(
        waiting_document(
            refresh_url=request_reference(
                request,
                _presentation_document_path(
                    request,
                    context,
                    view_name,
                    presentation_session,
                ),
            ),
            icon_url=request_reference(request, "/favicon.ico"),
            lifecycle_id=_positive_int(
                request.query_params.get(DOCUMENT_LIFECYCLE_QUERY_PARAM)
            ),
            runtime=request.query_params.get("runtime", "server"),
            view=view_name,
        ),
        status_code=202,
        headers=headers,
    )


def _presentation_document_path(
    request: Request,
    context: ServerContext,
    view_name: str,
    presentation_session: PresentationSession,
) -> str:
    return with_query(
        presentation_renewal_path(
            context,
            view_name,
            presentation_session.session_id,
            presentation_session.runtime_session_id,
            view_path(view_name),
        ),
        (
            *(
                (key, value)
                for key, value in request.query_params.multi_items()
                if key
                not in {
                    "access_token",
                    EDITOR_BINDING_CAPABILITY_QUERY_PARAM,
                    PRESENTATION_RENEWAL_QUERY_PARAM,
                    "session_id",
                    WORKSPACE_EVENTS_CAPABILITY_QUERY_PARAM,
                }
            ),
            ("session_id", presentation_session.runtime_session_id),
        ),
    )


def _positive_int(value: str | None) -> int | None:
    return (
        int(value)
        if value is not None and value.isdecimal() and int(value) > 0
        else None
    )
