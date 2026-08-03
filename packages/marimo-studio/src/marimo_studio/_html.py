"""Small HTML fragments injected into presentation documents."""

from __future__ import annotations

import json
from typing import cast

from htpy import Element, Node, Renderable, div, fragment, link, script
from markupsafe import Markup

from marimo_studio._assets import runtime_marimo_version

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
) -> Renderable:
    mount_config = json.dumps(
        {
            "supportUrl": support_url,
            "version": runtime_marimo_version(),
            "revision": revision,
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
