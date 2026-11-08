"""Render the development response for an invalid view document."""

from __future__ import annotations

import json
from typing import cast

from htpy import Node, body, h1, head, html, link, main, meta, p, script, style, title
from markupsafe import Markup

from marimo_studio._delivery.html import node_list, render


def _script_json(value: object) -> str:
    return json.dumps(value, separators=(",", ":")).replace("<", "\\u003c")


def _standalone_report(runtime: str) -> str:
    # A wrapper mirrors the report of the document in its frame. Each render
    # mints a lifecycle, so a repair page that reloads replaces its last report.
    report = _script_json({"type": "marimo-studio:view-state", "runtime": runtime})
    return (
        "if(parent!==window)parent.postMessage({"
        f"...{report},state:'error',diagnostics:[diagnostic],"
        "lifecycleId:1+Math.floor(Math.random()*(Number.MAX_SAFE_INTEGER-1))"
        "},'*');"
    )


def repair_document(
    message: str,
    hint: str,
    events_url: str,
    *,
    icon_url: str,
    code: str = "configuration-error",
    lifecycle_id: int | None = None,
    runtime: str = "server",
    view: str = "",
    recoverable: bool = True,
) -> str:
    """Show a view error, following source repairs when recovery is possible."""
    heading = "View needs repair" if recoverable else "Preview unavailable"
    events = json.dumps(events_url).replace("<", "\\u003c")
    diagnostic = {
        "scope": "runtime",
        "code": code,
        "severity": "error",
        "message": message,
        "hint": hint,
        "view": view,
    }
    node = html(
        lang="en",
        data_marimo_studio_preview_state="error",
        data_marimo_studio_state="error",
    )[
        node_list(
            head[
                node_list(
                    meta(charset="utf-8"),
                    meta(
                        name="viewport",
                        content="width=device-width, initial-scale=1",
                    ),
                    title[heading],
                    link(rel="icon", href=icon_url),
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
                            "role": "status" if recoverable else "alert",
                            "data-marimo-studio-repair": True,
                            "data-marimo-studio-message": message,
                            "data-marimo-studio-hint": hint,
                        }
                    )[
                        node_list(
                            h1[heading],
                            p[message],
                            hint and p[hint],
                        )
                    ],
                    script[
                        Markup(
                            f"const diagnostic={_script_json(diagnostic)};"
                            "globalThis.marimoStudio={"
                            "diagnostics:()=>[{...diagnostic}]};"
                            + (
                                "parent.postMessage("
                                + _script_json(
                                    {
                                        "type": "marimo-studio:view-error",
                                        "runtime": runtime,
                                        "lifecycleId": lifecycle_id,
                                        "view": view,
                                        "diagnostic": diagnostic,
                                    }
                                )
                                + ", '*');"
                                if lifecycle_id is not None and view
                                else _standalone_report(runtime)
                            )
                            + (
                                f"const url=new URL({events},location.href);"
                                "url.protocol=url.protocol==='https:'?'wss:':'ws:';"
                                "const events=new WebSocket(url);"
                                "events.addEventListener('message',(message)=>{"
                                "if(JSON.parse(message.data).event==='change')"
                                "location.reload();});"
                                "addEventListener('pagehide',()=>events.close(),{once:true});"
                                "setTimeout(()=>location.reload(),3000);"
                                if recoverable
                                else ""
                            )
                        )
                    ],
                )
            ],
        )
    ]
    return render(cast(Node, node))
