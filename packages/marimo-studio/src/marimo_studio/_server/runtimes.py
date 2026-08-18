"""Build runtime-specific configuration behind one presentation contract."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from marimo_studio._capabilities import (
    BrowserRuntimeProjector,
    ServerContext,
    SessionState,
)
from marimo_studio._server.server_instance import server_instance_id
from marimo_studio._urls import public_url
from marimo_studio._workspace.models import (
    RUNTIME_PATTERN,
    ResolvedView,
    StudioWorkspace,
)
from marimo_studio.errors import RuntimeSelectionError

if TYPE_CHECKING:
    from marimo_studio._server.presentation import PresentationSnapshot


@dataclass(frozen=True)
class RuntimeProjection:
    instance: str
    data: dict[str, object]
    cell_bindings: dict[str, dict[str, str]]
    value_bindings: dict[str, dict[str, object]]
    output_bindings: dict[str, dict[str, object]]
    control_cells: dict[str, str] | None = None


class RuntimeProvider(Protocol):
    id: str
    label: str

    def project(
        self,
        snapshot: PresentationSnapshot,
        context: ServerContext,
        session_id: str | None,
        binding_id: str | None = None,
    ) -> RuntimeProjection: ...


def _digest(*values: str) -> str:
    digest = hashlib.sha256()
    for value in values:
        digest.update(value.encode("utf-8"))
        digest.update(b"\0")
    return digest.hexdigest()


def _view(snapshot: PresentationSnapshot) -> ResolvedView:
    return snapshot.resolved.views[snapshot.view_name]


class ServerRuntime:
    id = "server"
    label = "Server"

    def __init__(self, sessions: SessionState) -> None:
        self._sessions = sessions

    def project(
        self,
        snapshot: PresentationSnapshot,
        context: ServerContext,
        session_id: str | None,
        binding_id: str | None = None,
    ) -> RuntimeProjection:
        cells = self._sessions.live_cells(context, session_id)
        view = _view(snapshot)
        return RuntimeProjection(
            instance=_digest(
                context.file_key,
                context.base_url,
                context.mode,
                context.server_token,
                binding_id or "",
            ),
            data={
                "url": public_url(context.base_url, "/"),
                "serverToken": context.server_token,
                "serverInstance": server_instance_id(context.server_token),
                "fileKey": context.file_key,
                "preserveSession": snapshot.resolved.workspace.preserve_session,
                **({"file": context.file_key} if context.routing_query else {}),
            },
            cell_bindings=snapshot.resolved.runtime_cell_bindings(
                cells,
                required_aliases=view.cell_aliases,
            ),
            value_bindings=view.runtime_value_bindings(cells),
            output_bindings=view.runtime_output_bindings(cells),
            control_cells=snapshot.resolved.runtime_control_cells(cells),
        )


class WasmRuntime:
    id = "wasm"
    label = "WebAssembly"

    def __init__(self, browser: BrowserRuntimeProjector) -> None:
        self._browser = browser

    def project(
        self,
        snapshot: PresentationSnapshot,
        context: ServerContext,
        session_id: str | None,
        binding_id: str | None = None,
    ) -> RuntimeProjection:
        del context, session_id, binding_id
        view = _view(snapshot)
        projection = self._browser.project(
            snapshot.resolved.workspace.notebook,
            snapshot.notebook_source,
            values=snapshot.value_references,
            outputs=snapshot.output_references,
        )
        return RuntimeProjection(
            instance=projection.instance,
            data=projection.runtime_data(),
            cell_bindings=snapshot.resolved.runtime_cell_bindings(
                None,
                required_aliases=view.cell_aliases,
            ),
            value_bindings=view.runtime_value_bindings(None),
            output_bindings=view.runtime_output_bindings(None),
            control_cells=snapshot.resolved.runtime_control_cells(None),
        )


class RuntimeRegistry:
    """Resolve immutable runtime providers by public runtime ID."""

    def __init__(self, providers: tuple[RuntimeProvider, ...]) -> None:
        if not providers:
            raise ValueError("A runtime registry requires at least one provider")
        for provider in providers:
            if not RUNTIME_PATTERN.fullmatch(provider.id):
                raise ValueError(f"Invalid runtime ID {provider.id!r}")
            if not provider.label:
                raise ValueError(f"Runtime {provider.id!r} requires a label")
        by_id = {provider.id: provider for provider in providers}
        if len(by_id) != len(providers):
            raise ValueError("Runtime providers must have unique IDs")
        self._providers = providers
        self._by_id = by_id

    @property
    def ids(self) -> tuple[str, ...]:
        return tuple(provider.id for provider in self._providers)

    @property
    def options(self) -> tuple[tuple[str, str], ...]:
        return tuple((provider.id, provider.label) for provider in self._providers)

    def available(
        self,
        studio: StudioWorkspace,
        context: ServerContext,
    ) -> tuple[str, ...]:
        configured = self.ids if context.mode == "edit" else studio.runtimes
        return tuple(
            runtime_id for runtime_id in configured if runtime_id in self._by_id
        )

    def select(
        self,
        studio: StudioWorkspace,
        context: ServerContext,
        requested: str | None,
    ) -> tuple[RuntimeProvider, tuple[str, ...]]:
        available = self.available(studio, context)
        selected = requested or studio.default_runtime
        if selected not in available:
            names = ", ".join(available)
            raise RuntimeSelectionError(
                f"Runtime {selected!r} is unavailable. Available runtimes: {names}."
            )
        return self._by_id[selected], available


def create_runtime_registry(
    sessions: SessionState,
    browser: BrowserRuntimeProjector,
) -> RuntimeRegistry:
    """Construct Studio runtime policy from the Marimo adapter bundle."""
    return RuntimeRegistry((ServerRuntime(sessions), WasmRuntime(browser)))


__all__ = [
    "RuntimeProjection",
    "RuntimeProvider",
    "RuntimeRegistry",
    "create_runtime_registry",
]
