"""Own explicit-host entry documents and native-session transfers."""

from __future__ import annotations

import json
from html import escape

from starlette.requests import HTTPConnection, Request
from starlette.responses import HTMLResponse, JSONResponse, Response
from starlette.types import ASGIApp, Receive, Scope, Send
from starlette.websockets import WebSocket

from marimo_studio._delivery.urls import (
    HOST_SESSION_HANDOFF_QUERY_PARAM,
    SUPPORT_PATH,
    public_url,
)
from marimo_studio._server.agent.clients import StudioClientRegistry
from marimo_studio._server.auth import (
    has_access_token,
    has_edit_access,
    has_read_access,
)
from marimo_studio._server.headers import (
    NO_STORE,
    edit_document_headers,
    edit_document_send,
)
from marimo_studio._server.notebook_scope import NotebookScopeRegistry
from marimo_studio._server.ports import ServerGateway, SessionState
from marimo_studio._server.records import ServerContext
from marimo_studio._server.route_policy import StudioRoutePolicy
from marimo_studio._server.routing import delegates_edit_root, is_studio_route
from marimo_studio._server.security import SecurityPolicy
from marimo_studio._server.studio.session_handoff import (
    HostSessionHandoffRegistry,
    HostSessionTicket,
    HostSessionTransfer,
    HostSessionTransition,
    host_session_handoff_capability_matches,
)

_NATIVE_TRANSPORT_ROUTES = {"/sse", "/ws", "/ws_sync"}
_HOST_HANDOFF_TRANSPORT_ROUTES = {"/sse", "/ws"}


