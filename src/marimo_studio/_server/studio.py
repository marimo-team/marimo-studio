"""Render the same-origin editor and named view workspace."""

from __future__ import annotations

import json
from typing import cast

from htpy import (
    Element,
    Node,
    a,
    body,
    button,
    div,
    h1,
    head,
    header,
    html,
    link,
    main,
    meta,
    option,
    p,
    script,
    select,
    span,
    style,
    title,
)
from markupsafe import Markup

from marimo_studio._html import node_list, render
from marimo_studio._server.routes import (
    SUPPORT_PATH,
    public_url,
    studio_url,
    view_url,
)
from marimo_studio._workspace.models import StudioConfig

_IFRAME = Element("iframe")


def repair_document(message: str, hint: str, events_url: str) -> str:
    """Return a development page that reloads when its source is repaired."""
    events = json.dumps(events_url).replace("<", "\\u003c")
    node = html(
        lang="en",
        data_marimo_studio_preview_state="error",
    )[
        node_list(
            head[
                node_list(
                    meta(charset="utf-8"),
                    meta(
                        name="viewport",
                        content="width=device-width, initial-scale=1",
                    ),
                    title["View needs repair"],
                    style[
                        Markup(
                            """
                            :root {
                              color-scheme: light dark;
                              font-family: ui-sans-serif, system-ui, sans-serif;
                            }
                            body { margin: 0; color: CanvasText; background: Canvas; }
                            main {
                              max-width: 42rem;
                              margin: 12vh auto;
                              padding: 1.25rem;
                            }
                            h1 { font-size: 1rem; margin: 0 0 .5rem; }
                            p { color: GrayText; line-height: 1.5; margin: .35rem 0; }
                            """
                        )
                    ],
                )
            ],
            body[
                node_list(
                    main(
                        {
                            "role": "status",
                            "data-marimo-studio-repair": True,
                            "data-marimo-studio-message": message,
                            "data-marimo-studio-hint": hint,
                        }
                    )[
                        node_list(
                            h1["View needs repair"],
                            p[message],
                            hint and p[hint],
                        )
                    ],
                    script[
                        Markup(
                            "const events=new EventSource("
                            f"{events});"
                            "events.addEventListener('change',()=>location.reload());"
                            "addEventListener('pagehide',()=>events.close(),{once:true});"
                            "setTimeout(()=>location.reload(),3000);"
                        )
                    ],
                )
            ],
        )
    ]
    return render(cast(Node, node))


def studio_document(config: StudioConfig, base_url: str, selected: str) -> str:
    """Return the Studio shell for one active view."""
    root_url = public_url(base_url, "/")
    support_url = public_url(base_url, SUPPORT_PATH)
    preview_url = view_url(base_url, selected)
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
            "data-view-prefix": root_url,
            "data-studio-prefix": studio_url(base_url),
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
