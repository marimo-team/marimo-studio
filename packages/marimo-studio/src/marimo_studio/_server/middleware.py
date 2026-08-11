"""Attach Studio presentation routes to Marimo's ASGI application."""

from __future__ import annotations

from collections.abc import Callable

from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from marimo_studio import _assets
from marimo_studio._capabilities import ServerAdapters
from marimo_studio._server.auth import (
    authentication_required_response,
    has_access_token,
    has_read_access,
)
from marimo_studio._server.editor_bridge import delegate_editor_request
from marimo_studio._server.files import file_response
from marimo_studio._server.notebook_scope import NotebookScopeRegistry
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
from marimo_studio._server.routing import (
    authored_view_route,
    could_handle,
    document_view,
    is_studio_landing,
    is_support_route,
    studio_view,
    view_asset,
    view_route_alias,
)
from marimo_studio._server.runtimes import create_runtime_registry
from marimo_studio._server.support import (
    support_response,
)
from marimo_studio._server.workspace_lifecycle import (
    Invalid,
    NeedsView,
    Ready,
    Unconfigured,
    resolve_workspace_lifecycle,
)
from marimo_studio._urls import ACTIVE_VIEW_QUERY_PARAM, SUPPORT_PATH
from marimo_studio.errors import MarimoStudioError


class PresentationMiddleware:
    """Present configured notebook views while delegating Marimo-owned routes."""

    def __init__(
        self,
        app: ASGIApp,
        adapter_factory: Callable[[], ServerAdapters],
    ) -> None:
        self.app = app
        self._adapters = adapter_factory()
        self._notebooks = NotebookScopeRegistry()
        self._runtimes = create_runtime_registry(
            self._adapters.session_state,
            self._adapters.browser,
        )

    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        if scope["type"] == "lifespan":
            adapters = self._adapters.lifecycle.open()
            closed = False

            async def close() -> None:
                nonlocal closed
                if closed:
                    return
                failure: BaseException | None = None
                try:
                    await self._notebooks.close()
                except BaseException as error:
                    failure = error
                try:
                    adapters.close()
                except BaseException as error:
                    if failure is None:
                        failure = error
                else:
                    closed = True
                if failure is not None:
                    raise failure

            async def close_scopes(message: Message) -> None:
                if message["type"] in {
                    "lifespan.startup.failed",
                    "lifespan.shutdown.complete",
                    "lifespan.shutdown.failed",
                }:
                    await close()
                await send(message)

            try:
                await self.app(scope, receive, close_scopes)
            finally:
                await close()
            return
        if scope["type"] not in {"http", "websocket"}:
            await self.app(scope, receive, send)
            return
        base_url = self._adapters.server.base_url(scope)
        if base_url is None:
            await self.app(scope, receive, send)
            return
        relative = self._adapters.server.relative_path(scope, base_url)
        if relative is None:
            await self.app(scope, receive, send)
            return
        mode = self._adapters.server.mode(scope)
        if mode is None:
            await self.app(scope, receive, send)
            return
        if await delegate_editor_request(
            self.app,
            self._notebooks,
            scope,
            receive,
            send,
            server=self._adapters.server,
            sessions=self._adapters.session_state,
            persistence=self._adapters.persistence,
            code_mode=self._adapters.code_mode,
            relative=relative,
            mode=mode,
        ):
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
        if (
            not has_read_access(scope)
            and is_support_route(relative)
            and _accepts_json(request)
        ):
            await authentication_required_response()(scope, receive, send)
            return
        if not has_read_access(scope) and relative in {"", "/"}:
            await self.app(scope, receive, send)
            return
        authored = authored_view_route(relative)
        if (
            not has_read_access(scope)
            and self._adapters.server.uses_file_routing(scope)
            and ("file" in request.query_params or authored is not None)
            and relative not in {"", "/"}
            and could_handle(relative, mode)
        ):
            response = authentication_redirect(request, base_url)
            await response(scope, receive, send)
            return

        request_relative = relative
        location = self._adapters.server.location(
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

        notebook_scope = self._notebooks.get(location.notebook)
        presentation = notebook_scope.presentation
        lifecycle = resolve_workspace_lifecycle(presentation)
        if isinstance(lifecycle, Unconfigured):
            await self.app(scope, receive, send)
            return
        if isinstance(lifecycle, Invalid) and landing:
            await self.app(scope, receive, send)
            return
        workspace = lifecycle.workspace if isinstance(lifecycle, Ready) else None

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

        context = self._adapters.server.context(location)
        dev = context.dev
        if isinstance(lifecycle, Invalid):
            response = (
                await support_response(
                    request,
                    context,
                    lifecycle,
                    notebook_scope,
                    relative.removeprefix(SUPPORT_PATH),
                    server=self._adapters.server,
                    session_state=self._adapters.session_state,
                    sessions=self._adapters.sessions,
                    projections=self._adapters.projections,
                    runtimes=self._runtimes,
                )
                if relative.startswith(SUPPORT_PATH)
                else error_response(
                    relative,
                    lifecycle.error,
                    presentation.notebook,
                    base_url=location.base_url,
                    dev=dev,
                    structured=_accepts_json(request),
                    routing_query=context.routing_query,
                )
            )
            await response(scope, receive, send)
            return

        if isinstance(lifecycle, NeedsView):
            if relative.startswith(SUPPORT_PATH):
                response = await support_response(
                    request,
                    context,
                    lifecycle,
                    notebook_scope,
                    relative.removeprefix(SUPPORT_PATH),
                    server=self._adapters.server,
                    session_state=self._adapters.session_state,
                    sessions=self._adapters.sessions,
                    projections=self._adapters.projections,
                    runtimes=self._runtimes,
                )
            elif location.mode == "edit" and (
                landing or relative.strip("/").split("/")[0] == "studio"
            ):
                redirect = page_redirect(request, relative, not landing)
                response = redirect or initialization_response(
                    request,
                    context,
                    lifecycle.definition,
                )
            else:
                response = error_response(
                    relative,
                    lifecycle.error,
                    presentation.notebook,
                    base_url=location.base_url,
                    dev=dev,
                    structured=_accepts_json(request),
                    routing_query=context.routing_query,
                )
            await response(scope, receive, send)
            return

        assert isinstance(lifecycle, Ready)
        workspace = lifecycle.workspace

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
                requested_view = request.query_params.get(ACTIVE_VIEW_QUERY_PARAM)
                response = studio_landing_redirect(
                    request,
                    location.base_url,
                    (
                        requested_view
                        if requested_view in workspace.views
                        else workspace.default_view
                    ),
                    context.routing_query,
                )
            else:
                self._adapters.peers.enable(location)
                if selected_document is not None:
                    response = await document_response(
                        request,
                        context,
                        presentation,
                        relative,
                        selected_document,
                        sessions=self._adapters.session_state,
                        replay=self._adapters.replay,
                        marimo_version=self._adapters.browser.version,
                    )
                elif selected_studio is not None:
                    if workspace.cells:
                        self._adapters.persistence.enable(location)
                    response = studio_response(
                        request,
                        context,
                        workspace,
                        selected_studio,
                        self._runtimes.options,
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
                        lifecycle,
                        notebook_scope,
                        relative.removeprefix(SUPPORT_PATH),
                        server=self._adapters.server,
                        session_state=self._adapters.session_state,
                        sessions=self._adapters.sessions,
                        projections=self._adapters.projections,
                        runtimes=self._runtimes,
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
