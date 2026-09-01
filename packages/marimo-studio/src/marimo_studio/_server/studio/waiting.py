"""Render the transient preview shown while the editor session starts."""

from __future__ import annotations

import json
from typing import cast

from htpy import Node, body, head, html, main, meta, p, script, span, style, title
from markupsafe import Markup

from marimo_studio._delivery.html import node_list, render


def waiting_document(
    *,
    refresh_url: str,
    lifecycle_id: int | None = None,
    runtime: str = "server",
    view: str = "",
) -> str:
    """Return a stable loading surface that polls for the notebook session."""
    refresh = json.dumps(refresh_url).replace("<", "\\u003c")
    receiver = (
        {
            "runtime": runtime,
            "lifecycleId": lifecycle_id,
            "view": view,
        }
        if lifecycle_id is not None and view
        else None
    )

    def signal(message_type: str) -> str:
        if receiver is None:
            return ""
        payload = json.dumps(
            {"type": message_type, **receiver},
            separators=(",", ":"),
        ).replace("<", "\\u003c")
        return f"parent.postMessage({payload}, '*');"

    node = html(
        lang="en",
        data_marimo_studio_preview_state="waiting",
    )[
        node_list(
            head[
                node_list(
                    meta(charset="utf-8"),
                    meta(
                        name="viewport",
                        content="width=device-width, initial-scale=1",
                    ),
                    title["Starting notebook"],
                    style[
                        Markup(
                            """
                            :root {
                              color-scheme: light dark;
                              font-family: "PT Sans", ui-sans-serif, system-ui,
                                sans-serif;
                              --background: #fff;
                              --foreground-muted: #64748b;
                              --border: #e2e8f0;
                              --primary: #0880ea;
                            }
                            @media (prefers-color-scheme: dark) {
                              :root {
                                --background: #181c1a;
                                --foreground-muted: #aab2af;
                                --border: #3b403e;
                                --primary: #28879f;
                              }
                            }
                            * { box-sizing: border-box; }
                            body {
                              min-height: 100vh;
                              margin: 0;
                              display: grid;
                              place-items: center;
                              background: var(--background);
                            }
                            main {
                              display: flex;
                              align-items: center;
                              gap: .625rem;
                              color: var(--foreground-muted);
                              font-size: .875rem;
                              line-height: 1.25rem;
                              opacity: 0;
                              animation: reveal 120ms ease-out 500ms forwards;
                            }
                            p { margin: 0; }
                            .spinner {
                              width: 1rem;
                              height: 1rem;
                              border: 1.5px solid var(--border);
                              border-top-color: var(--primary);
                              border-radius: 9999px;
                              animation: spin 800ms linear infinite;
                            }
                            @keyframes reveal { to { opacity: 1; } }
                            @keyframes spin { to { transform: rotate(360deg); } }
                            @media (prefers-reduced-motion: reduce) {
                              main { opacity: 1; animation: none; }
                              .spinner { animation: none; }
                            }
                            """
                        )
                    ],
                    script[
                        Markup(
                            signal("marimo-studio:receiver-waiting")
                            + """
                            const refreshUrl = """
                            + refresh
                            + """;
                            const poll = async () => {
                              try {
                                const response = await fetch(refreshUrl, {
                                  method: "HEAD",
                                  cache: "no-store",
                                });
                                if (response.status !== 202) {
                                  """
                            + signal("marimo-studio:receiver-unready")
                            + """
                                  location.replace(refreshUrl);
                                  return;
                                }
                              } catch {}
                              setTimeout(poll, 300);
                            };
                            setTimeout(poll, 300);
                            """
                        )
                    ],
                )
            ],
            body[
                node_list(
                    main({"role": "status", "aria-live": "polite"})[
                        node_list(
                            span({"class": "spinner", "aria-hidden": "true"})[""],
                            p["Starting notebook"],
                        )
                    ]
                )
            ],
        )
    ]
    return render(cast(Node, node))