class HostEntryHandler:
    """Route one explicit host through native and Studio documents."""

    def __init__(
        self,
        route_policy: StudioRoutePolicy,
        security_policy: SecurityPolicy,
        server: ServerGateway,
        sessions: SessionState,
        notebooks: NotebookScopeRegistry,
    ) -> None:
        self._route_policy = route_policy
        self._security_policy = security_policy
        self._server = server
        self._sessions = sessions
        self._notebooks = notebooks
        self._handoffs = HostSessionHandoffRegistry()

    def close(self) -> None:
        self._handoffs.close()

    def session_active(self, context: ServerContext, session_id: str) -> bool:
        return self._handoffs.active(context, session_id)

    async def serve(
        self,
        app: ASGIApp,
        scope: Scope,
        receive: Receive,
        send: Send,
        *,
        relative: str,
        mode: str,
    ) -> bool:
        """Serve an explicit-host route and report whether it was handled."""
        if self._route_policy.edit_root != "marimo" or mode != "edit":
            return False
        if delegates_edit_root(relative, mode, self._route_policy):
            await self._serve_native_root(app, scope, receive, send)
            return True
        if relative.rstrip("/") in _NATIVE_TRANSPORT_ROUTES:
            return await self._serve_native_transport(
                app,
                scope,
                receive,
                send,
                relative=relative,
            )
        if self._is_studio_entry(scope, relative):
            return await self._serve_studio_entry(scope, receive, send)
        return False

    async def _serve_native_root(
        self,
        app: ASGIApp,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        if (
            scope["type"] != "http"
            or scope.get("method") not in {"GET", "HEAD"}
            or not has_read_access(scope)
            or has_access_token(scope)
        ):
            await app(scope, receive, send)
            return
        request = Request(scope, receive)
        location = await self._server.location(request)
        if location is None:
            await app(scope, receive, send)
            return
        context = self._server.context(location)
        session_id = request.query_params.get("session_id")
        if session_id is None:
            await self._send_handoff(
                request,
                context,
                scope,
                receive,
                send,
                transition="native",
            )
            return
        capability = request.query_params.get(HOST_SESSION_HANDOFF_QUERY_PARAM)
        if capability is not None:
            await self._authorize_handoff(
                request,
                context,
                session_id,
                capability,
                scope,
                receive,
                send,
            )
            return
        owner = self._sessions.owner(context, session_id)
        clients = self._clients(context)
        studio_owned = owner.state == "current" and (
            self._sessions.editor_identity(context, session_id) is not None
            or (clients is not None and await clients.owns_session(session_id))
            or self._handoffs.active(context, session_id)
        )
        if owner.state == "foreign" or (
            studio_owned
            and (
                owner.claim is None
                or not self._handoffs.contains(context, session_id, owner.claim)
            )
        ):
            await self._send_handoff(
                request,
                context,
                scope,
                receive,
                send,
                transition="reset",
            )
            return
        await app(
            scope,
            receive,
            edit_document_send(send, self._security_policy),
        )

    async def _authorize_handoff(
        self,
        request: Request,
        context: ServerContext,
        session_id: str,
        capability: str,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        owner = self._sessions.owner(context, session_id)
        authorized = (
            self._sessions.is_session_id(session_id)
            and owner.state != "foreign"
            and host_session_handoff_capability_matches(
                capability,
                context,
                session_id,
                request.query_params.multi_items(),
            )
            and (
                owner.state == "unclaimed"
                or self._sessions.matches_creation_query(
                    context,
                    session_id,
                    request.query_params.multi_items(),
                )
            )
        )
        if not authorized:
            await self._send_handoff(
                request,
                context,
                scope,
                receive,
                send,
                transition="reset",
            )
            return
        if owner.state == "current" and owner.claim is not None:
            self._handoffs.authorize(context, session_id, owner.claim)
        await self._send_handoff(
            request,
            context,
            scope,
            receive,
            send,
            transition="complete",
            session_id=session_id,
        )

    def _is_studio_entry(self, scope: Scope, relative: str) -> bool:
        return (
            scope["type"] == "http"
            and scope.get("method") in {"GET", "HEAD"}
            and is_studio_route(relative, "edit")
            and has_read_access(scope)
            and not has_access_token(scope)
        )

    async def _serve_studio_entry(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> bool:
        request = Request(scope, receive)
        if "session_id" in request.query_params:
            return False
        location = await self._server.location(request)
        if location is None:
            return False
        context = self._server.context(location)
        await self._send_handoff(
            request,
            context,
            scope,
            receive,
            send,
            transition="studio",
        )
        return True

    async def _send_handoff(
        self,
        request: Request,
        context: ServerContext,
        scope: Scope,
        receive: Receive,
        send: Send,
        *,
        session_id: str | None = None,
        transition: HostSessionTransition,
    ) -> None:
        response = _handoff_response(
            request,
            context,
            session_id or self._notebooks.allocate_session_id(context, self._sessions),
            self._security_policy,
            transition,
        )
        await response(scope, receive, send)

    async def _serve_native_transport(
        self,
        app: ASGIApp,
        scope: Scope,
        receive: Receive,
        send: Send,
        *,
        relative: str,
    ) -> bool:
        if not has_edit_access(scope):
            return False
        connection = (
            Request(scope, receive)
            if scope["type"] == "http"
            else WebSocket(scope, receive, send)
        )
        session_id = _query_value(connection, "session_id")
        location = await self._server.location(connection) if session_id else None
        if location is None or session_id is None:
            return False
        context = self._server.context(location)
        owner = self._sessions.owner(context, session_id)
        if owner.state == "foreign":
            await _reject_transport(connection, receive, send)
            return True
        if owner.state != "current" or owner.claim is None:
            return False
        identity = self._sessions.editor_identity(context, session_id)
        clients = self._clients(context)
        studio_owned = (
            identity is not None
            or (clients is not None and await clients.owns_session(session_id))
            or self._handoffs.active(context, session_id)
        )
        if relative.rstrip("/") not in _HOST_HANDOFF_TRANSPORT_ROUTES:
            if studio_owned:
                await _reject_transport(connection, receive, send)
                return True
            return False
        authorized = self._sessions.matches_creation_query(
            context,
            session_id,
            connection.query_params.multi_items(),
        ) and self._handoffs.consume(context, session_id, owner.claim)
        if not authorized:
            if studio_owned:
                await _reject_transport(connection, receive, send)
                return True
            return False
        transfer = await HostSessionTransfer.begin(
            context,
            session_id,
            owner.claim,
            identity,
            studio_owned=studio_owned,
            clients=clients,
            sessions=self._sessions,
            handoffs=self._handoffs,
        )
        await transfer.serve(app, scope, receive, send)
        return True

    def _clients(self, context: ServerContext) -> StudioClientRegistry | None:
        scope = self._notebooks.lookup(context.notebook)
        return scope.clients if scope is not None else None


async def _reject_transport(
    connection: Request | WebSocket,
    receive: Receive,
    send: Send,
) -> None:
    if isinstance(connection, WebSocket):
        await connection.close(
            code=1008,
            reason="The host session handoff is not authorized.",
        )
        return
    await JSONResponse(
        {
            "error": "invalid-host-session-handoff",
            "message": "The host session handoff is not authorized.",
        },
        status_code=403,
        headers=NO_STORE,
    )(connection.scope, receive, send)


def _query_value(connection: HTTPConnection, key: str) -> str | None:
    values = connection.query_params.getlist(key)
    return values[0] if len(values) == 1 else None


def _handoff_response(
    request: Request,
    context: ServerContext,
    session_id: str,
    security_policy: SecurityPolicy,
    transition: HostSessionTransition,
) -> Response:
    ticket = HostSessionTicket.issue(
        context,
        session_id,
        request.query_params.multi_items(),
    )
    payload = ticket.browser_config(transition)
    encoded = json.dumps(payload, separators=(",", ":")).replace("<", "\\u003c")
    script_url = escape(
        public_url(context.base_url, f"{SUPPORT_PATH}/assets/host-session-handoff.js"),
        quote=True,
    )
    return HTMLResponse(
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        "<title>Opening notebook</title></head><body>"
        '<p role="status">Opening notebook</p>'
        '<script id="marimo-studio-host-session" type="application/json">'
        f"{encoded}</script>"
        f'<script type="module" src="{script_url}"></script>'
        "</body></html>",
        headers=edit_document_headers(security_policy),
    )
