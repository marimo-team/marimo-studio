"""Route requests while a Studio workspace is not ready."""

from __future__ import annotations

from dataclasses import dataclass

from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp, Receive, Scope, Send

from marimo_studio._delivery.urls import SUPPORT_PATH
from marimo_studio._server.notebook_scope import NotebookScope
from marimo_studio._server.pages import (
    error_response,
    initialization_response,
    page_redirect,
    unconfigured_response,
)
from marimo_studio._server.ports import ServerAdapters
from marimo_studio._server.presentation.access import grant_capability_headers
from marimo_studio._server.presentation.capability import (
    PresentationCapabilityRoute,
    presentation_revision_url,
)
from marimo_studio._server.presentation.service import NotebookPresentation
from marimo_studio._server.presentation.session import PresentationSession
from marimo_studio._server.records import ServerContext, ServerLocation
from marimo_studio._server.runtime.catalog import RuntimeRegistry
from marimo_studio._server.support import support_response
from marimo_studio._server.workspace_lifecycle import Invalid, NeedsView, Unconfigured
from marimo_studio.errors import MarimoStudioError

PendingLifecycle = Unconfigured | NeedsView | Invalid


@dataclass(frozen=True)
class LifecycleRoute:
    """Typed request state shared by incomplete workspace routes."""

    scope: Scope
    request: Request
    context: ServerContext
    location: ServerLocation
    notebook_scope: NotebookScope
    lifecycle: PendingLifecycle
    relative: str
    landing: bool
    request_view: str
    presentation_session: PresentationSession | None
    capability: PresentationCapabilityRoute | None


class LifecycleRouteHandler:
    """Serve configuration, repair, and support states before readiness."""

    def __init__(
        self,
        app: ASGIApp,
        adapters: ServerAdapters,
        runtimes: RuntimeRegistry,
    ) -> None:
        self._app = app
        self._adapters = adapters
        self._runtimes = runtimes

    async def handle(
        self,
        route: LifecycleRoute,
        receive: Receive,
        send: Send,
    ) -> None:
        lifecycle = route.lifecycle
        if isinstance(lifecycle, Invalid):
            response = await self._invalid_response(route)
        elif route.relative.startswith(SUPPORT_PATH):
            response = await self._support_response(route)
        elif route.location.mode == "edit" and (
            route.landing or route.relative.strip("/").split("/")[0] == "studio"
        ):
            redirect = page_redirect(
                route.request,
                route.relative,
                not route.landing,
            )
            if redirect is not None:
                response = redirect
            elif isinstance(lifecycle, Unconfigured):
                response = unconfigured_response(
                    route.request,
                    route.context,
                    lifecycle.notebook,
                    self._runtimes.options,
                    self._adapters.session_state,
                    route.notebook_scope.session_ids,
                )
            else:
                response = initialization_response(
                    route.request,
                    route.context,
                    lifecycle.definition,
                    self._runtimes.configured_options(lifecycle.definition.runtimes),
                    self._adapters.session_state,
                    route.notebook_scope.session_ids,
                )
        elif isinstance(lifecycle, NeedsView):
            response = await self._error_response(route, lifecycle.error)
        else:
            await self._app(route.scope, receive, send)
            return
        if route.capability is not None:
            grant_capability_headers(response)
        await _send_response(response, route.scope, receive, send)

    async def _invalid_response(self, route: LifecycleRoute) -> Response:
        lifecycle = route.lifecycle
        assert isinstance(lifecycle, Invalid)
        if route.relative.startswith(SUPPORT_PATH):
            return await self._support_response(route)
        return await self._error_response(route, lifecycle.error)

    async def _support_response(self, route: LifecycleRoute) -> Response:
        return await support_response(
            route.request,
            route.context,
            route.lifecycle,
            route.notebook_scope,
            route.relative.removeprefix(SUPPORT_PATH),
            server=self._adapters.server,
            session_state=self._adapters.session_state,
            sessions=self._adapters.sessions,
            projections=self._adapters.projections,
            runtimes=self._runtimes,
            presentation_capability=(
                route.capability.capability if route.capability is not None else None
            ),
            presentation_view=(
                route.capability.view if route.capability is not None else None
            ),
        )

    async def _error_response(
        self,
        route: LifecycleRoute,
        error: MarimoStudioError,
    ) -> Response:
        presentation = route.notebook_scope.presentation
        return error_response(
            route.relative,
            error,
            presentation.notebook,
            base_url=route.location.base_url,
            dev=route.context.dev,
            structured=_accepts_json(route.request),
            server_token=route.context.server_token,
            routing_query=route.context.routing_query,
            presentation_events_url=await presentation_events_url(
                route.context,
                presentation,
                route.request_view,
                route.presentation_session,
            ),
            lifecycle_id=request_lifecycle_id(route.request),
            runtime=route.request.query_params.get("runtime", "server"),
            view_name=route.request_view,
        )


def _accepts_json(request: Request) -> bool:
    return "application/json" in request.headers.get("accept", "")


def request_lifecycle_id(request: Request) -> int | None:
    value = request.query_params.get("marimo_studio_lifecycle")
    return (
        int(value)
        if value is not None and value.isdecimal() and int(value) > 0
        else None
    )


async def presentation_events_url(
    context: ServerContext,
    presentation: NotebookPresentation,
    view_name: str,
    session: PresentationSession | None,
) -> str | None:
    if context.mode != "edit" or not view_name or session is None:
        return None
    try:
        snapshot = await presentation.latest_snapshot_async(view_name)
    except (MarimoStudioError, OSError):
        return None
    return presentation_revision_url(
        context,
        snapshot,
        session.session_id,
        f"{SUPPORT_PATH}/dev/events",
        runtime_session_id=session.runtime_session_id,
    )


async def _send_response(
    response: Response,
    scope: Scope,
    receive: Receive,
    send: Send,
) -> None:
    response.headers.setdefault("Cache-Control", "no-store")
    await response(scope, receive, send)
