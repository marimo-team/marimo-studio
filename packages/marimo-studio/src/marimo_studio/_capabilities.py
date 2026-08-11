"""Studio-owned contracts for capabilities supplied by Marimo adapters."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, NewType, Protocol

from starlette.requests import Request
from starlette.types import ASGIApp, Scope
from starlette.websockets import WebSocket

from marimo_studio._agent_transport import StudioServerConnection
from marimo_studio.types import (
    LiveCellSnapshot,
    OutputRenderResult,
    RuntimeProbe,
    SourceSpan,
    ValueReadResult,
    ValueReference,
)

ServerMode = Literal["edit", "run"]
ServerHandle = NewType("ServerHandle", object)


class ASGIMiddlewareFactory(Protocol):
    """Wrap one ASGI application."""

    def __call__(self, app: ASGIApp) -> ASGIApp: ...


@dataclass(frozen=True)
class ServerLocation:
    """Notebook identity and routing data resolved from one Marimo request."""

    notebook: Path
    file_key: str
    base_url: str
    mode: ServerMode
    routing_query: tuple[tuple[str, str], ...]
    handle: ServerHandle = field(repr=False)


@dataclass(frozen=True)
class ServerContext:
    """Stable server values used while Studio handles one notebook request."""

    notebook: Path
    file_key: str
    base_url: str
    mode: ServerMode
    dev: bool
    routing_query: tuple[tuple[str, str], ...]
    user_config: dict[str, object]
    config_overrides: dict[str, object]
    server_token: str
    handle: ServerHandle = field(repr=False)


class CloseHandle(Protocol):
    """Release one idempotent adapter registration or installation."""

    def close(self) -> None: ...


class ServerGateway(Protocol):
    """Translate Marimo ASGI state into stable Studio server records."""

    def base_url(self, scope: Scope) -> str | None: ...

    def mode(self, scope: Scope) -> ServerMode | None: ...

    def uses_file_routing(self, scope: Scope) -> bool: ...

    def location(
        self,
        request: Request | WebSocket,
        selected_file: str | None = None,
    ) -> ServerLocation | None: ...

    def context(self, location: ServerLocation) -> ServerContext: ...

    def relative_path(self, scope: Scope, base_url: str) -> str | None: ...

    def shutdown_requested(self, context: ServerContext) -> bool: ...


class SessionState(Protocol):
    """Read and notify sessions without exposing Marimo session objects."""

    def is_session_id(self, value: object) -> bool: ...

    def exists(self, context: ServerContext, session_id: str) -> bool: ...

    def has_notebook_session(self, context: ServerContext) -> bool: ...

    def live_cells(
        self,
        context: ServerContext,
        session_id: str | None,
    ) -> LiveCellSnapshot | None: ...

    async def reload_page(
        self,
        context: ServerContext,
        view_name: str,
        session_id: str | None = None,
    ) -> None: ...


class ExistingSessionAttachment(Protocol):
    """Attach a consumer to one exact existing Marimo session."""

    def attach(
        self,
        context: ServerContext,
        consumer_id: str,
        session_id: str,
    ) -> bool: ...


class SessionReplay(Protocol):
    """Register documents whose reconnects replay their current session."""

    def configure(self, context: ServerContext, enabled: bool) -> None: ...


@dataclass(frozen=True)
class SaveCell:
    """Stable cell values exposed at the notebook persistence boundary."""

    code: str
    runtime_id: str


@dataclass(frozen=True)
class SourceTransformResult:
    """Transformed source and a callback run after its durable write."""

    source: str
    commit: Callable[[], None] = lambda: None


class SourceTransformSession(Protocol):
    """Transform saves for one live notebook session."""

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
    """Create a source-transform policy for one live notebook."""

    def open(
        self,
        path: Path,
        cells: tuple[SaveCell, ...],
    ) -> SourceTransformSession | None: ...


class NotebookSaveTransform(Protocol):
    """Install Studio's source transform at Marimo's persistence boundary."""

    def enable(self, location: ServerLocation) -> None: ...


class PeerCommandRelay(Protocol):
    """Relay authorized control commands between consumers of one session."""

    def enable(self, location: ServerLocation) -> None: ...


class ProjectionUnavailable(Exception):
    """A live kernel cannot complete one projection operation."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        transient: bool,
        status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.transient = transient
        self.status_code = status_code or (503 if transient else 500)


class QuerySyncUnavailable(Exception):
    """A live editor session cannot accept query state yet."""


class KernelProjectionHost(Protocol):
    """Read values, render owned outputs, and synchronize query state."""

    async def read_values(
        self,
        context: ServerContext,
        session_id: str,
        selectors: tuple[str, ...],
        *,
        consumer_id: str,
    ) -> ValueReadResult: ...

    async def render_outputs(
        self,
        context: ServerContext,
        session_id: str,
        selectors: tuple[str, ...],
        active_selectors: tuple[str, ...],
        *,
        consumer_id: str,
    ) -> OutputRenderResult: ...

    def sync_query(
        self,
        context: ServerContext,
        session_id: str,
        query: dict[str, str | list[str]],
        operation_id: str,
    ) -> None: ...


SelectorSpec = tuple[str, tuple[tuple[str, str | int], ...]]


