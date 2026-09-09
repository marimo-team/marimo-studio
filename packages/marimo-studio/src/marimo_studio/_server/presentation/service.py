"""Own the coherent presentation snapshots served for one notebook.

A presentation snapshot binds saved notebook source, Studio configuration,
the notebook symbol graph, provider-declared mounts, and one leased immutable
artifact into one presentation revision. Page rendering, runtime configuration,
projection routes, and browser evidence all resolve against that same captured
state. Validation independently checks the corresponding published
presentation revisions.

The service caches current snapshots and retains a bounded history so a page
can finish revision-qualified requests after a newer build publishes. During
edits or provider failures it can continue serving the last verified
publication while current source is repaired. History eviction releases older
leases, while view deletion and notebook shutdown release every retained
snapshot.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from threading import RLock
from typing import TYPE_CHECKING

from marimo_studio._artifacts.paths import artifact_root
from marimo_studio._artifacts.records import ViewArtifact
from marimo_studio._artifacts.repository import read_build_state
from marimo_studio._artifacts.retention import ArtifactLease
from marimo_studio._processes.provider_operation import raise_process_cleanup
from marimo_studio._projections.resolved import ResolvedStudio
from marimo_studio._projections.symbol_graph import NotebookSymbolGraph
from marimo_studio._views.presentation_publication import publish_presentation
from marimo_studio._views.resolve import resolve_studio
from marimo_studio._views.revisions import (
    PreparedViewProject,
    capture_presentations,
    capture_published_presentations,
)
from marimo_studio._workspace import discover_studio
from marimo_studio._workspace.config import (
    discover_studio_definition,
    materialize_studio_workspace,
    materialize_studio_workspace_after_conflict,
)
from marimo_studio._workspace.models import (
    StudioDefinition,
    StudioWorkspace,
)
from marimo_studio.errors import (
    ConfigurationError,
    MarimoStudioError,
    ViewProjectError,
    WorkspaceGenerationConflictError,
)
from marimo_studio.errors._internal import ArtifactIntegrityError, RuntimeSyncError
from marimo_studio.view_providers import (
    BuildProfile,
    MountDeclaration,
    ProjectInspection,
    ViewProject,
)

if TYPE_CHECKING:
    from marimo_studio._server.development.coordinator import DevelopmentCoordinator

_SNAPSHOT_HISTORY_LIMIT = 8
_SNAPSHOT_RECONCILIATION_LIMIT = 8
_SnapshotKey = tuple[str, BuildProfile]


@dataclass(frozen=True)
class PresentationSnapshot:
    """One artifact and notebook graph captured as a presentation revision."""

    resolved: ResolvedStudio
    view_name: str
    artifact: ViewArtifact
    document: str
    notebook_source: str
    source_revision: str
    symbols: NotebookSymbolGraph
    mounts: tuple[MountDeclaration, ...]
    revision: str


class NotebookPresentation:
    """Cache notebook inspection while configuration inputs stay unchanged."""

    def __init__(
        self,
        notebook: Path,
        *,
        development: DevelopmentCoordinator | None = None,
    ) -> None:
        self.notebook = notebook
        self._development = development
        self._lock = RLock()
        self._view_locks: dict[str, RLock] = {}
        self._snapshots: dict[_SnapshotKey, PresentationSnapshot] = {}
        self._snapshot_history: dict[str, dict[str, PresentationSnapshot]] = {}
        self._snapshot_leases: dict[str, dict[str, ArtifactLease]] = {}
        self._snapshot_generations: dict[_SnapshotKey, int] = {}
        self._snapshot_notebook_stamps: dict[_SnapshotKey, tuple[int, int, int]] = {}
        self._snapshot_document_stamps: dict[
            _SnapshotKey,
            tuple[tuple[str, int, int, int], ...],
        ] = {}
        self._snapshot_publication_stamps: dict[
            _SnapshotKey,
            tuple[int, int, int, int] | None,
        ] = {}
        self._closed = False

    def discover(self) -> StudioWorkspace | None:
        return discover_studio(self.notebook)

    def discover_definition(self) -> StudioDefinition | None:
        """Return configuration before workspace materialization."""
        return discover_studio_definition(self.notebook)

    def materialize(self, definition: StudioDefinition) -> StudioWorkspace:
        """Resolve the current authored views for a definition."""
        try:
            return materialize_studio_workspace(definition)
        except WorkspaceGenerationConflictError:
            return materialize_studio_workspace_after_conflict(definition)

    def snapshot(
        self,
        view_name: str | None,
        *,
        profile: BuildProfile = "development",
    ) -> PresentationSnapshot:
        snapshot = self._resolve_snapshot(view_name, published=False, profile=profile)
        if snapshot is not None:
            return snapshot
        raise RuntimeSyncError(
            "The view sources are still changing. Studio will retry shortly."
        )

    def display_snapshot(
        self,
        view_name: str,
        *,
        profile: BuildProfile = "development",
    ) -> PresentationSnapshot:
        """Return the last verified publication while current source validates."""
        published = self._resolve_snapshot(
            view_name,
            published=True,
            profile=profile,
        )
        return (
            published
            if published is not None
            else self.snapshot(view_name, profile=profile)
        )

    def _resolve_snapshot(
        self,
        view_name: str | None,
        *,
        published: bool,
        profile: BuildProfile,
        prepared: PreparedViewProject | None = None,
    ) -> PresentationSnapshot | None:
        for _attempt in range(3):
            studio = self.discover()
            if studio is None:
                raise ConfigurationError(
                    f"No Marimo Studio configuration found for {self.notebook}"
                )
            selected = view_name or studio.default_view
            coordination = self._coordination_lock(selected)
            with coordination:
                self._ensure_open()
                current = self.discover()
                if current is None:
                    continue
                current_selected = view_name or current.default_view
                if current_selected != selected:
                    continue
                if selected not in current.views:
                    raise ConfigurationError(f"Unknown view {selected!r}")
                self._prune_snapshots(current)
                snapshot = self._capture_snapshot(
                    current,
                    selected,
                    default_selected=view_name is None,
                    published=published,
                    profile=profile,
                    prepared=prepared,
                )
                if snapshot is not None:
                    return snapshot
        return None

    def _capture_snapshot(
        self,
        studio: StudioWorkspace,
        selected: str,
        *,
        default_selected: bool,
        published: bool,
        profile: BuildProfile,
        prepared: PreparedViewProject | None,
    ) -> PresentationSnapshot | None:
        try:
            source = (
                capture_published_presentations(
                    studio,
                    (selected,),
                    profile=profile,
                )
                if published
                else capture_presentations(
                    studio,
                    (selected,),
                    profile=profile,
                    prepared=({selected: prepared} if prepared is not None else None),
                )
            )
            if source is None:
                return None
            with source as before:
                revision = before.revision(selected)
                key = (selected, profile)
                with self._lock:
                    if self._closed:
                        raise RuntimeError("Notebook presentation is closed")
                    cached = self._snapshots.get(key)
                if cached is not None and cached.revision == revision:
                    return cached
                candidate_lease = before.take_lease(selected)
        except OSError as error:
            raise_process_cleanup(error)
            return None
        try:
            artifact = candidate_lease.artifact
            try:
                resolved = resolve_studio(
                    studio,
                    view_name=selected,
                    published_mounts={selected: artifact.mounts},
                )
            except MarimoStudioError:
                try:
                    current = self.discover()
                    if current is None or selected not in current.views:
                        return None
                    current_source = capture_published_presentations(
                        current,
                        (selected,),
                        profile=profile,
                    )
                    if current_source is None:
                        return None
                    with current_source as current_snapshot:
                        if revision != current_snapshot.revision(selected):
                            return None
                except OSError:
                    return None
                raise
            verified = self.discover()
            if verified is None:
                return None
            if selected not in verified.views or (
                default_selected and verified.default_view != selected
            ):
                return None
            try:
                verified_source = capture_published_presentations(
                    verified,
                    (selected,),
                    profile=profile,
                )
                if verified_source is None:
                    return None
                with verified_source as after:
                    after_revision = after.revision(selected)
            except OSError:
                return None
            if revision != after_revision:
                return None
            try:
                candidate_lease.verify_membership()
                document = candidate_lease.read_text(artifact.document)
            except ArtifactIntegrityError as error:
                candidate_lease.record_corruption(error)
                raise
            snapshot = PresentationSnapshot(
                resolved=resolved,
                view_name=selected,
                artifact=artifact,
                document=document,
                notebook_source=before.notebook_source,
                source_revision=before.source_revision,
                symbols=resolved.symbols,
                mounts=artifact.mounts,
                revision=revision,
            )
            remembered_lease = candidate_lease
            candidate_lease = None
            self._remember(snapshot, remembered_lease)
            return snapshot
        finally:
            if candidate_lease is not None:
                candidate_lease.close()

    def _coordination_lock(self, view_name: str) -> RLock:
        with self._lock:
            self._ensure_open_locked()
            return self._view_locks.setdefault(view_name, RLock())

    def _ensure_open(self) -> None:
        with self._lock:
            self._ensure_open_locked()

    def _ensure_open_locked(self) -> None:
        if self._closed:
            raise RuntimeError("Notebook presentation is closed")

    async def snapshot_async(
        self,
        view_name: str | None,
        *,
        profile: BuildProfile = "development",
    ) -> PresentationSnapshot:
        """Capture a presentation once for each accepted watcher generation."""
        development = self._development
        if development is None:
            return await asyncio.to_thread(self.snapshot, view_name, profile=profile)
        studio = await asyncio.to_thread(self.discover)
        if studio is None:
            raise ConfigurationError(
                f"No Marimo Studio configuration found for {self.notebook}"
            )
        selected = view_name or studio.default_view
        key = (selected, profile)
        for _attempt in range(_SNAPSHOT_RECONCILIATION_LIMIT):
            catalog = await development.project_catalog(studio, selected)
            with self._lock:
                cached = self._snapshots.get(key)
                cached_generation = self._snapshot_generations.get(key)
                cached_stamps = (
                    self._snapshot_notebook_stamps.get(key),
                    self._snapshot_document_stamps.get(key),
                    self._snapshot_publication_stamps.get(key),
                )
            current_stamps = await asyncio.to_thread(
                self._presentation_stamps,
                catalog.project,
                catalog.inspection,
                profile,
            )
            if cached is not None and cached_generation == catalog.generation:
                if cached_stamps == current_stamps:
                    return cached
                await development.refresh(selected)
                catalog = await development.project_catalog(studio, selected)
                current_stamps = await asyncio.to_thread(
                    self._presentation_stamps,
                    catalog.project,
                    catalog.inspection,
                    profile,
                )
                if (
                    cached_generation == catalog.generation
                    and cached_stamps == current_stamps
                ):
                    return cached
            prepared = PreparedViewProject(catalog.inspection, catalog.input_id)
            await development.publish(
                selected,
                catalog.generation,
                partial(
                    publish_presentation,
                    studio,
                    selected,
                    prepared,
                    profile=profile,
                ),
                profile=profile,
            )
            snapshot = await asyncio.to_thread(
                self._resolve_snapshot,
                selected,
                published=True,
                profile=profile,
            )
            current = await development.project_catalog(studio, selected)
            if (
                current.generation != catalog.generation
                or current.input_id != catalog.input_id
            ):
                continue
            if snapshot is None:
                build = await asyncio.to_thread(
                    read_build_state, current.project, profile
                )
                diagnostic = next(
                    (item for item in build.diagnostics if item.severity == "error"),
                    None,
                )
                if build.phase == "failed" and diagnostic is not None:
                    source = diagnostic.source
                    raise ViewProjectError(
                        diagnostic.message,
                        source=(
                            current.project.root / source.path
                            if source is not None
                            else current.project.manifest
                        ),
                        line=source.line if source is not None else None,
                        column=source.column if source is not None else None,
                        hint=diagnostic.hint or None,
                    )
                raise RuntimeSyncError(
                    "The view sources are still changing. Studio will retry shortly."
                )
            accepted_stamps = await asyncio.to_thread(
                self._presentation_stamps,
                current.project,
                current.inspection,
                profile,
            )
            with self._lock:
                self._snapshot_generations[key] = current.generation
                self._snapshot_notebook_stamps[key] = accepted_stamps[0]
                self._snapshot_document_stamps[key] = accepted_stamps[1]
                self._snapshot_publication_stamps[key] = accepted_stamps[2]
            return snapshot
        raise RuntimeSyncError(
            "The view sources kept changing during presentation capture. "
            "Studio will retry shortly."
        )

    def _notebook_stamp(self) -> tuple[int, int, int]:
        state = self.notebook.stat()
        return state.st_mtime_ns, state.st_ctime_ns, state.st_size

    @staticmethod
    def _document_stamps(
        project: ViewProject,
        inspection: ProjectInspection,
    ) -> tuple[tuple[str, int, int, int], ...]:
        stamps: list[tuple[str, int, int, int]] = []
        for document in inspection.editor_documents:
            path = project.root.joinpath(*document.path.parts)
            state = path.stat(follow_symlinks=False)
            stamps.append(
                (
                    document.path.as_posix(),
                    state.st_mtime_ns,
                    state.st_ctime_ns,
                    state.st_size,
                )
            )
        return tuple(stamps)

    def _presentation_stamps(
        self,
        project: ViewProject,
        inspection: ProjectInspection,
        profile: BuildProfile = "development",
    ) -> tuple[
        tuple[int, int, int],
        tuple[tuple[str, int, int, int], ...],
        tuple[int, int, int, int] | None,
    ]:
        try:
            return (
                self._notebook_stamp(),
                self._document_stamps(project, inspection),
                self._publication_stamp(project, profile),
            )
        except OSError as error:
            raise RuntimeSyncError(
                "The view documents changed during presentation capture. "
                "Studio will retry shortly."
            ) from error

    @staticmethod
    def _publication_stamp(
        project: ViewProject,
        profile: BuildProfile = "development",
    ) -> tuple[int, int, int, int] | None:
        try:
            state = (artifact_root(project) / f"{profile}.json").stat()
        except OSError:
            return None
        return state.st_mtime_ns, state.st_ctime_ns, state.st_size, state.st_ino

    async def display_snapshot_async(
        self,
        view_name: str,
        *,
        profile: BuildProfile = "development",
    ) -> PresentationSnapshot:
        """Resolve the last publication once for each watcher generation."""
        development = self._development
        key = (view_name, profile)
        with self._lock:
            cached = self._snapshots.get(key)
            cached_generation = self._snapshot_generations.get(key)
            cached_stamp = self._snapshot_notebook_stamps.get(key)
            cached_documents = self._snapshot_document_stamps.get(key)
            cached_publication = self._snapshot_publication_stamps.get(key)
        if development is None:
            return (
                cached
                if cached is not None
                else await asyncio.to_thread(
                    self.display_snapshot,
                    view_name,
                    profile=profile,
                )
            )
        studio = await asyncio.to_thread(self.discover)
        if studio is None:
            raise ConfigurationError(
                f"No Marimo Studio configuration found for {self.notebook}"
            )
        for _attempt in range(_SNAPSHOT_RECONCILIATION_LIMIT):
            with self._lock:
                cached = self._snapshots.get(key)
                cached_generation = self._snapshot_generations.get(key)
                cached_stamp = self._snapshot_notebook_stamps.get(key)
                cached_documents = self._snapshot_document_stamps.get(key)
                cached_publication = self._snapshot_publication_stamps.get(key)
            try:
                catalog = await development.project_catalog(studio, view_name)
            except MarimoStudioError:
                if _attempt + 1 < _SNAPSHOT_RECONCILIATION_LIMIT:
                    continue
                if cached is not None:
                    return cached
                raise
            try:
                current_stamps = await asyncio.to_thread(
                    self._presentation_stamps,
                    catalog.project,
                    catalog.inspection,
                    profile,
                )
            except RuntimeSyncError:
                if cached is not None:
                    return cached
                raise
            cached_stamps = (cached_stamp, cached_documents, cached_publication)
            if cached is not None and cached_generation == catalog.generation:
                if cached_stamps == current_stamps:
                    return cached
                await development.refresh(view_name)
                try:
                    catalog = await development.project_catalog(studio, view_name)
                    current_stamps = await asyncio.to_thread(
                        self._presentation_stamps,
                        catalog.project,
                        catalog.inspection,
                        profile,
                    )
                except MarimoStudioError:
                    if _attempt + 1 < _SNAPSHOT_RECONCILIATION_LIMIT:
                        continue
                    return cached
                if (
                    cached_generation == catalog.generation
                    and cached_stamps == current_stamps
                ):
                    return cached
            published = await asyncio.to_thread(
                self._resolve_snapshot,
                view_name,
                published=True,
                profile=profile,
            )
            if published is None:
                if cached is not None:
                    return cached
                return await self.snapshot_async(view_name, profile=profile)
            current = await development.project_catalog(studio, view_name)
            if current.generation != catalog.generation:
                continue
            try:
                accepted_stamps = await asyncio.to_thread(
                    self._presentation_stamps,
                    current.project,
                    current.inspection,
                    profile,
                )
            except RuntimeSyncError:
                if cached is not None:
                    return cached
                raise
            with self._lock:
                self._snapshot_generations[key] = current.generation
                self._snapshot_notebook_stamps[key] = accepted_stamps[0]
                self._snapshot_document_stamps[key] = accepted_stamps[1]
                self._snapshot_publication_stamps[key] = accepted_stamps[2]
            return published
        if cached is not None:
            return cached
        raise RuntimeSyncError(
            "The published view kept changing during presentation capture. "
            "Studio will retry shortly."
        )

    def latest_snapshot(
        self,
        view_name: str,
        *,
        profile: BuildProfile = "development",
    ) -> PresentationSnapshot:
        """Return the snapshot already mounted by a browser when available."""
        with self._lock:
            cached = self._snapshots.get((view_name, profile))
        return (
            cached if cached is not None else self.snapshot(view_name, profile=profile)
        )

    async def latest_snapshot_async(
        self,
        view_name: str,
        *,
        profile: BuildProfile = "development",
    ) -> PresentationSnapshot:
        """Return a mounted snapshot or capture it outside the event loop."""
        with self._lock:
            cached = self._snapshots.get((view_name, profile))
        return (
            cached
            if cached is not None
            else await self.snapshot_async(view_name, profile=profile)
        )

    def snapshot_for_revision(
        self,
        view_name: str,
        revision: str,
    ) -> PresentationSnapshot | None:
        """Return a recently published snapshot for an in-flight browser read."""
        with self._lock:
            return self._snapshot_history.get(view_name, {}).get(revision)

    def lease_artifact(
        self,
        view_name: str,
        artifact_revision: str,
    ) -> ArtifactLease | None:
        """Share a retained artifact for one in-flight browser response."""
        with self._coordination_lock(view_name):
            with self._lock:
                history = self._snapshot_history.get(view_name, {})
                leases = self._snapshot_leases.get(view_name, {})
                retained = next(
                    (
                        leases[revision]
                        for revision, snapshot in reversed(tuple(history.items()))
                        if snapshot.artifact.artifact_revision == artifact_revision
                    ),
                    None,
                )
            if retained is not None:
                return retained.share()
        return None

    def _remember(self, snapshot: PresentationSnapshot, lease: ArtifactLease) -> None:
        with self._lock:
            if self._closed:
                released = [lease]
                closed = True
            else:
                self._snapshots[(snapshot.view_name, snapshot.artifact.profile)] = (
                    snapshot
                )
                history = self._snapshot_history.setdefault(snapshot.view_name, {})
                leases = self._snapshot_leases.setdefault(snapshot.view_name, {})
                history.pop(snapshot.revision, None)
                previous_lease = leases.pop(snapshot.revision, None)
                history[snapshot.revision] = snapshot
                leases[snapshot.revision] = lease
                released = []
                closed = False
                if previous_lease is not None:
                    released.append(previous_lease)
                while len(history) > _SNAPSHOT_HISTORY_LIMIT:
                    revision = next(iter(history))
                    del history[revision]
                    released.append(leases.pop(revision))
        self._close_leases(released)
        if closed:
            raise RuntimeError("Notebook presentation is closed")

    @staticmethod
    def _close_leases(leases: Iterable[ArtifactLease]) -> None:
        failure: BaseException | None = None
        for lease in leases:
            try:
                lease.close()
            except BaseException as error:
                if failure is None:
                    failure = error
        if failure is not None:
            raise failure

    def _discard_views_locked(self, view_names: Iterable[str]) -> list[ArtifactLease]:
        released: list[ArtifactLease] = []
        for view_name in view_names:
            keys = tuple(key for key in self._snapshots if key[0] == view_name)
            for key in keys:
                self._snapshots.pop(key, None)
                self._snapshot_generations.pop(key, None)
                self._snapshot_notebook_stamps.pop(key, None)
                self._snapshot_document_stamps.pop(key, None)
                self._snapshot_publication_stamps.pop(key, None)
            self._snapshot_history.pop(view_name, None)
            released.extend(self._snapshot_leases.pop(view_name, {}).values())
        return released

    def _discard_views(self, view_names: Iterable[str]) -> None:
        with self._lock:
            released = self._discard_views_locked(view_names)
        self._close_leases(released)

    def _prune_snapshots(self, studio: StudioWorkspace) -> None:
        with self._lock:
            removed = {view for view, _profile in self._snapshots}.difference(
                studio.views
            )
            released = self._discard_views_locked(removed)
        self._close_leases(released)

    @contextmanager
    def deleting_view(self, view_name: str) -> Iterator[Callable[[], None]]:
        """Coordinate deletion and defer artifact release until owner admission."""
        with self._coordination_lock(view_name):
            self._ensure_open()
            yield partial(self._discard_views, (view_name,))

    def close(self) -> None:
        """Release every artifact retained by presentation history."""
        with self._lock:
            self._closed = True
            leases = tuple(
                lease
                for by_revision in self._snapshot_leases.values()
                for lease in by_revision.values()
            )
            self._snapshots.clear()
            self._snapshot_history.clear()
            self._snapshot_leases.clear()
            self._snapshot_generations.clear()
            self._snapshot_notebook_stamps.clear()
            self._snapshot_document_stamps.clear()
            self._snapshot_publication_stamps.clear()
            self._view_locks.clear()
        self._close_leases(leases)
