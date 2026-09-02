"""Route requests against one ready Studio workspace."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from typing import TypeVar

from starlette.requests import Request
from starlette.responses import Response
from starlette.types import Receive, Scope, Send

from marimo_studio._artifacts.retention import ArtifactLease
from marimo_studio._delivery.urls import (
    ACTIVE_VIEW_QUERY_PARAM,
    SUPPORT_PATH,
)
from marimo_studio._processes.ownership import settle_ownership
from marimo_studio._server.files import (
    artifact_file_response,
    close_artifact_response,
)
from marimo_studio._server.lifecycle_handler import (
    presentation_events_url,
    request_lifecycle_id,
)
from marimo_studio._server.notebook_scope import NotebookScope
from marimo_studio._server.pages import (
    authored_document_redirect,
    document_response,
    error_response,
    page_redirect,
    studio_landing_redirect,
    studio_response,
)
from marimo_studio._server.ports import ServerAdapters
from marimo_studio._server.presentation.access import grant_capability_headers
from marimo_studio._server.presentation.capability import PresentationCapabilityRoute
from marimo_studio._server.presentation.ownership import studio_owned_request
from marimo_studio._server.presentation.session import PresentationSession
from marimo_studio._server.records import ServerContext, ServerLocation
from marimo_studio._server.routing import ArtifactAssetRoute, AuthoredViewRoute
from marimo_studio._server.runtime.catalog import RuntimeRegistry
from marimo_studio._server.support import support_response
from marimo_studio._server.workspace_lifecycle import Ready
from marimo_studio.errors import MarimoStudioError

_Owned = TypeVar("_Owned")


@dataclass(frozen=True)
class ReadyWorkspaceRoute:
    """Typed route state after workspace and route selection converge."""

    scope: Scope
    request: Request
    context: ServerContext
    location: ServerLocation
    notebook_scope: NotebookScope
    lifecycle: Ready
    relative: str
    landing: bool
    request_view: str
    authored: AuthoredViewRoute | None
    selected_document: str | None
    selected_studio: str | None
    selected_asset: ArtifactAssetRoute | None
    presentation_session: PresentationSession | None
    capability: PresentationCapabilityRoute | None


class ReadyWorkspaceHandler:
    """Serve documents, artifacts, Studio, and support from a ready workspace."""

    def __init__(
        self,
        adapters: ServerAdapters,
        runtimes: RuntimeRegistry,
    ) -> None:
        self._adapters = adapters
        self._runtimes = runtimes

    async def handle(
        self,
        route: ReadyWorkspaceRoute,
        receive: Receive,
        send: Send,
    ) -> None:
        presentation = route.notebook_scope.presentation
        workspace = route.lifecycle.workspace
        artifact_response: Response | None = None
        try:
            redirect = (
                authored_document_redirect(
                    route.request,
                    route.context,
                    route.selected_document,
                )
                if route.authored is not None
                and route.selected_document is not None
                and route.request.method in {"GET", "HEAD"}
                and not _accepts_json(route.request)
                else page_redirect(
                    route.request,
                    route.relative,
                    route.selected_document is not None
                    or route.selected_studio is not None,
                )
            )
            if redirect is not None:
                response = redirect
            elif route.landing:
                requested_view = route.request.query_params.get(ACTIVE_VIEW_QUERY_PARAM)
                response = studio_landing_redirect(
                    route.request,
                    route.location.base_url,
                    (
                        requested_view
                        if requested_view in workspace.views
                        else workspace.default_view
                    ),
                    route.context.routing_query,
                )
            else:
                self._adapters.peer_commands.enable(route.location)
                if route.selected_document is not None:
                    if route.presentation_session is None:
                        raise RuntimeError("Presentation session was not assigned")
                    response = await document_response(
                        route.request,
                        route.context,
                        presentation,
                        route.relative,
                        route.selected_document,
                        sessions=self._adapters.session_state,
                        clients=route.notebook_scope.clients,
                        replay=self._adapters.replay,
                        runtimes=self._runtimes,
                        marimo_version=self._adapters.browser.version,
                        presentation_session=route.presentation_session,
                        trusted_shell=route.capability is None,
                    )
                elif route.selected_studio is not None:
                    if workspace.cells:
                        self._adapters.persistence.enable(route.location)
                    response = studio_response(
                        route.request,
                        route.context,
                        workspace,
                        route.selected_studio,
                        self._runtimes.configured_options(workspace.runtimes),
                        self._adapters.session_state,
                        route.notebook_scope.session_ids,
                    )
                elif route.selected_asset is not None:
                    response, artifact_response = await self._artifact_response(route)
                else:
                    response = await support_response(
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
                            route.capability.capability
                            if route.capability is not None
                            else None
                        ),
                        presentation_view=(
                            route.capability.view
                            if route.capability is not None
                            else None
                        ),
                    )
        except MarimoStudioError as error:
            response = error_response(
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
        if (
            route.selected_document is not None
            and route.context.mode == "edit"
            and studio_owned_request(route.request)
        ):
            grant_capability_headers(response)
        if artifact_response is not None:
            grant_capability_headers(artifact_response)
        if route.capability is not None:
            grant_capability_headers(response)
        if artifact_response is not None:
            await _send_artifact_response(
                artifact_response,
                route.scope,
                receive,
                send,
            )
        else:
            await _send_response(response, route.scope, receive, send)

    async def _artifact_response(
        self,
        route: ReadyWorkspaceRoute,
    ) -> tuple[Response, Response | None]:
        selected = route.selected_asset
        assert selected is not None
        if route.request.method not in {"GET", "HEAD"}:
            response = Response(status_code=405)
            return response, None
        presentation = route.notebook_scope.presentation
        lease = await _offload_owned(
            lambda: presentation.lease_artifact(selected.view, selected.revision),
            _close_optional_lease,
        )
        if lease is None:
            response = Response(status_code=404)
            return response, None
        response = await _offload_owned(
            lambda: artifact_file_response(
                lease,
                selected.asset,
                head=route.request.method == "HEAD",
                if_none_match=route.request.headers.get("If-None-Match"),
            ),
            close_artifact_response,
        )
        return response, response


def _accepts_json(request: Request) -> bool:
    return "application/json" in request.headers.get("accept", "")


async def _complete_task(task: asyncio.Task[_Owned]) -> _Owned:
    result, cancellation = await settle_ownership(task)
    if cancellation is not None:
        raise cancellation
    return result


async def _finish_cleanup(cleanup: Callable[[], None]) -> None:
    task = asyncio.create_task(asyncio.to_thread(cleanup))
    await _complete_task(task)


async def _offload_owned(
    operation: Callable[[], _Owned],
    close: Callable[[_Owned], None],
) -> _Owned:
    task = asyncio.create_task(asyncio.to_thread(operation))
    try:
        return await asyncio.shield(task)
    except BaseException as operation_error:
        try:
            owned, _deferred_cancellation = await settle_ownership(task)
        except BaseException:
            raise operation_error.with_traceback(
                operation_error.__traceback__
            ) from None
        try:
            await _finish_cleanup(lambda: close(owned))
        except BaseException as cleanup_error:
            raise cleanup_error from operation_error
        raise operation_error.with_traceback(operation_error.__traceback__) from None


def _close_optional_lease(lease: ArtifactLease | None) -> None:
    if lease is not None:
        lease.close()


async def _send_artifact_response(
    response: Response,
    scope: Scope,
    receive: Receive,
    send: Send,
) -> None:
    response.headers.setdefault("Cache-Control", "no-store")
    try:
        await response(scope, receive, send)
    finally:
        await _finish_cleanup(lambda: close_artifact_response(response))


async def _send_response(
    response: Response,
    scope: Scope,
    receive: Receive,
    send: Send,
) -> None:
    response.headers.setdefault("Cache-Control", "no-store")
    await response(scope, receive, send)
