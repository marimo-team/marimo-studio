"""Compose the authenticated document that mounts the Studio workspace."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from typing import cast

from htpy import Node, a, body, div, head, html, link, meta, noscript, script, title
from markupsafe import Markup

from marimo_studio._html import node_list, render
from marimo_studio._urls import (
    SUPPORT_PATH,
    editor_url,
    public_url,
    studio_url,
    with_query,
)
from marimo_studio._workspace.models import StudioWorkspace


def studio_document(
    config: StudioWorkspace,
    base_url: str,
    selected: str,
    server_token: str,
    file_key: str,
    query: Sequence[tuple[str, str]],
    routing_query: Sequence[tuple[str, str]],
    runtimes: tuple[tuple[str, str], ...],
) -> str:
    """Return the Studio mount point and its versioned bootstrap payload."""
    root_url = public_url(base_url, "/")
    support_url = public_url(base_url, SUPPORT_PATH)
    native_editor_url = editor_url(base_url, file_key, query)

    def routed(url: str) -> str:
        return with_query(url, routing_query)

    workspace_id = hashlib.sha256(str(config.notebook).encode()).hexdigest()[:16]
    bootstrap = json.dumps(
        {
            "schema": 1,
            "notebook": {"name": config.notebook.name},
            "selectedView": selected,
            "views": list(config.views),
            "runtimes": [
                {"id": runtime_id, "label": label} for runtime_id, label in runtimes
            ],
            "defaultRuntime": config.default_runtime,
            "urls": {
                "editor": native_editor_url,
                "events": routed(f"{support_url}/dev/events"),
                "query": routed(f"{support_url}/query"),
                "studioPrefix": routed(studio_url(base_url)),
                "viewPrefix": routed(root_url),
                "viewSupportPrefix": routed(f"{support_url}/views"),
                "views": routed(f"{support_url}/views"),
            },
            "workspaceId": workspace_id,
            "serverToken": server_token,
        },
        separators=(",", ":"),
    ).replace("<", "\\u003c")
    node = html(lang="en")[
        node_list(
            head[
                node_list(
                    meta(charset="utf-8"),
                    meta(
                        name="viewport",
                        content="width=device-width, initial-scale=1",
                    ),
                    title[f"{config.notebook.name} · Studio"],
                    link(rel="icon", href=public_url(base_url, "/favicon.ico")),
                    link(rel="stylesheet", href=f"{support_url}/assets/studio.css"),
                )
            ],
            body[
                node_list(
                    div(id="marimo-studio-root")[
                        node_list(
                            div(
                                {
                                    "class": "studio-opening",
                                    "role": "status",
                                    "aria-busy": "true",
                                }
                            )[
                                node_list(
                                    div["Opening Studio"],
                                    a(
                                        {
                                            "class": "studio-native-editor-link",
                                            "data-native-editor-link": True,
                                            "href": native_editor_url,
                                        }
                                    )["Open notebook editor"],
                                )
                            ]
                        )
                    ],
                    script(
                        id="marimo-studio-bootstrap",
                        type="application/json",
                    )[Markup(bootstrap)],
                    noscript[
                        node_list(
                            "Studio requires JavaScript. ",
                            a(href=native_editor_url)["Open the notebook editor"],
                            ".",
                        )
                    ],
                    script(type="module", src=f"{support_url}/assets/studio.js"),
                )
            ],
        )
    ]
    return render(cast(Node, node))
