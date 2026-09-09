"""Delegate native editor traffic while attaching Studio session context."""

from __future__ import annotations

import asyncio
import hmac
import re
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from typing import Literal
from urllib.parse import parse_qsl, urlsplit

from starlette.requests import HTTPConnection, Request
from starlette.responses import JSONResponse, RedirectResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send
from starlette.websockets import WebSocket

from marimo_studio._browser_client.ports import CodeModeBridge
from marimo_studio._delivery.urls import (
    EDITOR_BINDING_CAPABILITY_QUERY_PARAM,
    SERVER_INSTANCE_QUERY_PARAM,
    STUDIO_CLIENT_QUERY_PARAM,
)
from marimo_studio._server.auth import has_edit_access
from marimo_studio._server.headers import NO_STORE, edit_document_send
from marimo_studio._server.notebook_scope import NotebookScopeRegistry
from marimo_studio._server.ports import (
    DocumentTransactionEvidence,
    EditorRuntimeBootstrap,
    ExistingSessionAttachment,
    NotebookSaveTransform,
    ServerGateway,
    SessionState,
)
from marimo_studio._server.presentation.admission import (
    NATIVE_SESSION_ADMISSION_SCOPE_KEY,
    NativeSessionAdmission,
)
from marimo_studio._server.records import ServerContext
from marimo_studio._server.request_body import (
    BoundedBodyError,
    bounded_body_error_response,
    read_bounded_body,
)
from marimo_studio._server.routing import native_editor_target
from marimo_studio._server.security import DEFAULT_SECURITY_POLICY, SecurityPolicy
from marimo_studio._server.server_instance import server_instance_id
from marimo_studio._server.studio.editor_capability import (
    editor_binding_capability_matches,
)
from marimo_studio._server.studio.session_handoff import HostSessionTicket
from marimo_studio._workspace import discover_studio
from marimo_studio.errors import MarimoStudioError

_CODE_MODE_ROUTES = {"/api/ai/chat", "/api/kernel/execute"}
_SAVE_ROUTE = "/api/kernel/save"
_DOCUMENT_TRANSACTION_MAX_BYTES = 64 * 1024 * 1024
EditorBindingResult = Literal["absent", "bound", "invalid"]


@dataclass(frozen=True)
class EditorBinding:
    status: EditorBindingResult
    admission: NativeSessionAdmission | None = None
    session_id: str | None = None


