"""Serve named presentation routes inside Marimo's ASGI application."""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast
from urllib.parse import urlencode

from starlette.requests import Request
from starlette.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    PlainTextResponse,
    RedirectResponse,
    Response,
    StreamingResponse,
)
from starlette.types import ASGIApp, Receive, Scope, Send

from marimo_studio import _assets
from marimo_studio._compat.kernel_values import (
    ValueReadUnavailable,
    read_session_values,
)
from marimo_studio._compat.server import (
    ServerContext,
    current_session,
    enable_document_replay,
    has_access_token,
    has_notebook_session,
    has_read_access,
    relative_request_path,
    server_context,
    server_location,
)
from marimo_studio._html import cell_host, render
from marimo_studio._server.dev import change_events
from marimo_studio._server.presentation import NotebookPresentation
from marimo_studio._server.routes import (
    STUDIO_PATH,
    SUPPORT_PATH,
    public_url,
)
from marimo_studio._server.studio import studio_document
from marimo_studio._workspace.models import (
    RESERVED_VIEW_NAMES,
    VIEW_PATTERN,
    ResolvedView,
    StudioConfig,
)
from marimo_studio.errors import MarimoStudioError

_NO_STORE = {"Cache-Control": "no-store"}
_DOCUMENT_HEADERS = {
    **_NO_STORE,
    "Referrer-Policy": "same-origin",
    "X-Content-Type-Options": "nosniff",
}


