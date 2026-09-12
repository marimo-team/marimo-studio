"""Grant an authored presentation the narrow server access it needs.

Presentation URLs carry signed authority for one notebook, view, presentation
revision, artifact revision, presentation session, and runtime session. After
validating that identity, this module applies the allowed target and method
policy before rewriting a request onto Studio support or native Marimo routes.
Caller-supplied native credentials are replaced only after the presentation
request is accepted.

Stale pages may retain immutable assets, while stale value and output reads
receive a refresh or retry response. Native HTTP, WebSocket, and
server-sent-event connections also pass through explicit session admission, so
an unrelated document or replaced session cannot attach to the live notebook.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import parse_qsl, urlencode

from starlette.requests import ClientDisconnect, Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send
from starlette.websockets import WebSocket

from marimo_studio._delivery.urls import SUPPORT_PATH
from marimo_studio._processes.provider_operation import raise_process_cleanup
from marimo_studio._server.notebook_scope import NotebookScopeRegistry
from marimo_studio._server.ports import ServerGateway, SessionState
from marimo_studio._server.presentation.admission import (
    NATIVE_SESSION_ADMISSION_SCOPE_KEY,
    NativeSessionAdmission,
)
from marimo_studio._server.presentation.capability import (
    PRESENTATION_RESPONSE_HEADERS,
    PresentationCapabilityRoute,
    capability_artifact_target,
    capability_matches,
    capability_matches_snapshot,
    capability_target_matches,
    parse_presentation_capability_route,
    presentation_target_allowed,
    presentation_target_session_header,
)
from marimo_studio._server.presentation.session_ids import SessionIdAllocator
from marimo_studio._server.records import ServerContext, ServerLocation, ServerMode
from marimo_studio._server.request_body import (
    BoundedBodyError,
    bounded_body_error_response,
    read_bounded_body,
)
from marimo_studio._server.routing import could_handle
from marimo_studio.errors import MarimoStudioError

_CAPABILITY_REQUEST_HEADERS = (
    "Content-Type, Marimo-Session-Id, Marimo-Server-Token, "
    "Marimo-Studio-Preview-Session-Id, X-Runtime-Url"
)
_NATIVE_POST_MAX_BYTES = 64 * 1024 * 1024


@dataclass(frozen=True)
class CapabilityResolution:
    """The normalized routing state after capability authorization."""

    scope: Scope
    relative: str
    route: PresentationCapabilityRoute | None = None
    location: ServerLocation | None = None
    context: ServerContext | None = None
    handled: bool = False


class PresentationCapabilityHandler:
    """Authorize signed presentation paths before normal route dispatch."""

    def __init__(
        self,
        app: ASGIApp,
        server: ServerGateway,
        sessions: SessionState,
        notebooks: NotebookScopeRegistry,
    ) -> None:
        self._app = app
        self._server = server
        self._sessions = sessions
        self._notebooks = notebooks

    async def resolve(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
        *,
        relative: str,
        mode: ServerMode,
    ) -> CapabilityResolution:
        route = parse_presentation_capability_route(relative)
        if route is None:
            return CapabilityResolution(scope=scope, relative=relative)
        connection = (
            Request(scope, receive)
            if scope["type"] == "http"
            else WebSocket(scope, receive, send)
        )
        location = await self._server.location(
            connection,
            selected_file=route.file_key,
        )
        context = self._server.context(location) if location is not None else None
        session_ids = (
            self._notebooks.get(location.notebook).session_ids
            if location is not None
            else None
        )
        method = str(scope.get("method", "GET"))
        requested_method = (
            Request(scope).headers.get("Access-Control-Request-Method", "")
            if method == "OPTIONS" and scope["type"] == "http"
            else method
        )
        valid = (
            context is not None
            and capability_matches(route.capability, context)
            and capability_target_matches(route)
            and presentation_target_allowed(
                route,
                requested_method,
                str(scope["type"]),
            )
            and self._session_matches(route, connection, method)
            and self._runtime_mode_matches(route, connection, context)
            and session_ids is not None
            and self._runtime_session_matches(
                route,
                context,
                session_ids,
            )
        )
        retained_runtime_asset = (
            scope["type"] == "http"
            and method in {"GET", "HEAD"}
            and (
                route.target.startswith(f"{SUPPORT_PATH}/assets/")
                or (
                    context is not None
                    and context.mode == "edit"
                    and route.target.startswith("/@file/")
                )
            )
        )
        session_model = (
            context is not None
            and context.mode == "edit"
            and route.target == "/api/kernel/set_model_value"
        )
        if (
            valid
            and route.capability.kind == "revision"
            and not retained_runtime_asset
            and not session_model
        ):
            current = await self._current_revision_matches(route, location, context)
            if not current and route.target in {
                f"{SUPPORT_PATH}/views/{route.view}/values",
                f"{SUPPORT_PATH}/views/{route.view}/outputs",
            }:
                assert isinstance(connection, Request)
                await _send_response(
                    _stale_projection_capability(),
                    scope,
                    receive,
                    send,
                )
                return CapabilityResolution(scope, relative, handled=True)
            valid = current
        if not valid:
            await self._forbid(connection, scope, receive, send)
            return CapabilityResolution(scope, relative, handled=True)
        if method == "OPTIONS":
            assert isinstance(connection, Request)
            await _send_response(
                _capability_preflight(connection, route),
                scope,
                receive,
                send,
            )
            return CapabilityResolution(scope, relative, handled=True)
        assert context is not None and session_ids is not None
        runtime_session_id = route.capability.runtime_session_id
        preauthorized_owner = (
            self._sessions.owner(context, runtime_session_id)
            if runtime_session_id is not None
            else None
        )
        if runtime_session_id is not None and not session_ids.authorize(
            context,
            self._sessions,
            route.view,
            route.session_id,
            runtime_session_id,
            native_admission=route.target in {"/ws", "/sse"},
            expected_owner=preauthorized_owner,
        ):
            await self._forbid(connection, scope, receive, send)
            return CapabilityResolution(scope, relative, handled=True)
        native_admission = None
        if route.target in {"/ws", "/sse"} and runtime_session_id is not None:
            assert preauthorized_owner is not None
            native_admission = NativeSessionAdmission(
                expected_claim=(
                    preauthorized_owner.claim
                    if preauthorized_owner.state == "current"
                    else None
                ),
                file_key=context.file_key,
                mode=("current" if preauthorized_owner.state == "current" else "fresh"),
                notebook=str(context.notebook),
                runtime_session_id=runtime_session_id,
            )
        capability_scope = _bind_native_session(
            replace_relative_path(scope, relative, route.target),
            route,
            method,
            native_admission,
        )
        if route.target in {"/ws", "/sse"}:
            assert runtime_session_id is not None and native_admission is not None
            try:
                await _send_capability_app(
                    self._app,
                    self._server.authorize_presentation(capability_scope, context),
                    receive,
                    send,
                )
            finally:
                if native_admission.rejected:
                    session_ids.cancel_admission(
                        context,
                        route.view,
                        route.session_id,
                        runtime_session_id,
                    )
                else:
                    session_ids.settle_admission(
                        context,
                        self._sessions,
                        route.view,
                        route.session_id,
                        runtime_session_id,
                    )
            return CapabilityResolution(scope, relative, handled=True)
        if not could_handle(route.target, mode):
            assert context is not None
            delegated_receive = receive
            if method == "POST":
                assert isinstance(connection, Request)
                try:
                    body = await read_bounded_body(
                        connection,
                        max_bytes=_NATIVE_POST_MAX_BYTES,
                    )
                except BoundedBodyError as error:
                    response = bounded_body_error_response(error)
                    response.headers.update(PRESENTATION_RESPONSE_HEADERS)
                    await _send_response(response, scope, receive, send)
                    return CapabilityResolution(scope, relative, handled=True)
                delegated_receive = _replay_body(body, receive)
            await _send_capability_app(
                self._app,
                self._server.authorize_presentation(capability_scope, context),
                delegated_receive,
                send,
            )
            return CapabilityResolution(scope, relative, handled=True)
        return CapabilityResolution(
            scope=capability_scope,
            relative=route.target,
            route=route,
            location=location,
            context=context,
        )

    async def _current_revision_matches(
        self,
        route: PresentationCapabilityRoute,
        location: ServerLocation | None,
        context: ServerContext | None,
    ) -> bool:
        if location is None or context is None:
            return False
        presentation = self._notebooks.get(location.notebook).presentation
        if (
            capability_artifact_target(route.target) is not None
            and route.capability.revision is not None
        ):
            retained = presentation.snapshot_for_revision(
                route.view,
                route.capability.revision,
            )
            return retained is not None and capability_matches_snapshot(
                route.capability,
                retained,
            )
        try:
            snapshot = (
                await presentation.display_snapshot_async(route.view)
                if context.mode == "edit"
                else await presentation.snapshot_async(
                    route.view,
                    profile="production",
                )
            )
        except (MarimoStudioError, OSError) as error:
            raise_process_cleanup(error)
            if context.mode != "edit" or not route.target.endswith("/dev/events"):
                return False
            try:
                snapshot = await presentation.latest_snapshot_async(route.view)
            except (MarimoStudioError, OSError) as error:
                raise_process_cleanup(error)
                return False
        return capability_matches_snapshot(route.capability, snapshot)

    @staticmethod
    def _session_matches(
        route: PresentationCapabilityRoute,
        connection: Request | WebSocket,
        method: str,
    ) -> bool:
        presentation_session = connection.headers.get(
            "Marimo-Studio-Preview-Session-Id"
        )
        if (
            presentation_session is not None
            and presentation_session != route.session_id
        ):
            return False
        required_header = presentation_target_session_header(route.target, method)
        if required_header == "Marimo-Studio-Preview-Session-Id":
            runtime_session = route.capability.runtime_session_id
            requested_runtime_session = connection.headers.get("Marimo-Session-Id")
            return (
                presentation_session == route.session_id
                and runtime_session is not None
                and requested_runtime_session in {None, runtime_session}
            )
        if required_header == "Marimo-Session-Id":
            return (
                route.capability.runtime_session_id is not None
                and connection.headers.get(required_header) == route.session_id
            )
        if route.target in {"/ws", "/sse"}:
            return (
                route.capability.runtime_session_id is not None
                and connection.query_params.get("session_id") == route.session_id
            )
        return True

    def _runtime_session_matches(
        self,
        route: PresentationCapabilityRoute,
        context: ServerContext,
        session_ids: SessionIdAllocator,
    ) -> bool:
        runtime_session_id = route.capability.runtime_session_id
        return runtime_session_id is None or session_ids.allows(
            context,
            self._sessions,
            route.view,
            route.session_id,
            runtime_session_id,
        )

    @staticmethod
    def _runtime_mode_matches(
        route: PresentationCapabilityRoute,
        connection: Request | WebSocket,
        context: ServerContext,
    ) -> bool:
        return (
            context.mode != "edit"
            or route.target not in {"/ws", "/sse"}
            or connection.query_params.get("kiosk") == "true"
        )

    @staticmethod
    async def _forbid(
        connection: Request | WebSocket,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        if isinstance(connection, WebSocket):
            await connection.close(code=1008)
            return
        await _send_response(_capability_forbidden(), scope, receive, send)


def grant_capability_headers(response: Response) -> Response:
    response.headers.update(PRESENTATION_RESPONSE_HEADERS)
    return response


def capability_forbidden() -> JSONResponse:
    return _capability_forbidden()


def replace_relative_path(scope: Scope, current: str, target: str) -> Scope:
    """Replace one decoded relative path while preserving its ASGI mount."""
    path = str(scope.get("path", "/"))
    prefix = path[: -len(current)] if current and path.endswith(current) else ""
    updated = dict(scope)
    updated_path = f"{prefix}{target}"
    updated["path"] = updated_path
    updated["raw_path"] = updated_path.encode()
    return updated


def _bind_native_session(
    scope: Scope,
    route: PresentationCapabilityRoute,
    method: str,
    admission: NativeSessionAdmission | None = None,
) -> Scope:
    native_session = route.capability.runtime_session_id
    if native_session is None:
        return scope
    updated = dict(scope)
    if admission is not None:
        updated[NATIVE_SESSION_ADMISSION_SCOPE_KEY] = admission
    if presentation_target_session_header(route.target, method) == "Marimo-Session-Id":
        headers = [
            (name, value)
            for name, value in scope.get("headers", ())
            if bytes(name).lower() != b"marimo-session-id"
        ]
        headers.append((b"marimo-session-id", native_session.encode()))
        updated["headers"] = headers
    if route.target in {"/ws", "/sse"}:
        query = [
            (key, native_session if key == "session_id" else value)
            for key, value in parse_qsl(
                bytes(scope.get("query_string", b"")).decode("latin-1"),
                keep_blank_values=True,
            )
        ]
        updated["query_string"] = urlencode(query).encode("latin-1")
    return updated


async def send_capability_app(
    app: ASGIApp,
    scope: Scope,
    receive: Receive,
    send: Send,
) -> None:
    await _send_capability_app(app, scope, receive, send)


def _replay_body(body: bytes, receive: Receive) -> Receive:
    pending = True

    async def replay() -> Message:
        nonlocal pending
        if pending:
            pending = False
            return {"type": "http.request", "body": body, "more_body": False}
        return await receive()

    return replay


def _capability_preflight(
    request: Request,
    route: PresentationCapabilityRoute,
) -> Response:
    method = request.headers.get("Access-Control-Request-Method", "").upper()
    if not presentation_target_allowed(route, method, "http"):
        return _capability_forbidden()
    return Response(
        status_code=204,
        headers={
            **PRESENTATION_RESPONSE_HEADERS,
            "Access-Control-Allow-Headers": _CAPABILITY_REQUEST_HEADERS,
            "Access-Control-Allow-Methods": method,
            "Access-Control-Max-Age": "600",
        },
    )


def _capability_forbidden() -> JSONResponse:
    return JSONResponse(
        {
            "error": "presentation-capability-forbidden",
            "message": "The presentation cannot use this server operation.",
        },
        status_code=403,
        headers=PRESENTATION_RESPONSE_HEADERS,
    )


def _stale_projection_capability() -> JSONResponse:
    return JSONResponse(
        {
            "error": "stale-projection-binding",
            "message": "The presentation is refreshing its notebook bindings.",
            "transient": True,
        },
        status_code=409,
        headers=PRESENTATION_RESPONSE_HEADERS,
    )


async def _send_response(
    response: Response,
    scope: Scope,
    receive: Receive,
    send: Send,
) -> None:
    response.headers.setdefault("Cache-Control", "no-store")
    await response(scope, receive, send)


async def _send_capability_app(
    app: ASGIApp,
    scope: Scope,
    receive: Receive,
    send: Send,
) -> None:
    async def cors_send(message: Message) -> None:
        if message["type"] == "http.response.start":
            enforced = {
                name.lower().encode(): value.encode()
                for name, value in PRESENTATION_RESPONSE_HEADERS.items()
            }
            headers = [
                (name, value)
                for name, value in message.get("headers", ())
                if bytes(name).lower() not in enforced
            ]
            headers.extend(enforced.items())
            message = {**message, "headers": headers}
        try:
            await send(message)
        except OSError:
            if scope["type"] == "websocket" and message["type"] == "websocket.close":
                return
            raise

    try:
        await app(scope, receive, cors_send)
    except ClientDisconnect:
        if scope["type"] != "http":
            raise
        await Response(status_code=499)(scope, receive, cors_send)