async def delegate_editor_request(
    app: ASGIApp,
    notebooks: NotebookScopeRegistry,
    scope: Scope,
    receive: Receive,
    send: Send,
    *,
    server: ServerGateway,
    sessions: SessionState,
    attachment: ExistingSessionAttachment,
    persistence: NotebookSaveTransform,
    code_mode: CodeModeBridge,
    editor_runtime: EditorRuntimeBootstrap,
    document_transactions: DocumentTransactionEvidence,
    relative: str,
    mode: str,
    security_policy: SecurityPolicy = DEFAULT_SECURITY_POLICY,
    host_session_active: Callable[[ServerContext, str], bool] | None = None,
) -> bool:
    """Delegate one editor or code-mode request and report whether it matched."""
    editor_target = native_editor_target(relative)
    if editor_target is not None and mode == "edit":
        delegated_scope = _replace_relative_path(scope, relative, editor_target)
        connection = (
            Request(scope, receive)
            if scope["type"] == "http"
            else WebSocket(scope, receive, send)
        )
        location = await server.location(connection)
        binding = EditorBinding("absent")
        context: ServerContext | None = None
        native_transport = editor_target in {"/ws", "/ws_sync", "/sse"}
        editor_root = editor_target.rstrip("/") == ""
        if location is not None:
            context = server.context(location)
            lifetime_owner = attachment.claim_editor_lifetime(context)
            if lifetime_owner is None:
                if isinstance(connection, WebSocket):
                    await connection.close(
                        code=1013,
                        reason="The editor session is shutting down.",
                    )
                else:
                    await JSONResponse(
                        {
                            "error": "editor-session-closing",
                            "message": "The Studio editor session is shutting down.",
                            "transient": True,
                        },
                        status_code=503,
                        headers=NO_STORE,
                    )(scope, receive, send)
                return True
            binding = await _bind_editor_session(
                notebooks,
                connection,
                context,
                sessions,
                bind_session=native_transport or editor_root,
                expected_server_instance=server_instance_id(context.server_token),
                lifetime_owner=lifetime_owner,
                host_session_active=host_session_active,
            )
            binding_required = (
                native_transport
                or editor_root
                or any(
                    key in connection.query_params
                    for key in {
                        EDITOR_BINDING_CAPABILITY_QUERY_PARAM,
                        STUDIO_CLIENT_QUERY_PARAM,
                    }
                )
            )
            if binding.status in {"absent", "invalid"} and binding_required:
                if isinstance(connection, WebSocket):
                    await connection.close(
                        code=1008,
                        reason="The editor binding capability is invalid.",
                    )
                else:
                    await JSONResponse(
                        {
                            "error": "invalid-editor-binding",
                            "message": (
                                "The Studio editor binding capability is invalid."
                            ),
                        },
                        status_code=403,
                        headers=NO_STORE,
                    )(scope, receive, send)
                return True
            if (
                isinstance(connection, Request)
                and editor_target.rstrip("/") == ""
                and "session_id" not in connection.query_params
                and binding.session_id is not None
            ):
                await RedirectResponse(
                    str(
                        connection.url.include_query_params(
                            session_id=binding.session_id
                        )
                    ),
                    status_code=307,
                    headers=NO_STORE,
                )(scope, receive, send)
                return True
            if binding.admission is not None:
                delegated_scope = {
                    **delegated_scope,
                    NATIVE_SESSION_ADMISSION_SCOPE_KEY: binding.admission,
                }
        workspace = None
        if scope["type"] == "http" and location is not None:
            with suppress(MarimoStudioError):
                workspace = discover_studio(location.notebook)
            if workspace is not None and workspace.cells:
                persistence.enable(location)
            if editor_target.rstrip("/") in _CODE_MODE_ROUTES:
                delegated_scope = code_mode.attach_session(
                    delegated_scope,
                    location.notebook,
                )
        delegated_send = (
            edit_document_send(send, security_policy)
            if scope["type"] == "http" and editor_root
            else send
        )
        served = False
        if (
            scope["type"] == "http"
            and isinstance(connection, Request)
            and connection.method == "POST"
            and editor_target.rstrip("/") == "/api/document/transaction"
        ):
            try:
                body = await read_bounded_body(
                    connection,
                    max_bytes=_DOCUMENT_TRANSACTION_MAX_BYTES,
                )
            except BoundedBodyError as error:
                await bounded_body_error_response(error)(scope, receive, send)
                return True
            await document_transactions.serve(
                app,
                delegated_scope,
                send,
                body,
            )
            served = True
        if (
            not served
            and scope["type"] == "http"
            and isinstance(connection, Request)
            and connection.method == "GET"
        ):
            served = await editor_runtime.serve(
                app,
                delegated_scope,
                receive,
                delegated_send,
                resource_path=editor_target,
                runtime_url=str(connection.url),
                eager_runtime=workspace is not None,
            )
        if not served:
            await app(delegated_scope, receive, delegated_send)
        return True

    if (
        scope["type"] == "http"
        and mode == "edit"
        and relative.rstrip("/") in _CODE_MODE_ROUTES
    ):
        connection = Request(scope, receive)
        location = await server.location(connection)
        if location is None:
            await app(scope, receive, send)
            return True
        delegated_scope = code_mode.attach_session(scope, location.notebook)
        await app(delegated_scope, receive, send)
        return True
    if (
        scope["type"] == "http"
        and mode == "edit"
        and relative.rstrip("/") == _SAVE_ROUTE
    ):
        request = Request(scope, receive)
        if STUDIO_CLIENT_QUERY_PARAM in request.query_params:
            return False
        session_id = request.headers.get("Marimo-Session-Id")
        location = await server.location(request)
        request_base_url = server.base_url(scope)
        status: int | None = None

        async def track_response(message: Message) -> None:
            nonlocal status
            if message.get("type") == "http.response.start":
                value = message.get("status")
                status = value if isinstance(value, int) else None
            await send(message)

        await app(scope, receive, track_response)
        if status is not None and 200 <= status < 300 and session_id is not None:
            saved_location = await server.session_location(request, session_id)
            if saved_location is not None:
                location = saved_location
            if location is not None and await asyncio.to_thread(
                location.notebook.is_file
            ):
                context = server.context(location)
                sessions.request_studio_reload(
                    context,
                    session_id,
                    host_handoff=HostSessionTicket.issue(
                        context,
                        session_id,
                        _save_page_query(request),
                        public_base_url=(
                            context.base_url
                            if request_base_url is None
                            else request_base_url
                        ),
                    ).capability,
                )
        return True
    return False


