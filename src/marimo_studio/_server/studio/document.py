"""Compose the same-origin Studio workspace document."""

from __future__ import annotations

import hashlib
from typing import cast

from htpy import Node, body, div, head, html, link, meta, script, title

from marimo_studio._html import node_list, render
from marimo_studio._server.studio.menus import toolbar
from marimo_studio._server.studio.panes import workspace
from marimo_studio._urls import SUPPORT_PATH, public_url, studio_url, view_url
from marimo_studio._workspace.models import StudioConfig


def studio_document(
    config: StudioConfig,
    base_url: str,
    selected: str,
    server_token: str,
) -> str:
    """Return the Studio shell for one active view."""
    root_url = public_url(base_url, "/")
    support_url = public_url(base_url, SUPPORT_PATH)
    preview_url = view_url(base_url, selected)
    workspace_id = hashlib.sha256(str(config.notebook).encode()).hexdigest()[:16]
    studio_root = div(
        {
            "class": "studio",
            "data-studio": True,
            "data-events-url": f"{support_url}/dev/events",
            "data-views-url": f"{support_url}/views",
            "data-view-prefix": root_url,
            "data-studio-prefix": studio_url(base_url),
            "data-support-prefix": f"{support_url}/views",
            "data-workspace-id": workspace_id,
            "data-server-token": server_token,
        }
    )[
        node_list(
            toolbar(config, selected),
            workspace(root_url, preview_url, selected),
        )
    ]
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
                    link(rel="stylesheet", href=f"{support_url}/assets/studio.css"),
                )
            ],
            body[
                node_list(
                    studio_root,
                    script(type="module", src=f"{support_url}/assets/studio.js"),
                )
            ],
        )
    ]
    return render(cast(Node, node))
