"""Compose the authenticated document that owns the native editor."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Literal, cast

from htpy import (
    Node,
    a,
    body,
    div,
    head,
    html,
    iframe,
    link,
    meta,
    noscript,
    script,
    title,
)
from markupsafe import Markup

from marimo_studio._delivery.html import node_list, render
from marimo_studio._delivery.urls import (
    ACTIVE_VIEW_QUERY_PARAM,
    EDITOR_BINDING_CAPABILITY_QUERY_PARAM,
    SERVER_INSTANCE_QUERY_PARAM,
    STUDIO_CLIENT_QUERY_PARAM,
    SUPPORT_PATH,
    WORKSPACE_EVENTS_CAPABILITY_QUERY_PARAM,
    editor_url,
    public_url,
    studio_url,
    with_notebook_query,
    with_query,
)
from marimo_studio._server.server_instance import server_instance_id
from marimo_studio._server.studio.editor_capability import (
    editor_binding_capability,
)
from marimo_studio._server.studio.event_capability import (
    workspace_events_capability,
)
from marimo_studio._workspace.models import StudioWorkspace

StudioHostState = Literal["unconfigured", "needs-view", "ready"]


def studio_bootstrap_payload(
    config: StudioWorkspace,
    base_url: str,
    selected: str,
    server_token: str,
    file_key: str,
    query: Sequence[tuple[str, str]],
    routing_query: Sequence[tuple[str, str]],
    runtimes: tuple[tuple[str, str], ...],
    client_id: str,
    native_session_id: str,
) -> dict[str, object]:
    """Build the ready-workspace contract for one stable browser client."""
    root_url = public_url(base_url, "/")
    support_url = public_url(base_url, SUPPORT_PATH)
    server_instance = server_instance_id(server_token)
    events_capability = workspace_events_capability(
        server_token,
        file_key,
        base_url,
        client_id,
    )
    binding_capability = editor_binding_capability(
        server_token,
        file_key,
        base_url,
        client_id,
        native_session_id,
    )

    def routed(url: str) -> str:
        return with_query(url, routing_query)

    workspace_id = hashlib.sha256(str(config.notebook).encode()).hexdigest()[:16]
    return {
        "schema": 1,
        "notebook": {"name": config.notebook.name},
        "defaultView": config.default_view,
        "selectedView": selected,
        "views": list(config.views),
        "runtimes": [
            {"id": runtime_id, "label": label} for runtime_id, label in runtimes
        ],
        "defaultRuntime": config.default_runtime,
        "urls": {
            "editor": editor_url(
                base_url,
                file_key,
                query,
                client_id,
                server_instance,
                native_session_id,
                binding_capability,
            ),
            "agent": routed(support_url),
            "events": with_query(
                routed(f"{support_url}/dev/events"),
                (
                    (STUDIO_CLIENT_QUERY_PARAM, client_id),
                    (ACTIVE_VIEW_QUERY_PARAM, selected),
                    (SERVER_INSTANCE_QUERY_PARAM, server_instance),
                    (
                        WORKSPACE_EVENTS_CAPABILITY_QUERY_PARAM,
                        events_capability,
                    ),
                ),
            ),
            "query": routed(f"{support_url}/query"),
            "studioPrefix": routed(studio_url(base_url)),
            "viewPrefix": routed(root_url),
            "viewSupportPrefix": routed(f"{support_url}/views"),
            "views": routed(f"{support_url}/views"),
        },
        "workspaceId": workspace_id,
        "clientId": client_id,
        "serverInstance": server_instance,
        "serverToken": server_token,
    }


def studio_document(
    notebook: Path,
    base_url: str,
    server_token: str,
    file_key: str,
    query: Sequence[tuple[str, str]],
    routing_query: Sequence[tuple[str, str]],
    runtimes: tuple[tuple[str, str], ...],
    client_id: str,
    native_session_id: str,
    *,
    state: StudioHostState,
    config: StudioWorkspace | None = None,
    selected: str | None = None,
    default_view: str | None = None,
) -> str:
    """Return the stable editor host and optional ready-workspace bootstrap."""
    server_instance = server_instance_id(server_token)
    events_capability = workspace_events_capability(
        server_token,
        file_key,
        base_url,
        client_id,
    )
    binding_capability = editor_binding_capability(
        server_token,
        file_key,
        base_url,
        client_id,
        native_session_id,
    )
    support_url = public_url(base_url, SUPPORT_PATH)

    def routed(url: str) -> str:
        return with_query(url, routing_query)

    native_editor_url = editor_url(
        base_url,
        file_key,
        query,
        client_id,
        server_instance,
        native_session_id,
        binding_capability,
    )
    client_query = (
        (STUDIO_CLIENT_QUERY_PARAM, client_id),
        (SERVER_INSTANCE_QUERY_PARAM, server_instance),
    )
    editor_query = (
        ("session_id", native_session_id),
        (EDITOR_BINDING_CAPABILITY_QUERY_PARAM, binding_capability),
    )
    events_query = (
        *client_query,
        (WORKSPACE_EVENTS_CAPABILITY_QUERY_PARAM, events_capability),
    )
    host: dict[str, object] = {
        "schema": 1,
        "state": state,
        "notebook": {"name": notebook.name},
        "clientId": client_id,
        "serverInstance": server_instance,
        "serverToken": server_token,
        "urls": {
            "bootstrap": with_query(
                with_notebook_query(
                    f"{support_url}/bootstrap",
                    query,
                    routing_query,
                ),
                (*client_query, *editor_query),
            ),
            "editor": native_editor_url,
            "events": with_query(
                routed(f"{support_url}/dev/events"),
                events_query,
            ),
            "views": routed(f"{support_url}/views"),
        },
    }
    if state == "needs-view":
        assert default_view is not None
        host["defaultView"] = default_view

    bootstrap: dict[str, object] | None = None
    if state == "ready":
        assert config is not None and selected is not None
        bootstrap = studio_bootstrap_payload(
            config,
            base_url,
            selected,
            server_token,
            file_key,
            query,
            routing_query,
            runtimes,
            client_id,
            native_session_id,
        )

    fallback = (
        div(
            {
                "class": "studio-opening",
                "role": "status",
                "aria-busy": "true",
            }
        )["Opening Studio"]
        if state == "ready"
        else None
    )
    node = html(lang="en", data_marimo_studio_state=state)[
        node_list(
            head[
                node_list(
                    meta(charset="utf-8"),
                    meta(
                        name="viewport",
                        content="width=device-width, initial-scale=1",
                    ),
                    title[f"{notebook.name} · Studio"],
                    link(rel="icon", href=public_url(base_url, "/favicon.ico")),
                    link(rel="stylesheet", href=f"{support_url}/assets/studio.css"),
                )
            ],
            body[
                node_list(
                    div(id="marimo-studio-editor-host")[
                        cast(
                            Node,
                            iframe(
                                id="marimo-studio-editor",
                                src=native_editor_url,
                                title="Marimo editor",
                                allow="clipboard-read; clipboard-write",
                            ),
                        )
                    ],
                    div(id="marimo-studio-root")[fallback],
                    script(
                        id="marimo-studio-host",
                        type="application/json",
                    )[Markup(_json(host))],
                    *(
                        (
                            script(
                                id="marimo-studio-bootstrap",
                                type="application/json",
                            )[Markup(_json(bootstrap))],
                        )
                        if bootstrap is not None
                        else ()
                    ),
                    script[
                        Markup(
                            """
                            const studioUrl = new URL(globalThis.location.href);
                            studioUrl.searchParams.delete("session_id");
                            studioUrl.searchParams.delete("marimo_studio_resume");
                            globalThis.history.replaceState(
                              globalThis.history.state,
                              "",
                              studioUrl,
                            );
                            """
                        )
                    ],
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


def _json(value: object) -> str:
    return json.dumps(value, separators=(",", ":")).replace("<", "\\u003c")
