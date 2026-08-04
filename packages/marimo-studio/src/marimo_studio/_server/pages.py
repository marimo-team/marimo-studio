"""Build Studio page, redirect, and page-level error responses."""

from __future__ import annotations

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

from marimo_studio._compat.server.models import ServerContext
from marimo_studio._compat.server.replay import configure_document_replay
from marimo_studio._compat.server.sessions import has_notebook_session
from marimo_studio._server.headers import DOCUMENT_HEADERS
from marimo_studio._server.presentation import NotebookPresentation
from marimo_studio._server.studio import (
    repair_document,
    studio_document,
    waiting_document,
)
from marimo_studio._urls import (
    SUPPORT_PATH,
    public_url,
    studio_url,
    with_notebook_query,
)
from marimo_studio._workspace.models import StudioConfig
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
    target = request.url.path + "/"
    if request.url.query:
        target += f"?{request.url.query}"
    return RedirectResponse(target, status_code=307, headers=DOCUMENT_HEADERS)


def studio_landing_redirect(
    request: Request,
    base_url: str,
    view_name: str,
) -> Response:
    """Redirect the edit root to its configured Studio workspace."""
    target = with_notebook_query(
        studio_url(base_url, view_name),
        request.query_params.multi_items(),
    )
    return RedirectResponse(target, status_code=307, headers=DOCUMENT_HEADERS)


def document_response(
    request: Request,
    context: ServerContext,
    presentation: NotebookPresentation,
    relative: str,
    view_name: str,
) -> Response:
    """Render one custom view document against the active Marimo server."""
    if request.method not in {"GET", "HEAD"}:
        return Response(status_code=405)
    if context.mode == "edit" and not has_notebook_session(context):
        return _waiting_response()
    selected = None if context.mode == "run" and relative in {"", "/"} else view_name
    snapshot = presentation.snapshot(selected)
    if context.mode == "run":
        configure_document_replay(
            context,
            snapshot.resolved.studio.preserve_session,
        )
    return HTMLResponse(
        presentation.render_document(snapshot, context),
        headers={
            **DOCUMENT_HEADERS,
            "Marimo-Studio-Revision": snapshot.revision,
            "Marimo-Studio-Support-Url": public_url(
                context.base_url,
                f"{SUPPORT_PATH}/views/{snapshot.view_name}",
            ),
        },
    )


def studio_response(
    request: Request,
    context: ServerContext,
    studio: StudioConfig,
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
            studio,
            context.base_url,
            selected,
            context.server_token,
            context.file_key,
            request.query_params.multi_items(),
            runtimes,
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
) -> Response:
    """Translate a domain error for the requested page or support route."""
    code = getattr(error, "code", "configuration-error")
    status_code = getattr(error, "status_code", 500)
    transient = getattr(error, "transient", False)
    message = error.public_message()
    for root in {notebook.parent, notebook.parent.resolve()}:
        message = message.replace(f"{root}/", "")
    hint = error.public_hint
    payload: dict[str, object] = {"error": code, "message": message}
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
                public_url(base_url, f"{SUPPORT_PATH}/dev/events"),
            ),
            status_code=status_code,
            headers=headers,
        )
    return PlainTextResponse(
        f"Marimo Studio configuration error\n\n{message}",
        status_code=status_code,
        headers=headers,
    )


def _waiting_response() -> Response:
    return HTMLResponse(
        waiting_document(),
        status_code=202,
        headers={**DOCUMENT_HEADERS, "Retry-After": "1"},
    )