class PresentationMiddleware:
    """Present configured notebook views while delegating Marimo-owned routes."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        self._presentations: dict[Path, NotebookPresentation] = {}

    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        location = server_location(scope)
        if location is None:
            await self.app(scope, receive, send)
            return
        relative = relative_request_path(scope, location.base_url)
        if relative is None or not self._could_handle(relative, location.mode):
            await self.app(scope, receive, send)
            return
        presentation = self._presentations.setdefault(
            location.notebook,
            NotebookPresentation(location.notebook),
        )
        try:
            studio = presentation.discover()
            discovery_error = None
        except MarimoStudioError as error:
            studio = None
            discovery_error = error
        if studio is None:
            if discovery_error is None:
                await self.app(scope, receive, send)
                return
            document_view = None
            studio_view = None
        else:
            document_view = self._document_view(relative, studio, location.mode)
            studio_view = self._studio_view(relative, studio, location.mode)
            if (
                document_view is None
                and studio_view is None
                and not relative.startswith(SUPPORT_PATH)
            ):
                await self.app(scope, receive, send)
                return
        if has_access_token(scope) or not has_read_access(scope):
            if relative in {"", "/"} or relative.startswith(f"{SUPPORT_PATH}/assets/"):
                await self.app(scope, receive, send)
            else:
                response = self._authentication_redirect(
                    Request(scope, receive),
                    location.base_url,
                )
                await response(scope, receive, send)
            return
        if discovery_error is not None:
            response = self._error_response(relative, discovery_error)
            await response(scope, receive, send)
            return
        assert studio is not None
        try:
            redirect = self._page_redirect(
                Request(scope, receive),
                relative,
                document_view is not None or studio_view is not None,
            )
            if redirect is not None:
                await redirect(scope, receive, send)
                return
            context = server_context(location)
            if studio.preserve_session and context.mode == "run":
                enable_document_replay(context)
            response = await self._response(
                scope,
                receive,
                relative,
                context,
                studio,
                presentation,
                document_view,
                studio_view,
            )
        except MarimoStudioError as error:
            response = self._error_response(relative, error)
        await response(scope, receive, send)

    @staticmethod
    def _authentication_redirect(request: Request, base_url: str) -> Response:
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
        return RedirectResponse(
            target,
            status_code=303,
            headers=_DOCUMENT_HEADERS,
        )

    @staticmethod
    def _could_handle(relative: str, mode: str) -> bool:
        if relative == SUPPORT_PATH or relative.startswith(f"{SUPPORT_PATH}/"):
            return True
        if mode == "run" and relative in {"", "/"}:
            return True
        parts = relative.strip("/").split("/")
        if mode == "edit" and parts[0] == STUDIO_PATH.strip("/"):
            return len(parts) in {1, 2}
        return (
            len(parts) == 1
            and VIEW_PATTERN.fullmatch(parts[0]) is not None
            and parts[0] not in RESERVED_VIEW_NAMES
        )

    @staticmethod
    def _document_view(
        relative: str,
        studio: StudioConfig,
        mode: str,
    ) -> str | None:
        if mode == "run" and relative in {"", "/"}:
            return studio.default_view
        name = relative.strip("/")
        return name if "/" not in name and name in studio.views else None

    @staticmethod
    def _studio_view(
        relative: str,
        studio: StudioConfig,
        mode: str,
    ) -> str | None:
        if mode != "edit":
            return None
        parts = relative.strip("/").split("/")
        if parts == [STUDIO_PATH.strip("/")]:
            return studio.default_view
        if len(parts) == 2 and parts[0] == STUDIO_PATH.strip("/"):
            return parts[1] if parts[1] in studio.views else None
        return None

    @staticmethod
    def _page_redirect(
        request: Request,
        relative: str,
        page: bool,
    ) -> Response | None:
        if not page or relative in {"", "/"} or relative.endswith("/"):
            return None
        target = request.url.path + "/"
        if request.url.query:
            target += f"?{request.url.query}"
        return RedirectResponse(
            target,
            status_code=307,
            headers=_DOCUMENT_HEADERS,
        )

    async def _response(
        self,
        scope: Scope,
        receive: Receive,
        relative: str,
        context: ServerContext,
        studio: StudioConfig,
        presentation: NotebookPresentation,
        document_view: str | None,
        studio_view: str | None,
    ) -> Response:
        request = Request(scope, receive)
        if document_view is not None:
            if request.method not in {"GET", "HEAD"}:
                return Response(status_code=405)
            if context.mode == "edit" and not has_notebook_session(context):
                return self._waiting_response()
            resolved = presentation.resolve(studio, document_view)
            return HTMLResponse(
                presentation.render_document(resolved, context, document_view),
                headers=_DOCUMENT_HEADERS,
            )
        if studio_view is not None:
            return self._studio_response(request, context, studio, studio_view)
        support_path = relative.removeprefix(SUPPORT_PATH)
        if support_path.startswith("/assets/"):
            return self._file_response(
                _assets.runtime_assets_path(),
                support_path.removeprefix("/assets/"),
            )
        if not has_read_access(scope):
            return JSONResponse(
                {
                    "error": "authentication-required",
                    "message": "Authenticate with Marimo before using this route.",
                },
                status_code=401,
                headers=_NO_STORE,
            )
        if support_path == "/views" and request.method == "GET":
            return JSONResponse(
                {
                    "schema": 1,
                    "default_view": studio.default_view,
                    "views": list(studio.views),
                },
                headers=_NO_STORE,
            )
        if support_path == "/dev/events" and request.method == "GET" and context.dev:
            return self._events_response(studio)
        if support_path.startswith("/views/"):
            return await self._view_response(
                request,
                context,
                studio,
                presentation,
                support_path.removeprefix("/views/"),
            )
        return Response(status_code=404)

    def _studio_response(
        self,
        request: Request,
        context: ServerContext,
        studio: StudioConfig,
        selected: str,
    ) -> Response:
        if context.mode != "edit":
            return Response(status_code=404)
        if request.method not in {"GET", "HEAD"}:
            return Response(status_code=405)
        if selected not in studio.views:
            return PlainTextResponse(
                f"Unknown view {selected!r}",
                status_code=404,
                headers=_DOCUMENT_HEADERS,
            )
        return HTMLResponse(
            studio_document(studio, context.base_url, selected),
            headers=_DOCUMENT_HEADERS,
        )

    async def _view_response(
        self,
        request: Request,
        context: ServerContext,
        studio: StudioConfig,
        presentation: NotebookPresentation,
        relative: str,
    ) -> Response:
        view_name, separator, route = relative.partition("/")
        if not separator or view_name not in studio.views:
            return Response(status_code=404)
        if route.startswith("static/") and request.method in {"GET", "HEAD"}:
            return self._file_response(
                studio.views[view_name].root,
                route.removeprefix("static/"),
            )
        if route == "dev/events" and request.method == "GET" and context.dev:
            return self._events_response(studio, view_name)
        resolved = presentation.resolve(studio, view_name)
        view = resolved.views[view_name]
        if route == "config" and request.method == "GET":
            return JSONResponse(
                presentation.runtime_config(
                    resolved,
                    context,
                    view_name,
                    request.headers.get("Marimo-Session-Id"),
                ),
                headers=_NO_STORE,
            )
        if route == "values" and request.method == "POST":
            return await self._values_response(request, context, view)
        if route.startswith("cells/") and request.method == "GET":
            alias = route.removeprefix("cells/")
            if "/" in alias or alias not in resolved.aliases:
                return JSONResponse(
                    {"error": "unknown-cell", "message": f"Unknown cell {alias!r}."},
                    status_code=404,
                    headers=_NO_STORE,
                )
            return HTMLResponse(render(cell_host(alias)), headers=_NO_STORE)
        return Response(status_code=404)

    @staticmethod
    def _events_response(
        studio: StudioConfig,
        view_name: str | None = None,
    ) -> Response:
        return StreamingResponse(
            change_events(studio, view_name),
            media_type="text/event-stream",
            headers={**_NO_STORE, "X-Accel-Buffering": "no"},
        )

    @staticmethod
    def _waiting_response() -> Response:
        return HTMLResponse(
            (
                '<!doctype html><html><head><meta charset="utf-8">'
                '<meta name="viewport" content="width=device-width">'
                "<title>Connecting to notebook</title></head>"
                "<body><p>Connecting to the notebook session</p>"
                "<script>setTimeout(()=>location.reload(),300)</script>"
                "</body></html>"
            ),
            status_code=503,
            headers={**_DOCUMENT_HEADERS, "Retry-After": "1"},
        )

    async def _values_response(
        self,
        request: Request,
        context: ServerContext,
        view: ResolvedView,
    ) -> Response:
        try:
            body = await request.json()
        except (json.JSONDecodeError, UnicodeDecodeError):
            body = None
        selectors = body.get("selectors") if isinstance(body, dict) else None
        if (
            not isinstance(selectors, list)
            or len(selectors) > 100
            or not all(isinstance(selector, str) for selector in selectors)
        ):
            return JSONResponse(
                {
                    "error": "invalid-value-request",
                    "message": "selectors must be an array of at most 100 strings.",
                },
                status_code=400,
                headers=_NO_STORE,
            )
        requested = tuple(dict.fromkeys(cast(list[str], selectors)))
        unknown = sorted(set(requested).difference(view.value_bindings))
        if unknown:
            return JSONResponse(
                {
                    "error": "unknown-selector",
                    "message": f"Unknown selectors: {', '.join(unknown)}.",
                },
                status_code=400,
                headers=_NO_STORE,
            )
        session_id = request.headers.get("Marimo-Session-Id")
        if not session_id:
            return JSONResponse(
                {
                    "error": "missing-session",
                    "message": "Marimo-Session-Id is required.",
                    "transient": True,
                },
                status_code=409,
                headers=_NO_STORE,
            )
        session = current_session(context, session_id)
        if session is None:
            return JSONResponse(
                {
                    "error": "unknown-session",
                    "message": "The Marimo session is still connecting.",
                    "transient": True,
                },
                status_code=409,
                headers=_NO_STORE,
            )
        try:
            result = await read_session_values(
                session,
                requested,
                consumer_id=session_id,
            )
        except ValueReadUnavailable as error:
            return JSONResponse(
                {
                    "error": error.code,
                    "message": str(error),
                    "transient": error.transient,
                },
                status_code=error.status_code,
                headers=_NO_STORE,
            )
        return JSONResponse(result.to_dict(), headers=_NO_STORE)

    @staticmethod
    def _file_response(root: Path, relative: str) -> Response:
        root = root.resolve()
        candidate = (root / relative).resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            return Response(status_code=404)
        if not candidate.is_file():
            return Response(status_code=404)
        return FileResponse(candidate, headers={"Cache-Control": "no-cache"})

    @staticmethod
    def _error_response(relative: str, error: Exception) -> Response:
        code = getattr(error, "code", "configuration-error")
        status_code = getattr(error, "status_code", 500)
        transient = getattr(error, "transient", False)
        if not relative.startswith(SUPPORT_PATH):
            return PlainTextResponse(
                f"Marimo Studio configuration error\n\n{error}",
                status_code=status_code,
                headers=_DOCUMENT_HEADERS,
            )
        payload: dict[str, object] = {"error": code, "message": str(error)}
        if transient:
            payload["transient"] = True
        return JSONResponse(
            payload,
            status_code=status_code,
            headers=_NO_STORE,
        )
