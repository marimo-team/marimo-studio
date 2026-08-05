"""Small HTML fragments injected into presentation documents."""

from __future__ import annotations

import json
from html.parser import HTMLParser
from typing import cast

from htpy import Element, Node, Renderable, base, div, fragment, link, script
from markupsafe import Markup

from marimo_studio._assets import runtime_marimo_version
from marimo_studio._workspace.templates import (
    TemplateParser,
    validate_template_structure,
)
from marimo_studio.errors import TemplateError

_MARIMO_CELL = Element("marimo-cell")
_MARIMO_FILENAME = Element("marimo-filename")


def node_list(*nodes: object) -> list[Node]:
    return cast(list[Node], list(nodes))


def render(node: Node) -> str:
    rendered = str(fragment[node])
    # MarkupSafe keeps its subclass through str(), which can escape the
    # surrounding document when fragments are inserted through concatenation.
    return str.__new__(str, rendered)


def runtime_head(
    *,
    support_url: str,
    assets_url: str,
    dev: bool,
    revision: str,
    runtime: str,
) -> Renderable:
    mount_config = json.dumps(
        {
            "supportUrl": support_url,
            "version": runtime_marimo_version(),
            "revision": revision,
            "runtime": runtime,
        },
        separators=(",", ":"),
    ).replace("<", "\\u003c")
    return fragment[
        node_list(
            link(
                {
                    "data-marimo-studio-runtime": True,
                    "rel": "stylesheet",
                    "href": f"{assets_url}/runtime.css",
                }
            ),
            script({"data-marimo-studio-runtime": True})[
                Markup(f"window.__MARIMO_MOUNT_CONFIG__=Object.freeze({mount_config});")
            ],
            script(
                {
                    "data-marimo-studio-runtime": True,
                    "type": "module",
                    "src": f"{assets_url}/runtime.js",
                }
            ),
            dev
            and script(
                {
                    "data-marimo-studio-dev": True,
                    "type": "module",
                    "src": f"{assets_url}/dev-reload.js",
                }
            ),
        )
    ]


def runtime_root() -> Renderable:
    return div(id="marimo-runtime-root", hidden=True, hx_preserve=True)


def runtime_metadata(filename: str) -> Renderable:
    return _MARIMO_FILENAME(hidden=True)[filename]


def cell_host(alias: str) -> Renderable:
    return _MARIMO_CELL(name=alias)


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


def runtime_document(
    document: str,
    *,
    root_url: str,
    support_url: str,
    assets_url: str,
    dev: bool,
    revision: str,
    runtime: str,
    filename: str,
) -> str:
    """Inject one presentation runtime into an authored view document."""
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

    head_content = (
        f"\n{base(href=root_url)}\n"
        + render(
            runtime_head(
                support_url=support_url,
                assets_url=assets_url,
                dev=dev,
                revision=revision,
                runtime=runtime,
            )
        )
        + "\n"
    )
    body_content = (
        "\n" + render(runtime_root()) + "\n" + render(runtime_metadata(filename)) + "\n"
    )
    return (
        document[: layout.head_open_end]
        + head_content
        + document[layout.head_open_end : layout.head_close]
        + document[layout.head_close : layout.body_close]
        + body_content
        + document[layout.body_close :]
    )
