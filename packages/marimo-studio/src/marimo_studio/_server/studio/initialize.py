"""Render the authenticated first-view initializer."""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import cast

from htpy import (
    Node,
    a,
    body,
    button,
    code,
    div,
    form,
    h1,
    head,
    html,
    link,
    main,
    meta,
    p,
    script,
    span,
    title,
)
from markupsafe import Markup

from marimo_studio._html import node_list, render
from marimo_studio._urls import SUPPORT_PATH, editor_url, public_url
from marimo_studio._workspace.models import StudioDefinition

_STATUS_ATTRIBUTE = "data-studio-initialization-status"


def initialization_document(
    definition: StudioDefinition,
    base_url: str,
    server_token: str,
    file_key: str,
    query: Sequence[tuple[str, str]],
) -> str:
    """Return the page that creates a definition's first view."""
    support_url = public_url(base_url, SUPPORT_PATH)
    native_editor_url = editor_url(base_url, file_key, query)
    bootstrap = json.dumps(
        {
            "schema": 1,
            "defaultView": definition.default_view,
            "createUrl": f"{support_url}/views",
            "serverToken": server_token,
        },
        separators=(",", ":"),
    ).replace("<", "\\u003c")
    node = html(lang="en", data_marimo_studio_state="needs-view")[
        node_list(
            head[
                node_list(
                    meta(charset="utf-8"),
                    meta(
                        name="viewport",
                        content="width=device-width, initial-scale=1",
                    ),
                    title[f"Initialize {definition.notebook.name} · Studio"],
                    link(rel="icon", href=public_url(base_url, "/favicon.ico")),
                    link(rel="stylesheet", href=f"{support_url}/assets/studio.css"),
                )
            ],
            body[
                node_list(
                    main(
                        {
                            "class": "studio-initialization",
                            "data-studio-initialization": True,
                        }
                    )[
                        node_list(
                            div({"class": "studio-initialization-card"})[
                                node_list(
                                    span({"class": "studio-initialization-eyebrow"})[
                                        "Marimo Studio"
                                    ],
                                    h1["Create the first view"],
                                    p[
                                        node_list(
                                            "This notebook is configured for Studio. ",
                                            "Create ",
                                            code[definition.default_view],
                                            " to open the authoring workspace.",
                                        )
                                    ],
                                    form({"data-studio-initialization-form": True})[
                                        node_list(
                                            button(type="submit")[
                                                f"Create {definition.default_view}"
                                            ],
                                            p(
                                                {
                                                    "role": "status",
                                                    "aria-live": "polite",
                                                    _STATUS_ATTRIBUTE: True,
                                                }
                                            ),
                                        )
                                    ],
                                    a(href=native_editor_url)["Open notebook editor"],
                                )
                            ],
                            script(
                                id="marimo-studio-initialization",
                                type="application/json",
                            )[Markup(bootstrap)],
                            script[
                                Markup(
                                    "const config=JSON.parse(document.getElementById("
                                    "'marimo-studio-initialization').textContent);"
                                    "const form=document.querySelector("
                                    "'[data-studio-initialization-form]');"
                                    "const status=document.querySelector("
                                    "'[data-studio-initialization-status]');"
                                    "const button=form.querySelector('button');"
                                    "form.addEventListener('submit',async(event)=>{"
                                    "event.preventDefault();button.disabled=true;"
                                    "status.textContent='Creating view…';"
                                    "try{const response=await fetch(config.createUrl,{"
                                    "method:'POST',headers:{'Content-Type':'application/json',"
                                    "'Marimo-Server-Token':config.serverToken},"
                                    "body:JSON.stringify({name:config.defaultView})});"
                                    "const payload=await response.json();"
                                    "if(!response.ok)throw new Error(payload.message||"
                                    "`Request failed with ${response.status}`);"
                                    "status.textContent='Opening Studio…';"
                                    "const target=new URL("
                                    "payload.studio_url,location.href);"
                                    "target.search=location.search;location.assign(target);"
                                    "}catch(error){"
                                    "status.textContent=error instanceof Error"
                                    "?error.message:"
                                    "'Studio could not create the view.';"
                                    "button.disabled=false;}});"
                                )
                            ],
                        )
                    ]
                )
            ],
        )
    ]
    return render(cast(Node, node))
