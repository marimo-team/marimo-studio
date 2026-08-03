"""Render the development response for an invalid view document."""

from __future__ import annotations

import json
from typing import cast

from htpy import Node, body, h1, head, html, main, meta, p, script, style, title
from markupsafe import Markup

from marimo_studio._html import node_list, render


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
