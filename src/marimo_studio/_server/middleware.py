"""Attach Studio presentation routes to Marimo's ASGI application."""

from __future__ import annotations

from pathlib import Path

from starlette.requests import Request
from starlette.types import ASGIApp, Receive, Scope, Send

from marimo_studio._compat.server import (
    enable_peer_control_sync,
    has_access_token,
    has_read_access,
    relative_request_path,
    server_context,
    server_location,
)
from marimo_studio._server.pages import (
    authentication_redirect,
    document_response,
    error_response,
    page_redirect,
    studio_landing_redirect,
    studio_response,
)
from marimo_studio._server.presentation import NotebookPresentation
from marimo_studio._server.routing import (
    could_handle,
    document_view,
    is_studio_landing,
    studio_view,
)
from marimo_studio._server.support import support_response
from marimo_studio._urls import SUPPORT_PATH
from marimo_studio.errors import MarimoStudioError


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
        if relative is None or not could_handle(relative, location.mode):
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive)
        landing = is_studio_landing(relative, location.mode)
        if landing and (
            request.method not in {"GET", "HEAD"} or "file" in request.query_params
        ):
            await self.app(scope, receive, send)
            return
        if landing and (has_access_token(scope) or not has_read_access(scope)):
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

        if discovery_error is not None and landing:
            await self.app(scope, receive, send)
            return

        if studio is None:
            if discovery_error is None:
                await self.app(scope, receive, send)
                return
            selected_document = None
            selected_studio = None
        else:
            selected_document = document_view(relative, studio, location.mode)
            selected_studio = studio_view(relative, studio, location.mode)
            if (
                selected_document is None
                and selected_studio is None
                and not landing
                and not relative.startswith(SUPPORT_PATH)
            ):
                await self.app(scope, receive, send)
                return

        if has_access_token(scope) or not has_read_access(scope):
            if relative in {"", "/"} or relative.startswith(f"{SUPPORT_PATH}/assets/"):
                await self.app(scope, receive, send)
            else:
                await authentication_redirect(request, location.base_url)(
                    scope,
                    receive,
                    send,
                )
            return

        dev = location.mode == "edit" or bool(
            getattr(location._session_manager, "watch", False)
        )
        if discovery_error is not None:
            response = error_response(
                relative,
                discovery_error,
                presentation.notebook,
                base_url=location.base_url,
                dev=dev,
                structured=_accepts_json(request),
            )
            await response(scope, receive, send)
            return

        assert studio is not None
        try:
            redirect = page_redirect(
                request,
                relative,
                selected_document is not None or selected_studio is not None,
            )
            if redirect is not None:
                response = redirect
            elif landing:
                response = studio_landing_redirect(
                    request,
                    location.base_url,
                    studio.default_view,
                )
            else:
                context = server_context(location)
                enable_peer_control_sync(location)
                if selected_document is not None:
                    response = document_response(
                        request,
                        context,
                        presentation,
                        relative,
                        selected_document,
                    )
                elif selected_studio is not None:
                    response = studio_response(
                        request,
                        context,
                        studio,
                        selected_studio,
                    )
                else:
                    response = await support_response(
                        request,
                        context,
                        studio,
                        presentation,
                        relative.removeprefix(SUPPORT_PATH),
                    )
        except MarimoStudioError as error:
            response = error_response(
                relative,
                error,
                presentation.notebook,
                base_url=location.base_url,
                dev=dev,
                structured=_accepts_json(request),
            )
        await response(scope, receive, send)


def _accepts_json(request: Request) -> bool:
    return "application/json" in request.headers.get("accept", "")