async def _bind_editor_session(
    notebooks: NotebookScopeRegistry,
    connection: HTTPConnection,
    context: ServerContext,
    sessions: SessionState,
    *,
    bind_session: bool,
    expected_server_instance: str,
    lifetime_owner: object,
    host_session_active: Callable[[ServerContext, str], bool] | None = None,
) -> EditorBinding:
    if not has_edit_access(connection.scope):
        return EditorBinding("invalid")
    client_id = _query_value(connection, STUDIO_CLIENT_QUERY_PARAM)
    session_id = _query_value(connection, "session_id")
    capability = _query_value(connection, EDITOR_BINDING_CAPABILITY_QUERY_PARAM)
    server_instance = _query_value(connection, SERVER_INSTANCE_QUERY_PARAM)
    if (
        client_id is None
        or capability is None
        or server_instance != expected_server_instance
        or re.fullmatch(r"[A-Za-z0-9_-]{16,128}", client_id) is None
    ):
        return EditorBinding("absent")
    if session_id is None and "session_id" in connection.query_params:
        return EditorBinding("invalid")
    notebook_scope = notebooks.get(context.notebook)
    retained = await notebook_scope.clients.binding_for_client(client_id)
    if session_id is None:
        if retained is None:
            return EditorBinding("absent")
        session_id = retained.session_id
    if not sessions.is_session_id(session_id):
        return EditorBinding("invalid")
    if host_session_active is not None and host_session_active(context, session_id):
        return EditorBinding("invalid")
    if not editor_binding_capability_matches(
        capability,
        context,
        client_id,
        session_id,
    ):
        return EditorBinding("invalid")
    if retained is not None and retained.session_id != session_id:
        return EditorBinding("invalid")
    owner = sessions.owner(context, session_id)
    if owner.state == "foreign":
        return EditorBinding("invalid")
    if owner.state == "current":
        identity = sessions.editor_identity(context, session_id)
        if identity is not None and (
            identity.client_id != client_id
            or not hmac.compare_digest(identity.capability, capability)
        ):
            return EditorBinding("invalid")
    if not bind_session:
        return EditorBinding("bound", session_id=session_id)
    binding = await notebook_scope.clients.bind_session(
        session_id,
        client_id,
        new_incarnation=owner.state == "unclaimed",
    )
    if binding is None:
        return EditorBinding("invalid")
    lease_holder = [binding]

    def reject_binding() -> None:
        current_owner = sessions.owner(context, session_id)
        current_identity = sessions.editor_identity(context, session_id)
        if (
            not admission.force_reject_binding
            and current_owner.state == "current"
            and current_identity is not None
            and current_identity.client_id == client_id
            and hmac.compare_digest(current_identity.capability, capability)
        ):
            return
        notebook_scope.clients.reject_session_binding(lease_holder[0])

    def accept_binding(native_claim: object) -> None:
        accepted = notebook_scope.clients.accept_session_binding(
            lease_holder[0],
            native_claim,
        )
        if accepted is not None:
            lease_holder[0] = accepted
            accepted.native_close_callback = close_binding
            sessions.retry_startup(context, session_id, native_claim)

    def close_binding() -> asyncio.Task[None] | None:
        return notebook_scope.clients.native_session_closed(lease_holder[0])

    binding.native_close_callback = close_binding
    admission = NativeSessionAdmission(
        expected_claim=owner.claim,
        file_key=context.file_key,
        mode="current" if owner.state == "current" else "fresh",
        notebook=str(context.notebook),
        runtime_session_id=session_id,
        binding_current=lambda: lease_holder[0].phase == "active",
        on_accept=accept_binding,
        on_reject=reject_binding,
        on_close=close_binding,
        lifetime_owner=lifetime_owner,
        replay_on_reconnect=True,
    )
    return EditorBinding("bound", admission, session_id)


def _query_value(connection: HTTPConnection, key: str) -> str | None:
    values = connection.query_params.getlist(key)
    return values[0] if len(values) == 1 else None


def _save_page_query(request: Request) -> list[tuple[str, str]]:
    query = request.query_params.multi_items()
    referrer = request.headers.get("referer")
    if referrer is None:
        return query
    try:
        page = urlsplit(referrer)
    except ValueError:
        return query
    if page.scheme != request.url.scheme or page.netloc != request.url.netloc:
        return query
    # Native save requests omit the page query. The referrer follows query
    # changes made after the notebook session opened.
    return parse_qsl(page.query, keep_blank_values=True)


def _replace_relative_path(scope: Scope, current: str, target: str) -> Scope:
    path = str(scope.get("path", "/"))
    prefix = path[: -len(current)] if current and path.endswith(current) else ""
    updated = dict(scope)
    updated_path = f"{prefix}{target}"
    updated["path"] = updated_path
    updated["raw_path"] = updated_path.encode()
    return updated
