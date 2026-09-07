"""Marimo adapter ports consumed by Studio server services."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

from starlette.requests import Request
from starlette.types import ASGIApp, Receive, Scope, Send
from starlette.websockets import WebSocket

from marimo_studio._browser_client.ports import CodeModeBridge
from marimo_studio._delivery.browser_ports import BrowserRuntimeProjector
from marimo_studio._notebook.records import LiveCellSnapshot
from marimo_studio._server.presentation.ports import KernelProjectionHost
from marimo_studio._server.records import (
    SaveCell,
    ServerContext,
    ServerLocation,
    ServerMode,
    SourceTransformResult,
)


class ASGIMiddlewareFactory(Protocol):
    def __call__(self, app: ASGIApp) -> ASGIApp: ...


class CloseHandle(Protocol):
    def close(self) -> None: ...


@dataclass(frozen=True)
class SessionOwner:
    state: Literal["unclaimed", "current", "foreign"]
    claim: object | None


@dataclass(frozen=True)
class EditorSessionIdentity:
    client_id: str
    capability: str


class ServerGateway(Protocol):
    def base_url(self, scope: Scope) -> str | None: ...

    def mode(self, scope: Scope) -> ServerMode | None: ...

    def uses_file_routing(self, scope: Scope) -> bool: ...

    async def location(
        self,
        request: Request | WebSocket,
        selected_file: str | None = None,
    ) -> ServerLocation | None: ...

    async def session_location(
        self,
        request: Request | WebSocket,
        session_id: str,
    ) -> ServerLocation | None: ...

    def context(self, location: ServerLocation) -> ServerContext: ...

    def relative_path(self, scope: Scope, base_url: str) -> str | None: ...

    def authorize_presentation(
        self,
        scope: Scope,
        context: ServerContext,
    ) -> Scope: ...

    def shutdown_requested(self, context: ServerContext) -> bool: ...


class EditorRuntimeBootstrap(Protocol):
    async def serve(
        self,
        app: ASGIApp,
        scope: Scope,
        receive: Receive,
        send: Send,
        *,
        resource_path: str,
        runtime_url: str,
        eager_runtime: bool,
    ) -> bool: ...


class DocumentTransactionEvidence(Protocol):
    async def serve(
        self,
        app: ASGIApp,
        scope: Scope,
        send: Send,
        body: bytes,
    ) -> None: ...


class SessionState(Protocol):
    async def close(self) -> None: ...

    def is_session_id(self, value: object) -> bool: ...

    def exists(self, context: ServerContext, session_id: str) -> bool: ...

    def request_studio_reload(
        self,
        context: ServerContext,
        session_id: str,
        *,
        host_handoff: str | None = None,
    ) -> bool: ...

    def matches_creation_query(
        self,
        context: ServerContext,
        session_id: str,
        query: Sequence[tuple[str, str]],
    ) -> bool: ...

    def owner(self, context: ServerContext, session_id: str) -> SessionOwner: ...

    def editor_identity(
        self,
        context: ServerContext,
        session_id: str,
    ) -> EditorSessionIdentity | None: ...

    def release_editor_identity(
        self,
        context: ServerContext,
        session_id: str,
    ) -> bool: ...

    def retry_startup(
        self,
        context: ServerContext,
        session_id: str,
        expected_claim: object,
    ) -> bool: ...

    def ownership(
        self,
        context: ServerContext,
        session_id: str,
    ) -> Literal["unclaimed", "current", "foreign"]: ...

    def ensure_started(self, context: ServerContext, session_id: str) -> bool: ...

    def has_notebook_session(self, context: ServerContext) -> bool: ...

    async def live_cells(
        self,
        context: ServerContext,
        session_id: str | None,
        *,
        include_dependency_closures: bool,
    ) -> LiveCellSnapshot | None: ...

    async def control_bindings(
        self, context: ServerContext, session_id: str
    ) -> dict[str, object]: ...


class ExistingSessionAttachment(Protocol):
    def claim_editor_lifetime(self, context: ServerContext) -> object | None: ...

    def attach(
        self,
        context: ServerContext,
        consumer_id: str,
        session_id: str,
    ) -> bool: ...


class SessionReplay(Protocol):
    def configure(self, context: ServerContext, enabled: bool) -> None: ...


class SourceTransformSession(Protocol):
    def transform(
        self,
        path: Path,
        source: str,
        *,
        persist: bool,
        cells: tuple[SaveCell, ...],
    ) -> SourceTransformResult: ...

    def close(self) -> None: ...


class NotebookSourcePolicy(Protocol):
    def open(
        self,
        path: Path,
        cells: tuple[SaveCell, ...],
    ) -> SourceTransformSession | None: ...


class NotebookSaveTransform(Protocol):
    def enable(self, location: ServerLocation) -> None: ...


class PeerCommandRelay(Protocol):
    def enable(self, location: ServerLocation) -> None: ...


class AdapterLifecycle(Protocol):
    def open(self) -> CloseHandle: ...


@dataclass(frozen=True)
class ServerAdapters:
    server: ServerGateway
    editor_runtime: EditorRuntimeBootstrap
    document_transactions: DocumentTransactionEvidence
    session_state: SessionState
    sessions: ExistingSessionAttachment
    replay: SessionReplay
    persistence: NotebookSaveTransform
    projections: KernelProjectionHost
    peer_commands: PeerCommandRelay
    browser: BrowserRuntimeProjector
    code_mode: CodeModeBridge
    lifecycle: AdapterLifecycle


CloseCallback = Callable[[], None]
