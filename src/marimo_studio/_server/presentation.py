"""Resolve named views into browser documents and runtime configuration."""

from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path
from threading import RLock

from htpy import base

from marimo_studio._compat.server import ServerContext, live_cell_ids
from marimo_studio._html import render, runtime_head, runtime_metadata, runtime_root
from marimo_studio._server.routes import SUPPORT_PATH, public_url
from marimo_studio._workspace import discover_studio, resolve_studio
from marimo_studio._workspace.config import (
    TemplateParser,
    validate_template_structure,
)
from marimo_studio._workspace.models import ResolvedStudio, StudioConfig
from marimo_studio.errors import ConfigurationError


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
        raise ConfigurationError("Template must contain <head>, </head>, and </body>")
    return (
        document[: layout.head_open_end]
        + head_content
        + document[layout.head_open_end : layout.head_close]
        + document[layout.head_close : layout.body_close]
        + body_content
        + document[layout.body_close :]
    )


def _stamp(path: Path) -> tuple[int, int]:
    try:
        stat = path.stat()
    except OSError:
        return (-1, -1)
    return stat.st_mtime_ns, stat.st_size


def _source_stamp(
    studio: StudioConfig,
    view_name: str,
) -> tuple[object, ...]:
    view = studio.views[view_name]
    return (
        _stamp(studio.config_path),
        _stamp(studio.notebook),
        tuple(studio.views),
        _stamp(view.template),
    )


class NotebookPresentation:
    """Cache notebook inspection while configuration inputs stay unchanged."""

    def __init__(self, notebook: Path) -> None:
        self.notebook = notebook
        self._lock = RLock()
        self._resolved: dict[str, ResolvedStudio] = {}
        self._source_stamps: dict[str, tuple[object, ...]] = {}

    def discover(self) -> StudioConfig | None:
        return discover_studio(self.notebook)

    def resolve(
        self,
        studio: StudioConfig,
        view_name: str,
    ) -> ResolvedStudio:
        with self._lock:
            stamp = _source_stamp(studio, view_name)
            if view_name not in self._resolved or stamp != self._source_stamps.get(
                view_name
            ):
                self._resolved[view_name] = resolve_studio(
                    studio,
                    view_name=view_name,
                )
                self._source_stamps[view_name] = stamp
            return self._resolved[view_name]

    def render_document(
        self,
        resolved: ResolvedStudio,
        context: ServerContext,
        view_name: str,
    ) -> str:
        view = resolved.views[view_name].view
        document = view.template.read_text(encoding="utf-8")
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
                )
            )
            + "\n"
        )
        runtime = (
            render(runtime_root()) + "\n" + render(runtime_metadata(context.file_key))
        )
        return _inject_runtime(document, head_content, f"\n{runtime}\n")

    def runtime_config(
        self,
        resolved: ResolvedStudio,
        context: ServerContext,
        view_name: str,
        session_id: str | None = None,
    ) -> dict[str, object]:
        cell_ids = live_cell_ids(context, session_id)
        return {
            "schema": 2,
            "view": view_name,
            "views": list(resolved.studio.views),
            "fileKey": context.file_key,
            "runtimeUrl": public_url(context.base_url, "/"),
            "supportUrl": public_url(
                context.base_url,
                f"{SUPPORT_PATH}/views/{view_name}",
            ),
            "cellBindings": resolved.runtime_cell_bindings(cell_ids),
            "valueBindings": resolved.views[view_name].runtime_value_bindings(cell_ids),
            "appConfig": resolved.notebook.app_config,
            "userConfig": context.user_config,
            "configOverrides": context.config_overrides,
            "serverToken": context.server_token,
            "dev": context.dev,
            "mode": context.mode,
            "preserveSession": resolved.studio.preserve_session,
        }
