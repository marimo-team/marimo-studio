"""Render the same-origin editor and named view workspace."""

from __future__ import annotations

from typing import cast

from htpy import (
    Element,
    Node,
    a,
    body,
    button,
    div,
    head,
    header,
    html,
    link,
    main,
    meta,
    option,
    script,
    select,
    span,
    title,
)

from marimo_studio._html import node_list, render
from marimo_studio._server.presentation import SUPPORT_PATH, public_url
from marimo_studio._workspace.models import StudioConfig

_IFRAME = Element("iframe")


def studio_document(config: StudioConfig, base_url: str, selected: str) -> str:
    """Return the Studio shell for one active view."""
    root_url = public_url(base_url, "/")
    support_url = public_url(base_url, SUPPORT_PATH)
    preview_url = f"{support_url}/preview/{selected}/?kiosk=true"
    view_selector = select(
        {
            "aria-label": "Custom view",
            "data-view-select": True,
        }
    )[
        node_list(
            *[
                option(
                    value=name,
                    selected=name == selected,
                )[name]
                for name in config.views
            ]
        )
    ]
    layout = div(
        {
            "class": "studio-layout",
            "role": "group",
            "aria-label": "Workspace layout",
        }
    )[
        node_list(
            button(
                type="button",
                data_layout="editor",
            )["Editor"],
            button(
                type="button",
                data_layout="split",
                aria_pressed="true",
            )["Split"],
            button(
                type="button",
                data_layout="preview",
            )["Preview"],
        )
    ]
    controls = div(class_="studio-controls")[
        node_list(
            view_selector,
            layout,
            a(
                {
                    "class": "studio-popout",
                    "data-preview-popout": True,
                    "href": preview_url,
                    "target": "_blank",
                    "rel": "noopener",
                }
            )["Open preview"],
            span(
                {
                    "class": "studio-status",
                    "data-studio-status": True,
                    "role": "status",
                    "hidden": True,
                }
            ),
        )
    ]
    toolbar = header(class_="studio-toolbar")[
        node_list(
            div(class_="studio-title")[
                node_list(
                    span(class_="studio-wordmark")["marimo"],
                    span(class_="studio-notebook")[config.notebook.name],
                )
            ],
            controls,
        )
    ]
    editor_pane = div(class_="studio-pane studio-pane-editor")[
        node_list(
            _IFRAME(
                {
                    "data-editor-frame": True,
                    "src": root_url,
                    "title": "Marimo editor",
                    "allow": "clipboard-read; clipboard-write",
                }
            )
        )
    ]
    divider = div(
        {
            "class": "studio-divider",
            "data-divider": True,
            "role": "separator",
            "aria-label": "Resize editor and preview",
            "aria-orientation": "vertical",
            "aria-valuemin": "20",
            "aria-valuemax": "80",
            "aria-valuenow": "50",
            "tabindex": "0",
        }
    )
    preview_pane = div(class_="studio-pane studio-pane-preview")[
        node_list(
            _IFRAME(
                {
                    "data-preview-frame": True,
                    "src": "about:blank",
                    "title": f"{selected} custom view",
                    "allow": "clipboard-read; clipboard-write",
                }
            )
        )
    ]
    workspace = main(class_="studio-workspace", data_layout_state="split")[
        node_list(editor_pane, divider, preview_pane)
    ]
    studio_root = div(
        {
            "class": "studio",
            "data-studio": True,
            "data-events-url": f"{support_url}/dev/events",
            "data-views-url": f"{support_url}/views",
            "data-preview-prefix": f"{support_url}/preview",
            "data-support-prefix": f"{support_url}/views",
        }
    )[node_list(toolbar, workspace)]
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
                    link(
                        rel="stylesheet",
                        href=f"{support_url}/assets/studio.css",
                    ),
                )
            ],
            body[
                node_list(
                    studio_root,
                    script(
                        type="module",
                        src=f"{support_url}/assets/studio.js",
                    ),
                )
            ],
        )
    ]
    return render(cast(Node, node))
