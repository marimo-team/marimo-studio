"""Build Studio page, redirect, and page-level error responses."""

from __future__ import annotations

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

from marimo_studio._capabilities import ServerContext, SessionReplay, SessionState
from marimo_studio._server.headers import DOCUMENT_HEADERS
from marimo_studio._server.presentation import NotebookPresentation
from marimo_studio._server.presentation_payload import (
    presentation_support_url,
    render_presentation_document,
)
from marimo_studio._server.server_instance import server_instance_id
from marimo_studio._server.studio import (
    repair_document,
    studio_document,
    waiting_document,
)
from marimo_studio._urls import (
    SERVER_INSTANCE_QUERY_PARAM,
    SUPPORT_PATH,
    public_url,
    studio_url,
    view_url,
    with_notebook_query,
    with_query,
)
from marimo_studio._workspace.models import StudioDefinition, StudioWorkspace
from marimo_studio.errors import MarimoStudioError


def authentication_redirect(request: Request, base_url: str) -> Response:
    """Redirect a Studio page request through Marimo authentication."""
    if "access_token" in request.query_params:
        stripped = request.url.remove_query_params("access_token")
        target = stripped.path
        if stripped.query:
            target += f"?{stripped.query}"
    else:
        next_url = request.url.path
        if request.url.query:
            next_url += f"?{request.url.query}"
        login = public_url(base_url, "/auth/login")
        target = f"{login}?{urlencode({'next': next_url})}"
    return RedirectResponse(target, status_code=303, headers=DOCUMENT_HEADERS)


def page_redirect(request: Request, relative: str, page: bool) -> Response | None:
    """Canonicalize page routes with a trailing slash."""
    if not page or relative in {"", "/"} or relative.endswith("/"):
        return None
    target = (
        request.url.path.removesuffix("index.html")
        if relative.endswith("/index.html")
        else request.url.path + "/"
    )
    if request.url.query:
        target += f"?{request.url.query}"
    return RedirectResponse(target, status_code=307, headers=DOCUMENT_HEADERS)


def studio_landing_redirect(
    request: Request,
    base_url: str,
    view_name: str,
    routing_query: Sequence[tuple[str, str]] = (),
) -> Response:
    """Redirect the edit root to its configured Studio workspace."""
    target = with_notebook_query(
        studio_url(base_url, view_name),
        request.query_params.multi_items(),
        routing_query,
    )
    return RedirectResponse(target, status_code=307, headers=DOCUMENT_HEADERS)


def authored_document_redirect(
    request: Request,
    context: ServerContext,
    view_name: str,
) -> Response:
    """Canonicalize an authored document route to its public view URL."""
    target = with_notebook_query(
        view_url(context.base_url, view_name),
        request.query_params.multi_items(),
        context.routing_query,
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
    replay: SessionReplay,
    marimo_version: str,
) -> Response:
    """Render one custom view document against the active Marimo server."""
    if request.method not in {"GET", "HEAD"}:
        return Response(status_code=405)
    if context.mode == "edit" and not sessions.has_notebook_session(context):
        return _waiting_response()
    selected = None if context.mode == "run" and relative in {"", "/"} else view_name
    snapshot = await presentation.snapshot_async(selected)
    if context.mode == "run":
        replay.configure(context, snapshot.resolved.workspace.preserve_session)
    return HTMLResponse(
        render_presentation_document(
            snapshot,
            context,
            marimo_version=marimo_version,
        ),
        headers={
            **DOCUMENT_HEADERS,
            "Marimo-Studio-Revision": snapshot.revision,
            "Marimo-Studio-Support-Url": presentation_support_url(
                context,
                snapshot.view_name,
            ),
        },
    )


def studio_response(
    request: Request,
    context: ServerContext,
    studio: StudioWorkspace,
    selected: str,
    runtimes: tuple[tuple[str, str], ...],
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
            headers=DOCUMENT_HEADERS,
        )
    return HTMLResponse(
        studio_document(
            studio.notebook,
            context.base_url,
            context.server_token,
            context.file_key,
            request.query_params.multi_items(),
            context.routing_query,
            runtimes,
            state="ready",
            config=studio,
            selected=selected,
        ),
        headers=DOCUMENT_HEADERS,
    )


def initialization_response(
    request: Request,
    context: ServerContext,
    definition: StudioDefinition,
    runtimes: tuple[tuple[str, str], ...],
) -> Response:
    """Render the authenticated first-view initializer in edit mode."""
    if context.mode != "edit":
        return Response(status_code=404)
    if request.method not in {"GET", "HEAD"}:
        return Response(status_code=405)
    return HTMLResponse(
        studio_document(
            definition.notebook,
            context.base_url,
            context.server_token,
            context.file_key,
            request.query_params.multi_items(),
            context.routing_query,
            runtimes,
            state="needs-view",
            default_view=definition.default_view,
        ),
        headers=DOCUMENT_HEADERS,
    )


def unconfigured_response(
    request: Request,
    context: ServerContext,
    notebook: Path,
    runtimes: tuple[tuple[str, str], ...],
) -> Response:
    """Render the stable editor host before Studio is configured."""
    if context.mode != "edit":
        return Response(status_code=404)
    if request.method not in {"GET", "HEAD"}:
        return Response(status_code=405)
    return HTMLResponse(
        studio_document(
            notebook,
            context.base_url,
            context.server_token,
            context.file_key,
            request.query_params.multi_items(),
            context.routing_query,
            runtimes,
            state="unconfigured",
        ),
        headers=DOCUMENT_HEADERS,
    )


def error_response(
    relative: str,
    error: MarimoStudioError,
    notebook: Path,
    *,
    base_url: str,
    dev: bool,
    structured: bool,
    server_token: str,
    routing_query: Sequence[tuple[str, str]] = (),
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
    headers = {**DOCUMENT_HEADERS, "Marimo-Studio-Error": code}
    if hint:
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
    if dev:
        return HTMLResponse(
            repair_document(
                message,
                hint,
                with_query(
                    public_url(base_url, f"{SUPPORT_PATH}/dev/events"),
                    (
                        *routing_query,
                        (
                            SERVER_INSTANCE_QUERY_PARAM,
                            server_instance_id(server_token),
                        ),
                    ),
                ),
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


def _waiting_response() -> Response:
    return HTMLResponse(
        waiting_document(),
        status_code=202,
        headers={**DOCUMENT_HEADERS, "Retry-After": "1"},
    )
