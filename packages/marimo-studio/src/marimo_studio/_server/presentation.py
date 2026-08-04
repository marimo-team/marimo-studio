"""Resolve named views into browser documents and runtime configuration."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from threading import RLock

from htpy import base

from marimo_studio._compat.server.models import ServerContext
from marimo_studio._html import render, runtime_head, runtime_metadata, runtime_root
from marimo_studio._server.runtimes import DEFAULT_RUNTIME_REGISTRY
from marimo_studio._urls import SUPPORT_PATH, public_url
from marimo_studio._workspace import discover_studio
from marimo_studio._workspace.models import (
    ProjectionDiagnostic,
    ResolvedStudio,
    StudioConfig,
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


class _DocumentLayout(HTMLParser):
    def __init__(self, source: str) -> None:
        super().__init__(convert_charrefs=False)
        self._line_starts = [0]
        for line in source.splitlines(keepends=True):
            self._line_starts.append(self._line_starts[-1] + len(line))
        self.head_open_end: int | None = None
        self.head_close: int | None = None
        self.body_close: int | None = None

    def _offset(self) -> int:
        line, column = self.getpos()
        return self._line_starts[line - 1] + column

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        del attrs
        if tag == "head" and self.head_open_end is None:
            source = self.get_starttag_text()
            if source is not None:
                self.head_open_end = self._offset() + len(source)

    def handle_endtag(self, tag: str) -> None:
        if tag == "head":
            self.head_close = self._offset()
        elif tag == "body":
            self.body_close = self._offset()


def _inject_runtime(document: str, head_content: str, body_content: str) -> str:
    parser = TemplateParser()
    parser.feed(document)
    validate_template_structure(parser, "Template")
    layout = _DocumentLayout(document)
    layout.feed(document)
    if (
        layout.head_open_end is None
        or layout.head_close is None
        or layout.body_close is None
    ):
        raise TemplateError("Template must contain <head>, </head>, and </body>")
    return (
        document[: layout.head_open_end]
        + head_content
        + document[layout.head_open_end : layout.head_close]
        + document[layout.head_close : layout.body_close]
        + body_content
        + document[layout.body_close :]
    )


def _configuration_identity(
    studio: StudioConfig,
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
    studio: StudioConfig,
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
    )
    return _PresentationSources(
        documents=documents,
        notebook_source=notebook_source,
        identity=identity,
    )


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

    def discover(self) -> StudioConfig | None:
        return discover_studio(self.notebook)

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
                self._snapshots[selected] = snapshot
                return snapshot
        raise RuntimeSyncError(
            "The view sources are still changing. Studio will retry shortly."
        )

    def render_document(
        self,
        snapshot: PresentationSnapshot,
        context: ServerContext,
    ) -> str:
        view_name = snapshot.view_name
        root_url = public_url(context.base_url, "/")
        support_url = public_url(
            context.base_url,
            f"{SUPPORT_PATH}/views/{view_name}",
        )
        head_content = (
            f"\n{base(href=root_url)}\n"
            + render(
                runtime_head(
                    support_url=support_url,
                    assets_url=public_url(
                        context.base_url,
                        f"{SUPPORT_PATH}/assets",
                    ),
                    dev=context.dev,
                    revision=snapshot.revision,
                    runtime=snapshot.resolved.studio.default_runtime,
                )
            )
            + "\n"
        )
        runtime = (
            render(runtime_root()) + "\n" + render(runtime_metadata(context.file_key))
        )
        return _inject_runtime(snapshot.document, head_content, f"\n{runtime}\n")

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
            resolved.studio,
            context,
            runtime_id,
        )
        projection = provider.project(snapshot, context, session_id)
        return {
            "schema": 1,
            "revision": snapshot.revision,
            "view": view_name,
            "views": list(resolved.studio.views),
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
            "supportUrl": public_url(
                context.base_url,
                f"{SUPPORT_PATH}/views/{view_name}",
            ),
            "cellBindings": projection.cell_bindings,
            "valueBindings": projection.value_bindings,
            "diagnostics": [
                _browser_diagnostic(
                    diagnostic,
                    notebook=resolved.studio.notebook,
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
