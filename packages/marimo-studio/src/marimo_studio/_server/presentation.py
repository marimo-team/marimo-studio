"""Resolve named views into browser documents and runtime configuration."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from threading import RLock

from marimo_studio._compat.server.models import ServerContext
from marimo_studio._html import runtime_document
from marimo_studio._server.runtimes import DEFAULT_RUNTIME_REGISTRY
from marimo_studio._urls import (
    SUPPORT_PATH,
    authored_view_root_url,
    public_url,
    view_url,
    with_query,
)
from marimo_studio._workspace import discover_studio
from marimo_studio._workspace.config import (
    discover_studio_definition,
    materialize_studio_workspace,
)
from marimo_studio._workspace.models import (
    ProjectionDiagnostic,
    ResolvedStudio,
    StudioDefinition,
    StudioWorkspace,
    View,
)
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


def _configuration_identity(
    studio: StudioWorkspace,
    view_name: str,
) -> tuple[object, ...]:
    view = studio.views[view_name]
    return (
        view_name,
        str(view.template),
        str(studio.config_path),
        studio.config_source,
        str(studio.notebook),
        str(studio.view_root),
        studio.default_view,
        studio.default_runtime,
        studio.runtimes,
        studio.preserve_session,
        studio.show_cell_logs,
        tuple((name, str(item.root)) for name, item in studio.views.items()),
        tuple(
            (alias, str(reference)) for alias, reference in sorted(studio.cells.items())
        ),
    )


@dataclass(frozen=True)
class _PresentationSources:
    documents: dict[str, str]
    notebook_source: str
    identity: tuple[object, ...]

    @property
    def revision(self) -> str:
        return hashlib.sha256(repr(self.identity).encode()).hexdigest()


def _read_sources(
    studio: StudioWorkspace,
    view_name: str,
) -> _PresentationSources:
    paths = tuple(
        dict.fromkeys(
            (
                studio.config_path,
                studio.notebook,
                *(view.template for view in studio.views.values()),
            )
        )
    )
    contents = {path: path.read_bytes() for path in paths}
    documents: dict[str, str] = {}
    for name, view in studio.views.items():
        try:
            documents[name] = contents[view.template].decode("utf-8")
        except UnicodeDecodeError as error:
            raise TemplateError(
                f"Could not decode {view.template} as UTF-8: {error}",
                source=view.template,
            ) from error
    try:
        notebook_source = contents[studio.notebook].decode("utf-8")
    except UnicodeDecodeError as error:
        raise ConfigurationError(
            f"Could not decode {studio.notebook} as UTF-8: {error}"
        ) from error
    identity = (
        _configuration_identity(studio, view_name),
        tuple(
            (str(path), hashlib.sha256(contents[path]).hexdigest()) for path in paths
        ),
        _view_asset_identity(studio.views[view_name]),
    )
    return _PresentationSources(
        documents=documents,
        notebook_source=notebook_source,
        identity=identity,
    )


def _view_asset_identity(view: View) -> tuple[tuple[object, ...], ...]:
    """Return stamps for assets whose browser lifecycle follows the document."""
    identity: list[tuple[object, ...]] = []
    for path in sorted(view.root.rglob("*")):
        if (
            path == view.template
            or path.suffix == ".css"
            or path.is_symlink()
            or not path.is_file()
        ):
            continue
        stat = path.stat()
        identity.append(
            (
                path.relative_to(view.root).as_posix(),
                stat.st_mtime_ns,
                stat.st_ctime_ns,
                stat.st_size,
                stat.st_ino,
            )
        )
    return tuple(identity)


@dataclass(frozen=True)
class PresentationSnapshot:
    """A view document and its bindings from one stable source revision."""

    resolved: ResolvedStudio
    view_name: str
    document: str
    notebook_source: str
    value_references: dict[str, ValueReference]
    revision: str


def _value_references(documents: dict[str, str]) -> dict[str, ValueReference]:
    references: dict[str, ValueReference] = {}
    for document in documents.values():
        parser = TemplateParser()
        try:
            parser.feed(document)
            validate_template_structure(parser, "Template")
        except (TemplateError, ValueError):
            continue
        references.update(
            (reference.source, reference) for reference in parser.value_references
        )
    return references


def _browser_diagnostic(
    diagnostic: ProjectionDiagnostic,
    *,
    notebook: Path,
    developer: bool,
) -> dict[str, object]:
    try:
        source = diagnostic.source.relative_to(notebook.parent)
    except ValueError:
        source = Path(diagnostic.source.name)
    return {
        "code": diagnostic.code,
        "severity": diagnostic.severity,
        "message": diagnostic.message,
        "hint": diagnostic.hint if developer else "",
        "view": diagnostic.view,
        "projection": diagnostic.projection,
        "target": diagnostic.target,
        "source": {
            "path": str(source),
            "line": diagnostic.line,
            "column": diagnostic.column,
        },
    }


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
                    before = _read_sources(studio, selected)
                except OSError:
                    continue
                revision = before.revision
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
                            or before.identity
                            != _read_sources(current, selected).identity
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
                    after = _read_sources(verified, selected)
                except OSError:
                    continue
                if before.identity != after.identity:
                    continue
                snapshot = PresentationSnapshot(
                    resolved=resolved,
                    view_name=selected,
                    document=before.documents[selected],
                    notebook_source=before.notebook_source,
                    value_references=_value_references(before.documents),
                    revision=revision,
                )
                self._remember(snapshot)
                return snapshot
        raise RuntimeSyncError(
            "The view sources are still changing. Studio will retry shortly."
        )

    def latest_snapshot(self, view_name: str) -> PresentationSnapshot:
        """Return the snapshot already mounted by a browser when available."""
        with self._lock:
            cached = self._snapshots.get(view_name)
        return cached if cached is not None else self.snapshot(view_name)

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

    def render_document(
        self,
        snapshot: PresentationSnapshot,
        context: ServerContext,
    ) -> str:
        view_name = snapshot.view_name
        root_url = (
            f"{authored_view_root_url(context.base_url, context.file_key)}{view_name}/"
            if context.routing_query
            else view_url(context.base_url, view_name)
        )
        support_url = with_query(
            public_url(
                context.base_url,
                f"{SUPPORT_PATH}/views/{view_name}",
            ),
            context.routing_query,
        )
        return runtime_document(
            snapshot.document,
            root_url=root_url,
            support_url=support_url,
            assets_url=public_url(
                context.base_url,
                f"{SUPPORT_PATH}/assets",
            ),
            dev=context.dev,
            revision=snapshot.revision,
            runtime=snapshot.resolved.workspace.default_runtime,
            filename=context.file_key,
        )

    def runtime_config(
        self,
        snapshot: PresentationSnapshot,
        context: ServerContext,
        runtime_id: str | None = None,
        session_id: str | None = None,
    ) -> dict[str, object]:
        resolved = snapshot.resolved
        view_name = snapshot.view_name
        view = resolved.views[view_name]
        provider, available = DEFAULT_RUNTIME_REGISTRY.select(
            resolved.workspace,
            context,
            runtime_id,
        )
        projection = provider.project(snapshot, context, session_id)
        public_root_url = with_query(
            public_url(context.base_url, "/"),
            context.routing_query,
        )
        return {
            "schema": 1,
            "revision": snapshot.revision,
            "view": view_name,
            "views": list(resolved.workspace.views),
            "runtime": {
                "id": provider.id,
                "instance": projection.instance,
                "available": list(available),
                "data": projection.data,
                **(
                    {"controls": {"cells": projection.control_cells}}
                    if projection.control_cells is not None
                    else {}
                ),
            },
            "rootUrl": public_url(context.base_url, "/"),
            "publicRootUrl": public_root_url,
            "documentRootUrl": (
                authored_view_root_url(context.base_url, context.file_key)
                if context.routing_query
                else public_root_url
            ),
            "supportUrl": with_query(
                public_url(
                    context.base_url,
                    f"{SUPPORT_PATH}/views/{view_name}",
                ),
                context.routing_query,
            ),
            "showCellLogs": resolved.workspace.show_cell_logs,
            "cellBindings": projection.cell_bindings,
            "valueBindings": projection.value_bindings,
            "diagnostics": [
                _browser_diagnostic(
                    diagnostic,
                    notebook=resolved.workspace.notebook,
                    developer=context.dev or context.mode == "edit",
                )
                for diagnostic in view.diagnostics
            ],
            "appConfig": resolved.notebook.app_config,
            "userConfig": context.user_config,
            "configOverrides": context.config_overrides,
            "dev": context.dev,
            "mode": context.mode,
        }
