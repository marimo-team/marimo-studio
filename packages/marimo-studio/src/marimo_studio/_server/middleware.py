"""Attach Studio presentation routes to Marimo's ASGI application."""

from __future__ import annotations

from pathlib import Path

from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp, Receive, Scope, Send

from marimo_studio import _assets
from marimo_studio._compat.server.cell_aliases import enable_cell_alias_sync
from marimo_studio._compat.server.context import (
    relative_request_path,
    server_base_url,
    server_context,
    server_location,
    server_mode,
    server_uses_file_routing,
)
from marimo_studio._compat.server.peer_controls import enable_peer_control_sync
from marimo_studio._compat.server.sessions import has_access_token, has_read_access
from marimo_studio._server.files import file_response
from marimo_studio._server.pages import (
    authentication_redirect,
    authored_document_redirect,
    document_response,
    error_response,
    initialization_response,
    page_redirect,
    studio_landing_redirect,
    studio_response,
)
from marimo_studio._server.presentation import NotebookPresentation
from marimo_studio._server.routing import (
    authored_view_route,
    could_handle,
    document_view,
    is_studio_landing,
    native_editor_target,
    studio_view,
    view_asset,
    view_route_alias,
)
from marimo_studio._server.runtimes import DEFAULT_RUNTIME_REGISTRY
from marimo_studio._server.support import (
    lifecycle_status_response,
    support_response,
)
from marimo_studio._urls import SUPPORT_PATH
from marimo_studio._workspace import discover_studio
from marimo_studio.errors import MarimoStudioError, WorkspaceInitializationError


