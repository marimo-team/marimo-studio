"""Small HTML fragments injected into presentation documents."""

from __future__ import annotations

import json
from html import escape
from html.parser import HTMLParser
from typing import cast

from htpy import Element, Node, Renderable, base, div, fragment, link, script
from markupsafe import Markup

from marimo_studio._projections import STUDIO_REGION_SELECTOR
from marimo_studio.errors import ViewProjectError
from marimo_studio.view_providers._document import (
    HTMLDocumentParser,
    validate_html_document,
)

_MARIMO_FILENAME = Element("marimo-filename")
_STYLE_LOADING_SCRIPT = """\
(() => {
  const root = document.documentElement;
  root.dataset.marimoStudioStyles = "loading";
  const reveal = () => {
    if (root.dataset.marimoStudioStyles !== "loading") return;
    root.dataset.marimoStudioStyles = "error";
    const show = () => {
      if (document.querySelector("[data-marimo-studio-style-error]")) return;
      const status = document.createElement("div");
      status.dataset.marimoStudioRuntimeDiagnostic = "";
      status.dataset.marimoStudioStyleError = "";
      status.dataset.state = "error";
      status.setAttribute("role", "alert");
      status.textContent =
        "View styling could not start. The authored view remains available.";
      document.body.append(status);
    };
    if (document.body) show();
    else window.addEventListener("DOMContentLoaded", show, { once: true });
  };
  window.__MARIMO_STUDIO_STYLE_TIMEOUT__ = window.setTimeout(reveal, 3000);
})();
"""


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
    runtime_explicit: bool,
    replay: bool,
    renewal_token: str | None,
    marimo_version: str,
    session_id: str | None = None,
    client_id: str | None = None,
    lifecycle_id: int | None = None,
    runtime_session_id: str | None = None,
    runtime_entry: str = "runtime.js",
    runtime_styles: tuple[str, ...] = ("runtime.css",),
) -> Renderable:
    mount_config = json.dumps(
        {
            "supportUrl": support_url,
            "version": marimo_version,
            "revision": revision,
            "runtime": runtime,
            "runtimeExplicit": runtime_explicit,
            "replay": replay,
            **({"renewalToken": renewal_token} if renewal_token is not None else {}),
            **({"sessionId": session_id} if session_id is not None else {}),
            **({"clientId": client_id} if client_id is not None else {}),
            **({"lifecycleId": lifecycle_id} if lifecycle_id is not None else {}),
            **(
                {"runtimeSessionId": runtime_session_id}
                if runtime_session_id is not None
                else {}
            ),
        },
        separators=(",", ":"),
    ).replace("<", "\\u003c")
    return fragment[
        node_list(
            *(
                link(
                    {
                        "data-marimo-studio-runtime": True,
                        "rel": "stylesheet",
                        "crossorigin": "anonymous",
                        "href": f"{assets_url}/{stylesheet}",
                    }
                )
                for stylesheet in runtime_styles
            ),
            script({"data-marimo-studio-runtime": True})[
                Markup(
                    _STYLE_LOADING_SCRIPT
                    + "Object.defineProperty(window,'__MARIMO_MOUNT_CONFIG__',{"
                    + f"value:Object.freeze({mount_config}),"
                    + "writable:false,configurable:false,enumerable:true});"
                )
            ],
            script(
                {
                    "data-marimo-studio-runtime": True,
                    "type": "module",
                    "src": f"{assets_url}/{runtime_entry}",
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


class _DocumentLayout(HTMLParser):
    def __init__(self, source: str) -> None:
        super().__init__(convert_charrefs=False)
        self._line_starts = [0]
        for line in source.splitlines(keepends=True):
            self._line_starts.append(self._line_starts[-1] + len(line))
        self.head_open_end: int | None = None
        self.head_close: int | None = None
        self.body_close: int | None = None
        self.lens_scope_insert: int | None = None

    def _offset(self) -> int:
        line, column = self.getpos()
        return self._line_starts[line - 1] + column

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        attributes = dict(attrs)
        if (
            attributes.get("id") == "app-shell"
            and "data-marimo-lens-scope" not in attributes
        ):
            source = self.get_starttag_text()
            if source is not None:
                self.lens_scope_insert = self._offset() + len(source) - 1
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
    runtime_explicit: bool,
    replay: bool,
    renewal_token: str | None,
    filename: str,
    marimo_version: str,
    session_id: str | None = None,
    client_id: str | None = None,
    lifecycle_id: int | None = None,
    runtime_session_id: str | None = None,
    runtime_entry: str = "runtime.js",
    runtime_styles: tuple[str, ...] = ("runtime.css",),
) -> str:
    """Inject one presentation runtime into an authored view document."""
    parser = HTMLDocumentParser()
    parser.feed(document)
    validate_html_document(parser, "HTML document")

    layout = _DocumentLayout(document)
    layout.feed(document)
    if (
        layout.head_open_end is None
        or layout.head_close is None
        or layout.body_close is None
    ):
        raise ViewProjectError(
            "HTML document must contain <head>, </head>, and </body>"
        )

    head_content = (
        f"\n{base(href=root_url)}\n"
        + render(
            runtime_head(
                support_url=support_url,
                assets_url=assets_url,
                dev=dev,
                revision=revision,
                runtime=runtime,
                runtime_explicit=runtime_explicit,
                replay=replay,
                renewal_token=renewal_token,
                marimo_version=marimo_version,
                session_id=session_id,
                client_id=client_id,
                lifecycle_id=lifecycle_id,
                runtime_session_id=runtime_session_id,
                runtime_entry=runtime_entry,
                runtime_styles=runtime_styles,
            )
        )
        + "\n"
    )
    body_content = (
        "\n" + render(runtime_root()) + "\n" + render(runtime_metadata(filename)) + "\n"
    )
    insertions = [
        (layout.head_open_end, head_content),
        (layout.body_close, body_content),
    ]
    if layout.lens_scope_insert is not None:
        insertions.append(
            (
                layout.lens_scope_insert,
                f' data-marimo-lens-scope="{escape(STUDIO_REGION_SELECTOR)}"',
            )
        )
    for offset, content in sorted(insertions, reverse=True):
        document = document[:offset] + content + document[offset:]
    return document