@dataclass(frozen=True)
class BrowserRuntimeProjection:
    """Browser notebook code and selector data for one runtime instance."""

    instance: str
    version: str
    commit: str
    code: str
    value_specs: Mapping[str, SelectorSpec]
    output_specs: Mapping[str, SelectorSpec]

    def runtime_data(self) -> dict[str, object]:
        return {
            "code": self.code,
            "filename": "notebook.py",
            "version": self.version,
            "valueSpecs": dict(self.value_specs),
            "outputSpecs": dict(self.output_specs),
        }


class BrowserRuntimeProjector(Protocol):
    """Build browser runtime records from a notebook and its projections."""

    version: str
    commit: str

    def project(
        self,
        notebook: Path,
        source: str,
        *,
        values: Mapping[str, ValueReference],
        outputs: Mapping[str, ValueReference],
    ) -> BrowserRuntimeProjection: ...


class LiveNotebookRunner(Protocol):
    """Execute selected projections in an owned headless session."""

    async def __call__(
        self,
        path: Path,
        *,
        cell_ids: tuple[str, ...],
        variables: tuple[str, ...],
        output_selector_groups: tuple[tuple[str, ...], ...],
        show_tracebacks: bool,
        timeout: float,
        value_max_bytes: int | None = None,
    ) -> RuntimeProbe: ...


class CodeModeBridge(Protocol):
    """Adapt Marimo code-mode request state for Studio agents."""

    def attach_session(self, scope: Scope) -> Scope: ...

    def connection(self) -> StudioServerConnection: ...


class AdapterLifecycle(Protocol):
    """Install process-scoped adapter behavior for one application lifespan."""

    def open(self) -> CloseHandle: ...


@dataclass(frozen=True)
class StaticCell:
    """Compiled notebook cell metadata returned by Marimo inspection."""

    runtime_id: str
    code: str
    name: str
    definitions: tuple[str, ...]
    references: tuple[str, ...]
    parents: tuple[str, ...]
    children: tuple[str, ...]
    column: int | None
    disabled: bool
    hide_code: bool
    source: SourceSpan


@dataclass(frozen=True)
class StaticNotebook:
    """Compiled notebook graph and application configuration."""

    cells: tuple[StaticCell, ...]
    app_config: dict[str, object]


class StaticNotebookLoader(Protocol):
    """Compile notebook metadata without running cell bodies."""

    def __call__(self, path: Path) -> StaticNotebook: ...


@dataclass(frozen=True)
class StaticRuntimeConfig:
    """Marimo configuration applied to a static browser runtime."""

    user: Mapping[str, object]
    overrides: Mapping[str, object]


class StaticRuntimeConfigLoader(Protocol):
    """Resolve Marimo configuration for one static browser runtime."""

    def __call__(self, notebook: Path) -> StaticRuntimeConfig: ...


class EnvironmentFlagBuilder(Protocol):
    """Build uv flags for one notebook environment."""

    def __call__(
        self,
        notebook: Path,
        package_requirement: str | None,
        *,
        compose_project: bool,
    ) -> list[str]: ...


@dataclass(frozen=True)
class ServerAdapters:
    """Marimo capabilities consumed by Studio's server process."""

    server: ServerGateway
    session_state: SessionState
    sessions: ExistingSessionAttachment
    replay: SessionReplay
    persistence: NotebookSaveTransform
    projections: KernelProjectionHost
    peer_commands: PeerCommandRelay
    browser: BrowserRuntimeProjector
    code_mode: CodeModeBridge
    lifecycle: AdapterLifecycle


@dataclass(frozen=True)
class ToolingAdapters:
    """Marimo capabilities consumed by checks, inspection, and code mode."""

    notebook: StaticNotebookLoader
    runner: LiveNotebookRunner
    environment: EnvironmentFlagBuilder
    code_mode: CodeModeBridge


@dataclass(frozen=True)
class ExportAdapters:
    """Marimo capabilities consumed by static export."""

    browser: BrowserRuntimeProjector
    runtime_config: StaticRuntimeConfigLoader


CloseCallback = Callable[[], None]


__all__ = [
    "ASGIMiddlewareFactory",
    "AdapterLifecycle",
    "BrowserRuntimeProjection",
    "BrowserRuntimeProjector",
    "CloseCallback",
    "CloseHandle",
    "CodeModeBridge",
    "EnvironmentFlagBuilder",
    "ExistingSessionAttachment",
    "ExportAdapters",
    "KernelProjectionHost",
    "LiveNotebookRunner",
    "NotebookSaveTransform",
    "NotebookSourcePolicy",
    "PeerCommandRelay",
    "ProjectionUnavailable",
    "QuerySyncUnavailable",
    "SaveCell",
    "SelectorSpec",
    "ServerAdapters",
    "ServerContext",
    "ServerGateway",
    "ServerHandle",
    "ServerLocation",
    "ServerMode",
    "SessionReplay",
    "SessionState",
    "SourceTransformResult",
    "SourceTransformSession",
    "StaticCell",
    "StaticNotebook",
    "StaticNotebookLoader",
    "StaticRuntimeConfig",
    "StaticRuntimeConfigLoader",
    "ToolingAdapters",
]
