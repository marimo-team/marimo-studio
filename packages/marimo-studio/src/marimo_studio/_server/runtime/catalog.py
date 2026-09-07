"""Convert Server and WebAssembly execution into one runtime projection.

Server mode maps saved cell identities to the current native Marimo session and
waits until that session has applied the page's notebook source. WebAssembly
mode transforms saved source into a browser-worker program with the same
executable cell and dependency information.

The registry validates the requested runtime against workspace configuration
and returns a common projection record. Changing execution environment does
not change the published artifact or the meaning of its notebook mounts.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from marimo_studio._delivery.browser_ports import BrowserRuntimeProjector
from marimo_studio._notebook.cell_refs import safe_cell_ref_matches
from marimo_studio._notebook.records import CellRef, LiveCellSnapshot
from marimo_studio._server.ports import SessionState
from marimo_studio._server.presentation.capability import (
    presentation_revision_capability,
    presentation_revision_url,
)
from marimo_studio._server.publication_runtime import PublicationRuntimeProjector
from marimo_studio._server.records import ServerContext
from marimo_studio._server.runtime.progress import RuntimeProgress, RuntimeProgressSink
from marimo_studio._server.runtime.wasm_work import WasmProjectionWork
from marimo_studio._server.server_instance import server_instance_id
from marimo_studio._workspace.models import (
    RUNTIME_PATTERN,
    StudioWorkspace,
)
from marimo_studio.errors import RuntimeSelectionError
from marimo_studio.errors._internal import RuntimeSyncError

if TYPE_CHECKING:
    from marimo_studio._server.notebook_scope import NotebookScopeRegistry
    from marimo_studio._server.presentation.service import PresentationSnapshot


@dataclass(frozen=True)
class RuntimeProjection:
    runtime_id: str
    instance: str
    data: dict[str, object]
    cell_refs: dict[str, str]


@dataclass(frozen=True)
class RuntimeEvidenceProjection(RuntimeProjection):
    current_cell_refs: dict[str, str]
    dependency_closures: dict[str, tuple[str, ...]]


class RuntimeProvider(Protocol):
    id: str
    label: str

    async def close(self) -> None: ...

    async def project(
        self,
        snapshot: PresentationSnapshot,
        context: ServerContext,
        session_id: str | None,
        binding_id: str | None = None,
        presentation_session_id: str | None = None,
        runtime_session_id: str | None = None,
        *,
        client_id: str | None = None,
        progress: RuntimeProgressSink | None = None,
    ) -> RuntimeProjection: ...

    async def project_evidence(
        self,
        snapshot: PresentationSnapshot,
        context: ServerContext,
        session_id: str | None,
        binding_id: str | None = None,
        presentation_session_id: str | None = None,
        runtime_session_id: str | None = None,
        *,
        client_id: str | None = None,
    ) -> RuntimeEvidenceProjection: ...


def _digest(*values: str) -> str:
    digest = hashlib.sha256()
    for value in values:
        digest.update(value.encode("utf-8"))
        digest.update(b"\0")
    return digest.hexdigest()


def _static_dependency_closures(
    snapshot: PresentationSnapshot,
    bindings: dict[str, str],
) -> dict[str, tuple[str, ...]]:
    closures: dict[str, tuple[str, ...]] = {}
    for producer in snapshot.symbols.cells:
        runtime_id = bindings.get(str(producer))
        if runtime_id is None:
            continue
        closure = tuple(
            bindings[str(reference)]
            for reference in snapshot.symbols.dependency_closure(producer)
            if str(reference) in bindings
        )
        closures[runtime_id] = closure
    return closures


class ServerRuntime:
    id = "server"
    label = "Python"

    def __init__(self, sessions: SessionState) -> None:
        self._sessions = sessions
        self._closed = False

    async def close(self) -> None:
        self._closed = True

    def _require_open(self) -> None:
        if self._closed:
            raise RuntimeSyncError("Server runtime projection is shutting down.")

    async def project(
        self,
        snapshot: PresentationSnapshot,
        context: ServerContext,
        session_id: str | None,
        binding_id: str | None = None,
        presentation_session_id: str | None = None,
        runtime_session_id: str | None = None,
        *,
        client_id: str | None = None,
        progress: RuntimeProgressSink | None = None,
    ) -> RuntimeProjection:
        self._require_open()
        if progress is not None:
            progress(RuntimeProgress("Connecting to Python"))
        bindings, _cells = await self._runtime_bindings(
            snapshot,
            context,
            session_id,
            include_dependency_closures=False,
        )
        self._require_open()
        return self._projection(
            snapshot,
            context,
            bindings,
            binding_id,
            presentation_session_id,
            runtime_session_id,
        )

    async def project_evidence(
        self,
        snapshot: PresentationSnapshot,
        context: ServerContext,
        session_id: str | None,
        binding_id: str | None = None,
        presentation_session_id: str | None = None,
        runtime_session_id: str | None = None,
        *,
        client_id: str | None = None,
    ) -> RuntimeEvidenceProjection:
        self._require_open()
        bindings, cells = await self._runtime_bindings(
            snapshot,
            context,
            session_id,
            include_dependency_closures=True,
        )
        self._require_open()
        projection = self._projection(
            snapshot,
            context,
            bindings,
            binding_id,
            presentation_session_id,
            runtime_session_id,
        )
        return RuntimeEvidenceProjection(
            runtime_id=projection.runtime_id,
            instance=projection.instance,
            data=projection.data,
            cell_refs=projection.cell_refs,
            current_cell_refs=(
                {
                    cell.runtime_id: str(cell.ref)
                    for cell in snapshot.resolved.notebook.cells
                }
                if cells is None
                else {
                    runtime_id: str(ref)
                    for runtime_id, ref in cells.current_refs.items()
                }
            ),
            dependency_closures=(
                _static_dependency_closures(snapshot, bindings)
                if cells is None
                else dict(cells.dependency_closures)
            ),
        )

    async def _runtime_bindings(
        self,
        snapshot: PresentationSnapshot,
        context: ServerContext,
        session_id: str | None,
        *,
        include_dependency_closures: bool,
    ) -> tuple[
        dict[str, str],
        LiveCellSnapshot | None,
    ]:
        cells = await self._sessions.live_cells(
            context,
            session_id,
            include_dependency_closures=include_dependency_closures,
        )
        bindings = snapshot.resolved.runtime_cell_refs(cells)
        current_matches = (
            safe_cell_ref_matches(
                {reference: CellRef.parse(reference) for reference in bindings},
                (
                    (reference, runtime_id)
                    for runtime_id, reference in cells.current_refs.items()
                ),
            )
            if cells is not None
            else bindings
        )
        if cells is not None and any(
            current_matches.get(reference) != runtime_id
            for reference, runtime_id in bindings.items()
        ):
            raise RuntimeSyncError(
                "Studio is waiting for the notebook kernel to apply the saved source."
            )
        return bindings, cells

    def _projection(
        self,
        snapshot: PresentationSnapshot,
        context: ServerContext,
        bindings: dict[str, str],
        binding_id: str | None,
        presentation_session_id: str | None,
        runtime_session_id: str | None,
    ) -> RuntimeProjection:
        if presentation_session_id is None:
            raise ValueError("A server runtime requires a presentation session")
        if runtime_session_id is None:
            raise ValueError("A server runtime requires a native runtime session")
        return RuntimeProjection(
            runtime_id=self.id,
            instance=_digest(
                context.file_key,
                context.base_url,
                context.mode,
                context.server_token,
                binding_id or "",
            ),
            data={
                "url": presentation_revision_url(
                    context,
                    snapshot,
                    presentation_session_id,
                    runtime_session_id=runtime_session_id,
                ),
                "capabilityToken": presentation_revision_capability(
                    context,
                    snapshot,
                    presentation_session_id,
                    runtime_session_id,
                ),
                "sessionId": runtime_session_id,
                "serverInstance": server_instance_id(context.server_token),
                "fileKey": context.file_key,
                "preserveSession": snapshot.resolved.workspace.preserve_session,
                **({"file": context.file_key} if context.routing_query else {}),
            },
            cell_refs=bindings,
        )


class WasmRuntime:
    id = "wasm"
    label = "Browser"

    def __init__(self, browser: BrowserRuntimeProjector) -> None:
        self._browser = browser
        self._work = WasmProjectionWork(browser)

    async def close(self) -> None:
        await self._work.close()

    async def project(
        self,
        snapshot: PresentationSnapshot,
        context: ServerContext,
        session_id: str | None,
        binding_id: str | None = None,
        presentation_session_id: str | None = None,
        runtime_session_id: str | None = None,
        *,
        client_id: str | None = None,
        progress: RuntimeProgressSink | None = None,
    ) -> RuntimeProjection:
        del context, binding_id
        if progress is not None:
            progress(RuntimeProgress("Preparing browser notebook"))
        notebook = snapshot.resolved.workspace.notebook
        owner_id = (
            presentation_session_id
            or runtime_session_id
            or session_id
            or snapshot.revision
        )
        projection = await self._work.project(
            notebook,
            snapshot.notebook_source,
            (str(notebook), owner_id),
        )
        bindings = snapshot.resolved.runtime_cell_refs(None)
        return RuntimeProjection(
            runtime_id=self.id,
            instance=projection.instance,
            data=projection.runtime_data(),
            cell_refs=bindings,
        )

    async def project_evidence(
        self,
        snapshot: PresentationSnapshot,
        context: ServerContext,
        session_id: str | None,
        binding_id: str | None = None,
        presentation_session_id: str | None = None,
        runtime_session_id: str | None = None,
        *,
        client_id: str | None = None,
    ) -> RuntimeEvidenceProjection:
        projection = await self.project(
            snapshot,
            context,
            session_id,
            binding_id,
            presentation_session_id,
            runtime_session_id,
            client_id=client_id,
        )
        bindings = projection.cell_refs
        return RuntimeEvidenceProjection(
            runtime_id=projection.runtime_id,
            instance=projection.instance,
            data=projection.data,
            cell_refs=bindings,
            current_cell_refs={
                cell.runtime_id: str(cell.ref)
                for cell in snapshot.resolved.notebook.cells
            },
            dependency_closures=_static_dependency_closures(
                snapshot,
                bindings,
            ),
        )


class ZeroPythonRuntime:
    id = "zero-python"
    label = "Prepared"

    def __init__(self, notebooks: NotebookScopeRegistry) -> None:
        self._notebooks = notebooks
        self._closed = False

    async def close(self) -> None:
        self._closed = True

    def _require_open(self) -> None:
        if self._closed:
            raise RuntimeSyncError("Zero-Python runtime projection is shutting down.")

    async def project(
        self,
        snapshot: PresentationSnapshot,
        context: ServerContext,
        session_id: str | None,
        binding_id: str | None = None,
        presentation_session_id: str | None = None,
        runtime_session_id: str | None = None,
        *,
        client_id: str | None = None,
        progress: RuntimeProgressSink | None = None,
    ) -> RuntimeProjection:
        del runtime_session_id
        self._require_open()
        publications = self._notebooks.get(context.notebook).publications
        if publications is None:
            raise RuntimeSyncError("Zero-Python publication ownership is unavailable.")
        prepared = await PublicationRuntimeProjector(publications).project(
            snapshot,
            context,
            "edit" if context.mode == "edit" else "read",
            session_id,
            binding_id,
            presentation_session_id,
            client_id=client_id,
            progress=progress,
        )
        self._require_open()
        return RuntimeProjection(
            runtime_id=self.id,
            instance=prepared.instance,
            data=prepared.data,
            cell_refs=snapshot.resolved.runtime_cell_refs(None),
        )

    async def project_evidence(
        self,
        snapshot: PresentationSnapshot,
        context: ServerContext,
        session_id: str | None,
        binding_id: str | None = None,
        presentation_session_id: str | None = None,
        runtime_session_id: str | None = None,
        *,
        client_id: str | None = None,
    ) -> RuntimeEvidenceProjection:
        projection = await self.project(
            snapshot,
            context,
            session_id,
            binding_id,
            presentation_session_id,
            runtime_session_id,
            client_id=client_id,
        )
        bindings = projection.cell_refs
        return RuntimeEvidenceProjection(
            runtime_id=projection.runtime_id,
            instance=projection.instance,
            data=projection.data,
            cell_refs=bindings,
            current_cell_refs={
                cell.runtime_id: str(cell.ref)
                for cell in snapshot.resolved.notebook.cells
            },
            dependency_closures=_static_dependency_closures(snapshot, bindings),
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
        self._closed = False

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        for provider in self._providers:
            await provider.close()

    def _require_open(self) -> None:
        if self._closed:
            raise RuntimeSyncError("Runtime projection is shutting down.")

    @property
    def ids(self) -> tuple[str, ...]:
        return tuple(provider.id for provider in self._providers)

    @property
    def options(self) -> tuple[tuple[str, str], ...]:
        return tuple((provider.id, provider.label) for provider in self._providers)

    def options_for(
        self,
        studio: StudioWorkspace,
        context: ServerContext,
    ) -> tuple[tuple[str, str], ...]:
        available = set(self.available(studio, context))
        return tuple(
            (provider.id, provider.label)
            for provider in self._providers
            if provider.id in available
        )

    def configured_options(
        self,
        runtime_ids: tuple[str, ...],
    ) -> tuple[tuple[str, str], ...]:
        return tuple(
            (runtime_id, self._by_id[runtime_id].label)
            for runtime_id in runtime_ids
            if runtime_id in self._by_id
        )

    def available(
        self,
        studio: StudioWorkspace,
        context: ServerContext,
    ) -> tuple[str, ...]:
        return tuple(
            runtime_id
            for runtime_id, _label in self.configured_options(studio.runtimes)
            if context.mode == "edit" or runtime_id != "zero-python"
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

    async def project(
        self,
        snapshot: PresentationSnapshot,
        context: ServerContext,
        requested: str | None,
        session_id: str | None,
        binding_id: str | None = None,
        presentation_session_id: str | None = None,
        runtime_session_id: str | None = None,
        *,
        client_id: str | None = None,
        progress: RuntimeProgressSink | None = None,
    ) -> RuntimeProjection:
        """Capture server state on its owner and offload browser compilation."""
        self._require_open()
        provider, _available = self.select(
            snapshot.resolved.workspace,
            context,
            requested,
        )
        projection = await provider.project(
            snapshot,
            context,
            session_id,
            binding_id,
            presentation_session_id,
            runtime_session_id,
            client_id=client_id,
            progress=progress,
        )
        self._require_open()
        return projection

    async def project_evidence(
        self,
        snapshot: PresentationSnapshot,
        context: ServerContext,
        requested: str | None,
        session_id: str | None,
        binding_id: str | None = None,
        presentation_session_id: str | None = None,
        runtime_session_id: str | None = None,
        *,
        client_id: str | None = None,
    ) -> RuntimeEvidenceProjection:
        """Capture server evidence on its owner and offload browser compilation."""
        self._require_open()
        provider, _available = self.select(
            snapshot.resolved.workspace,
            context,
            requested,
        )
        projection = await provider.project_evidence(
            snapshot,
            context,
            session_id,
            binding_id,
            presentation_session_id,
            runtime_session_id,
            client_id=client_id,
        )
        self._require_open()
        return projection


def create_runtime_registry(
    sessions: SessionState,
    browser: BrowserRuntimeProjector,
    notebooks: NotebookScopeRegistry,
) -> RuntimeRegistry:
    """Construct Studio runtime policy from the Marimo adapter bundle."""
    return RuntimeRegistry(
        (ServerRuntime(sessions), WasmRuntime(browser), ZeroPythonRuntime(notebooks))
    )