class PresentationMiddleware:
    """Present configured notebook views while delegating Marimo-owned routes."""

    def __init__(
        self,
        app: ASGIApp,
    ) -> None:
        self.app = app
        self._presentations: dict[Path, NotebookPresentation] = {}

    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        if scope["type"] not in {"http", "websocket"}:
            await self.app(scope, receive, send)
            return
        base_url = server_base_url(scope)
        if base_url is None:
            await self.app(scope, receive, send)
            return
        relative = relative_request_path(scope, base_url)
        if relative is None:
            await self.app(scope, receive, send)
            return
        mode = server_mode(scope)
        if mode is None:
            await self.app(scope, receive, send)
            return
        editor_target = native_editor_target(relative)
        if editor_target is not None and mode == "edit":
            if scope["type"] == "http":
                location = server_location(Request(scope, receive))
                if location is not None:
                    try:
                        workspace = discover_studio(location.notebook)
                    except MarimoStudioError:
                        workspace = None
                    if workspace is not None and workspace.cells:
                        enable_cell_alias_sync(location)
            await self.app(
                _replace_relative_path(scope, relative, editor_target),
                receive,
                send,
            )
            return
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive)
        if relative.startswith(f"{SUPPORT_PATH}/assets/"):
            response = (
                file_response(
                    _assets.runtime_assets_path(),
                    relative.removeprefix(f"{SUPPORT_PATH}/assets/"),
                )
                if request.method in {"GET", "HEAD"}
                else Response(status_code=405)
            )
            await response(scope, receive, send)
            return
        if not has_read_access(scope) and relative in {"", "/"}:
            await self.app(scope, receive, send)
            return
        authored = authored_view_route(relative)
        if (
            not has_read_access(scope)
            and server_uses_file_routing(scope)
            and ("file" in request.query_params or authored is not None)
            and relative not in {"", "/"}
            and could_handle(relative, mode)
        ):
            response = authentication_redirect(request, base_url)
            await response(scope, receive, send)
            return

        request_relative = relative
        location = server_location(
            request,
            selected_file=authored.file_key if authored is not None else None,
        )
        if location is None:
            await self.app(scope, receive, send)
            return
        if authored is not None:
            relative = authored.relative
        if not could_handle(relative, location.mode):
            await self.app(scope, receive, send)
            return

        landing = is_studio_landing(relative, location.mode)
        if landing and request.method not in {"GET", "HEAD"}:
            await self.app(scope, receive, send)
            return
        if landing and not has_read_access(scope):
            await self.app(scope, receive, send)
            return
        if landing and has_access_token(scope):
            await authentication_redirect(request, location.base_url)(
                scope,
                receive,
                send,
            )
            return

        presentation = self._presentations.setdefault(
            location.notebook,
            NotebookPresentation(location.notebook),
        )
        try:
            definition = presentation.discover_definition()
            lifecycle_error = None
        except MarimoStudioError as error:
            definition = None
            lifecycle_error = error

        if definition is None and lifecycle_error is None:
            await self.app(scope, receive, send)
            return

        if definition is not None:
            try:
                workspace = presentation.materialize(definition)
            except MarimoStudioError as error:
                workspace = None
                lifecycle_error = error
        else:
            workspace = None

        needs_view = isinstance(lifecycle_error, WorkspaceInitializationError)
        if lifecycle_error is not None and landing and not needs_view:
            await self.app(scope, receive, send)
            return

        if workspace is None:
            selected_document = None
            selected_studio = None
            selected_asset = None
        else:
            alias = view_route_alias(relative, workspace)
            if alias is not None and not alias.startswith(SUPPORT_PATH):
                await self.app(
                    _replace_relative_path(scope, request_relative, alias),
                    receive,
                    send,
                )
                return
            if alias is not None:
                relative = alias
            selected_document = document_view(relative, workspace, location.mode)
            selected_studio = studio_view(relative, workspace, location.mode)
            selected_asset = view_asset(relative, workspace)
            if (
                selected_document is None
                and selected_studio is None
                and selected_asset is None
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
        context = server_context(location)
        if definition is None:
            assert lifecycle_error is not None
            response = (
                lifecycle_status_response(lifecycle_error)
                if relative == f"{SUPPORT_PATH}/status" and request.method == "GET"
                else error_response(
                    relative,
                    lifecycle_error,
                    presentation.notebook,
                    base_url=location.base_url,
                    dev=dev,
                    structured=_accepts_json(request),
                    routing_query=context.routing_query,
                )
            )
            await response(scope, receive, send)
            return

        if workspace is None:
            assert lifecycle_error is not None
            if relative.startswith(SUPPORT_PATH):
                response = await support_response(
                    request,
                    context,
                    definition,
                    None,
                    lifecycle_error,
                    presentation,
                    relative.removeprefix(SUPPORT_PATH),
                )
            elif (
                needs_view
                and location.mode == "edit"
                and (landing or relative.strip("/").split("/")[0] == "studio")
            ):
                redirect = page_redirect(request, relative, not landing)
                response = redirect or initialization_response(
                    request,
                    context,
                    definition,
                )
            else:
                response = error_response(
                    relative,
                    lifecycle_error,
                    presentation.notebook,
                    base_url=location.base_url,
                    dev=dev,
                    structured=_accepts_json(request),
                    routing_query=context.routing_query,
                )
            await response(scope, receive, send)
            return

        if lifecycle_error is not None:
            response = error_response(
                relative,
                lifecycle_error,
                presentation.notebook,
                base_url=location.base_url,
                dev=dev,
                structured=_accepts_json(request),
                routing_query=context.routing_query,
            )
            await response(scope, receive, send)
            return

        try:
            redirect = (
                authored_document_redirect(request, context, selected_document)
                if authored is not None
                and selected_document is not None
                and request.method in {"GET", "HEAD"}
                and not _accepts_json(request)
                else page_redirect(
                    request,
                    relative,
                    selected_document is not None or selected_studio is not None,
                )
            )
            if redirect is not None:
                response = redirect
            elif landing:
                response = studio_landing_redirect(
                    request,
                    location.base_url,
                    workspace.default_view,
                    context.routing_query,
                )
            else:
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
                    if workspace.cells:
                        enable_cell_alias_sync(location)
                    response = studio_response(
                        request,
                        context,
                        workspace,
                        selected_studio,
                        DEFAULT_RUNTIME_REGISTRY.options,
                    )
                elif selected_asset is not None:
                    view_name, asset = selected_asset
                    response = (
                        file_response(workspace.views[view_name].root, asset)
                        if request.method in {"GET", "HEAD"}
                        else Response(status_code=405)
                    )
                else:
                    response = await support_response(
                        request,
                        context,
                        definition,
                        workspace,
                        None,
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
                routing_query=context.routing_query,
            )
        await response(scope, receive, send)


def _accepts_json(request: Request) -> bool:
    return "application/json" in request.headers.get("accept", "")


def _replace_relative_path(scope: Scope, current: str, target: str) -> Scope:
    """Replace one decoded relative path while preserving its ASGI mount."""
    path = str(scope.get("path", "/"))
    prefix = path[: -len(current)] if current and path.endswith(current) else ""
    updated = dict(scope)
    updated_path = f"{prefix}{target}"
    updated["path"] = updated_path
    updated["raw_path"] = updated_path.encode()
    return updated
