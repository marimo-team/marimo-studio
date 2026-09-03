"""Dispatch Studio-owned ASGI routes while preserving Marimo's server surface.

The middleware resolves the selected notebook, server mode, authentication,
and signed presentation access before handing a request to the matching Studio
handler or embedded native editor. Requests outside Studio's route space
continue to the original Marimo application.

Private Marimo adapters belong to the application lifespan. Notebook scopes are
created lazily for routed notebooks, then retained by that lifespan. Shutdown
closes every scope and adapter created during the application, even when one
owner reports a failure.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

import marimo_studio._delivery.assets as _assets
from marimo_studio._delivery.urls import (
    DOCUMENT_REPLAY_QUERY_PARAM,
    STUDIO_PATH,
    SUPPORT_PATH,
)
from marimo_studio._server.auth import (
    authentication_required_response,
    has_access_token,
    has_read_access,
)
from marimo_studio._server.editor_bridge import delegate_editor_request
from marimo_studio._server.files import (
    file_response,
)
from marimo_studio._server.host_integration import HostEntryHandler
from marimo_studio._server.lifecycle_handler import (
    LifecycleRoute,
    LifecycleRouteHandler,
)
from marimo_studio._server.notebook_scope import NotebookScopeRegistry
from marimo_studio._server.pages import authentication_redirect
from marimo_studio._server.ports import ServerAdapters
from marimo_studio._server.presentation.access import (
    PresentationCapabilityHandler,
    grant_capability_headers,
    replace_relative_path,
    send_capability_app,
)
from marimo_studio._server.presentation.capability import (
    PresentationCapabilityRoute,
)
from marimo_studio._server.presentation.session import (
    assign_presentation_session,
    presentation_session_redirect,
    resolve_presentation_session,
)
from marimo_studio._server.ready_handler import (
    ReadyWorkspaceHandler,
    ReadyWorkspaceRoute,
)
from marimo_studio._server.route_policy import (
    DEFAULT_STUDIO_ROUTE_POLICY,
    StudioRoutePolicy,
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
from marimo_studio._server.runtime.catalog import create_runtime_registry
from marimo_studio._server.security import DEFAULT_SECURITY_POLICY, SecurityPolicy
from marimo_studio._server.workspace_lifecycle import (
    Invalid,
    NeedsView,
    Ready,
    Unconfigured,
)


async def _send_studio_response(
    response: Response,
    scope: Scope,
    receive: Receive,
    send: Send,
) -> None:
    response.headers.setdefault("Cache-Control", "no-store")
    await response(scope, receive, send)


class PresentationMiddleware:
    """Present configured notebook views while delegating Marimo-owned routes."""

    def __init__(
        self,
        app: ASGIApp,
        adapter_factory: Callable[[], ServerAdapters],
        security_policy: SecurityPolicy = DEFAULT_SECURITY_POLICY,
        route_policy: StudioRoutePolicy = DEFAULT_STUDIO_ROUTE_POLICY,
    ) -> None:
        self.app = app
        self._security_policy = security_policy
        self._adapters = adapter_factory()
        self._route_policy = route_policy
        self._notebooks = NotebookScopeRegistry()
        self._host_entry = HostEntryHandler(
            route_policy,
            security_policy,
            self._adapters.server,
            self._adapters.session_state,
            self._notebooks,
        )
        self._capabilities = PresentationCapabilityHandler(
            app,
            self._adapters.server,
            self._adapters.session_state,
            self._notebooks,
        )
        self._runtimes = create_runtime_registry(
            self._adapters.session_state,
            self._adapters.browser,
        )
        self._lifecycle_routes = LifecycleRouteHandler(
            app,
            self._adapters,
            self._runtimes,
            security_policy,
        )
        self._ready_routes = ReadyWorkspaceHandler(
            self._adapters,
            self._runtimes,
            security_policy,
        )

    @asynccontextmanager
    async def lifespan(self) -> AsyncIterator[Callable[[], Awaitable[None]]]:
        """Own Studio resources for one server application lifespan."""
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
                self._host_entry.close()
            except BaseException as error:
                if failure is None:
                    failure = error
            try:
                await self._runtimes.close()
            except BaseException as error:
                if failure is None:
                    failure = error
            try:
                await self._adapters.session_state.close()
            except BaseException as error:
                if failure is None:
                    failure = error
            try:
                adapters.close()
            except BaseException as error:
                if failure is None:
                    failure = error
            if failure is None:
                closed = True
            if failure is not None:
                raise failure

        try:
            yield close
        finally:
            await close()

    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        if scope["type"] == "lifespan":
            async with self.lifespan() as close:

                async def close_scopes(message: Message) -> None:
                    if message["type"] in {
                        "lifespan.startup.failed",
                        "lifespan.shutdown.complete",
                        "lifespan.shutdown.failed",
                    }:
                        await close()
                    await send(message)

                await self.app(scope, receive, close_scopes)
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
        if await self._host_entry.serve(
            self.app,
            scope,
            receive,
            send,
            relative=relative,
            mode=mode,
        ):
            return
        capability = await self._capabilities.resolve(
            scope,
            receive,
            send,
            relative=relative,
            mode=mode,
        )
        if capability.handled:
            return
        scope = capability.scope
        relative = capability.relative
        capability_route = capability.route
        capability_location = capability.location
        capability_context = capability.context
        presentation_access = capability_route is not None
        if capability_route is None and await delegate_editor_request(
            self.app,
            self._notebooks,
            scope,
            receive,
            send,
            server=self._adapters.server,
            sessions=self._adapters.session_state,
            attachment=self._adapters.sessions,
            persistence=self._adapters.persistence,
            code_mode=self._adapters.code_mode,
            editor_runtime=self._adapters.editor_runtime,
            document_transactions=self._adapters.document_transactions,
            security_policy=self._security_policy,
            relative=relative,
            mode=mode,
            host_session_active=self._host_entry.session_active,
        ):
            return
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive)
        if relative.startswith(f"{SUPPORT_PATH}/assets/"):
            if request.method in {"GET", "HEAD"}:
                response = await file_response(
                    _assets.runtime_assets_path(),
                    relative.removeprefix(f"{SUPPORT_PATH}/assets/"),
                )
            else:
                response = Response(status_code=405)
            if presentation_access:
                grant_capability_headers(response)
            await _send_studio_response(response, scope, receive, send)
            return
        if (
            not presentation_access
            and not has_read_access(scope)
            and is_support_route(relative)
            and _accepts_json(request)
        ):
            await _send_studio_response(
                authentication_required_response(),
                scope,
                receive,
                send,
            )
            return
        if (
            not presentation_access
            and not has_read_access(scope)
            and relative in {"", "/"}
        ):
            await self.app(scope, receive, send)
            return
        authored = authored_view_route(relative)
        if (
            not presentation_access
            and not has_read_access(scope)
            and self._adapters.server.uses_file_routing(scope)
            and ("file" in request.query_params or authored is not None)
            and relative not in {"", "/"}
            and could_handle(relative, mode)
        ):
            response = authentication_redirect(request, base_url)
            await _send_studio_response(response, scope, receive, send)
            return

        request_relative = relative
        location = capability_location
        if location is None:
            location = await self._adapters.server.location(
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
            await _send_studio_response(
                authentication_redirect(request, location.base_url),
                scope,
                receive,
                send,
            )
            return

        notebook_scope = self._notebooks.get(location.notebook)
        presentation = notebook_scope.presentation
        lifecycle = await notebook_scope.lifecycle.resolve(presentation)
        if isinstance(lifecycle, Unconfigured) and not (
            location.mode == "edit"
            and (
                landing
                or is_support_route(relative)
                or relative.strip("/").split("/")[0] == "studio"
            )
        ):
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
                alias_scope = replace_relative_path(scope, request_relative, alias)
                if presentation_access:
                    assert capability_context is not None
                    await send_capability_app(
                        self.app,
                        self._adapters.server.authorize_presentation(
                            alias_scope,
                            capability_context,
                        ),
                        receive,
                        send,
                    )
                else:
                    await self.app(alias_scope, receive, send)
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

        if not presentation_access and (
            has_access_token(scope) or not has_read_access(scope)
        ):
            if relative in {"", "/"} or relative.startswith(f"{SUPPORT_PATH}/assets/"):
                await self.app(scope, receive, send)
            else:
                await _send_studio_response(
                    authentication_redirect(request, location.base_url),
                    scope,
                    receive,
                    send,
                )
            return

        context = self._adapters.server.context(location)
        request_view = (
            capability_route.view
            if capability_route is not None
            else selected_document
            or (
                lifecycle.definition.default_view
                if isinstance(lifecycle, (NeedsView, Invalid))
                and lifecycle.definition is not None
                else _request_view_name(relative, None)
            )
        )
        presentation_session = resolve_presentation_session(
            request,
            context,
            request_view,
            capability_route,
        )
        if (
            capability_route is None
            and presentation_session is None
            and request.method in {"GET", "HEAD"}
            and not landing
            and (relative.endswith("/") or relative in {"", "/"})
            and not relative.startswith(SUPPORT_PATH)
            and authored is None
            and selected_studio is None
            and selected_asset is None
            and relative.strip("/").split("/")[0] != STUDIO_PATH.strip("/")
        ):
            if (
                context.mode == "run"
                and workspace is not None
                and selected_document is not None
                and not request.query_params.getlist(DOCUMENT_REPLAY_QUERY_PARAM)
            ):
                presentation_session = assign_presentation_session(
                    request,
                    context,
                    request_view,
                    self._adapters.session_state,
                    notebook_scope.session_ids,
                    preserve_session=workspace.preserve_session,
                )
            else:
                await _send_studio_response(
                    presentation_session_redirect(
                        request,
                        context,
                        request_view,
                        self._adapters.session_state,
                        notebook_scope.session_ids,
                        preserve_session=(
                            workspace.preserve_session
                            if workspace is not None
                            else False
                        ),
                    ),
                    scope,
                    receive,
                    send,
                )
                return
        if not isinstance(lifecycle, Ready):
            await self._lifecycle_routes.handle(
                LifecycleRoute(
                    scope=scope,
                    request=request,
                    context=context,
                    location=location,
                    notebook_scope=notebook_scope,
                    lifecycle=lifecycle,
                    relative=relative,
                    landing=landing,
                    request_view=request_view,
                    presentation_session=presentation_session,
                    capability=capability_route,
                ),
                receive,
                send,
            )
            return

        await self._ready_routes.handle(
            ReadyWorkspaceRoute(
                scope=scope,
                request=request,
                context=context,
                location=location,
                notebook_scope=notebook_scope,
                lifecycle=lifecycle,
                relative=relative,
                landing=landing,
                request_view=request_view,
                authored=authored,
                selected_document=selected_document,
                selected_studio=selected_studio,
                selected_asset=selected_asset,
                presentation_session=presentation_session,
                capability=capability_route,
            ),
            receive,
            send,
        )


def _accepts_json(request: Request) -> bool:
    return "application/json" in request.headers.get("accept", "")


def _request_view_name(
    relative: str,
    capability: PresentationCapabilityRoute | None,
) -> str:
    if capability is not None:
        return capability.view
    return relative.strip("/").split("/", 1)[0]
