"""Resolve named views into browser documents and runtime configuration."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from threading import RLock

from marimo_studio._workspace import discover_studio
from marimo_studio._workspace.config import (
    discover_studio_definition,
    materialize_studio_workspace,
)
from marimo_studio._workspace.models import (
    ResolvedStudio,
    StudioDefinition,
    StudioWorkspace,
)
from marimo_studio._workspace.revisions import capture_studio_sources
from marimo_studio._workspace.templates import (
    TemplateParser,
    validate_template_structure,
)
from marimo_studio.errors import (
    ConfigurationError,
    MarimoStudioError,
    RuntimeSyncError,
    TemplateError,
)
from marimo_studio.types import ValueReference
from marimo_studio.workspace import resolve_studio

_SNAPSHOT_HISTORY_LIMIT = 8


@dataclass(frozen=True)
class PresentationSnapshot:
    """A view document and its bindings from one stable source revision."""

    resolved: ResolvedStudio
    view_name: str
    document: str
    notebook_source: str
    value_references: dict[str, ValueReference]
    output_references: dict[str, ValueReference]
    revision: str


def _projection_references(
    documents: dict[str, str],
) -> tuple[dict[str, ValueReference], dict[str, ValueReference]]:
    values: dict[str, ValueReference] = {}
    outputs: dict[str, ValueReference] = {}
    for document in documents.values():
        parser = TemplateParser()
        try:
            parser.feed(document)
            validate_template_structure(parser, "Template")
        except (TemplateError, ValueError):
            continue
        values.update(
            (reference.source, reference) for reference in parser.value_references
        )
        outputs.update(
            (reference.source, reference) for reference in parser.output_references
        )
    return values, outputs


class NotebookPresentation:
    """Cache notebook inspection while configuration inputs stay unchanged."""

    def __init__(
        self,
        notebook: Path,
    ) -> None:
        self.notebook = notebook
        self._lock = RLock()
        self._snapshots: dict[str, PresentationSnapshot] = {}
        self._snapshot_history: dict[str, dict[str, PresentationSnapshot]] = {}

    def discover(self) -> StudioWorkspace | None:
        return discover_studio(self.notebook)

    def discover_definition(self) -> StudioDefinition | None:
        """Return configuration before workspace materialization."""
        return discover_studio_definition(self.notebook)

    def materialize(self, definition: StudioDefinition) -> StudioWorkspace:
        """Resolve the current authored views for a definition."""
        return materialize_studio_workspace(definition)

    def snapshot(
        self,
        view_name: str | None,
    ) -> PresentationSnapshot:
        with self._lock:
            for _attempt in range(3):
                studio = self.discover()
                if studio is None:
                    raise ConfigurationError(
                        f"No Marimo Studio configuration found for {self.notebook}"
                    )
                self._prune_snapshots(studio)
                selected = view_name or studio.default_view
                if selected not in studio.views:
                    raise ConfigurationError(f"Unknown view {selected!r}")
                try:
                    before = capture_studio_sources(studio, (selected,))
                except OSError:
                    continue
                revision = before.revision(selected)
                cached = self._snapshots.get(selected)
                if cached is not None and cached.revision == revision:
                    return cached
                try:
                    resolved = resolve_studio(
                        studio,
                        view_name=selected,
                        view_documents={selected: before.documents[selected]},
                    )
                except MarimoStudioError:
                    try:
                        current = self.discover()
                        if (
                            current is None
                            or selected not in current.views
                            or revision
                            != capture_studio_sources(current, (selected,)).revision(
                                selected
                            )
                        ):
                            continue
                    except OSError:
                        continue
                    raise
                verified = self.discover()
                if verified is None:
                    continue
                verified_selected = view_name or verified.default_view
                if verified_selected != selected or selected not in verified.views:
                    continue
                try:
                    after = capture_studio_sources(verified, (selected,))
                except OSError:
                    continue
                if revision != after.revision(selected):
                    continue
                value_references, output_references = _projection_references(
                    {selected: before.documents[selected]}
                )
                snapshot = PresentationSnapshot(
                    resolved=resolved,
                    view_name=selected,
                    document=before.documents[selected],
                    notebook_source=before.notebook_source,
                    value_references=value_references,
                    output_references=output_references,
                    revision=revision,
                )
                self._remember(snapshot)
                return snapshot
        raise RuntimeSyncError(
            "The view sources are still changing. Studio will retry shortly."
        )

    async def snapshot_async(
        self,
        view_name: str | None,
    ) -> PresentationSnapshot:
        """Capture a presentation without blocking the server event loop."""
        return await asyncio.to_thread(self.snapshot, view_name)

    def latest_snapshot(self, view_name: str) -> PresentationSnapshot:
        """Return the snapshot already mounted by a browser when available."""
        with self._lock:
            cached = self._snapshots.get(view_name)
        return cached if cached is not None else self.snapshot(view_name)

    async def latest_snapshot_async(
        self,
        view_name: str,
    ) -> PresentationSnapshot:
        """Return a mounted snapshot or capture it outside the event loop."""
        with self._lock:
            cached = self._snapshots.get(view_name)
        return cached if cached is not None else await self.snapshot_async(view_name)

    def snapshot_for_revision(
        self,
        view_name: str,
        revision: str,
    ) -> PresentationSnapshot | None:
        """Return a recently published snapshot for an in-flight browser read."""
        with self._lock:
            return self._snapshot_history.get(view_name, {}).get(revision)

    def _remember(self, snapshot: PresentationSnapshot) -> None:
        self._snapshots[snapshot.view_name] = snapshot
        history = self._snapshot_history.setdefault(snapshot.view_name, {})
        history[snapshot.revision] = snapshot
        while len(history) > _SNAPSHOT_HISTORY_LIMIT:
            del history[next(iter(history))]

    def _prune_snapshots(self, studio: StudioWorkspace) -> None:
        removed = set(self._snapshots).difference(studio.views)
        for view_name in removed:
            self._snapshots.pop(view_name, None)
            self._snapshot_history.pop(view_name, None)
