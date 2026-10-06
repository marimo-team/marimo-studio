"""Compose the authenticated document that owns the native editor."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
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
    editor_path,
    relative_url,
    studio_path,
    with_notebook_query,
    with_query,
)
from marimo_studio._server.records import ServerContext
from marimo_studio._server.server_instance import server_instance_id
from marimo_studio._server.studio.editor_capability import (
    editor_binding_capability,
)
from marimo_studio._server.studio.event_capability import (
    workspace_events_capability,
)
from marimo_studio._server.studio.session_handoff import HostSessionTicket
from marimo_studio._workspace.models import StudioWorkspace

StudioHostState = Literal["unconfigured", "needs-view", "ready"]


def studio_bootstrap_payload(
    config: StudioWorkspace,
    context: ServerContext,
    selected: str,
    query: Sequence[tuple[str, str]],
    runtimes: tuple[tuple[str, str], ...],
    client_id: str,
    native_session_id: str,
    *,
    request_path: str,
    trusted_server_runtime: bool = False,
) -> dict[str, object]:
    """Build the ready-workspace contract served from app path `request_path`."""
    server_instance = server_instance_id(context.server_token)
    events_capability = workspace_events_capability(
        context.server_token,
        context.file_key,
        context.base_url,
        client_id,
    )
    binding_capability = editor_binding_capability(
        context.server_token,
        context.file_key,
        context.base_url,
        client_id,
        native_session_id,
    )

    def routed(path: str) -> str:
        return relative_url(request_path, with_query(path, context.routing_query))

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
        "defaultRuntime": (
            config.default_runtime
            if config.default_runtime in {runtime_id for runtime_id, _label in runtimes}
            else runtimes[0][0]
        ),
        "trustedServerRuntime": trusted_server_runtime,
        "urls": {
            "editor": relative_url(
                request_path,
                editor_path(
                    context.file_key,
                    query,
                    client_id,
                    server_instance,
                    native_session_id,
                    binding_capability,
                ),
            ),
            "agent": routed(SUPPORT_PATH),
            "events": with_query(
                routed(f"{SUPPORT_PATH}/dev/events"),
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
            "query": routed(f"{SUPPORT_PATH}/query"),
            "studioPrefix": routed(studio_path()),
            "viewPrefix": routed("/"),
            "viewSupportPrefix": routed(f"{SUPPORT_PATH}/views"),
            "views": routed(f"{SUPPORT_PATH}/views"),
        },
        "workspaceId": workspace_id,
        "clientId": client_id,
        "serverInstance": server_instance,
        "serverToken": context.server_token,
    }


def studio_document(
    context: ServerContext,
    query: Sequence[tuple[str, str]],
    runtimes: tuple[tuple[str, str], ...],
    client_id: str,
    native_session_id: str,
    *,
    request_path: str,
    state: StudioHostState,
    config: StudioWorkspace | None = None,
    selected: str | None = None,
    default_view: str | None = None,
    generation: str | None = None,
    trusted_server_runtime: bool = False,
) -> str:
    """Return the stable editor host served from app path `request_path`."""
    notebook = context.notebook
    server_instance = server_instance_id(context.server_token)
    events_capability = workspace_events_capability(
        context.server_token,
        context.file_key,
        context.base_url,
        client_id,
    )
    binding_capability = editor_binding_capability(
        context.server_token,
        context.file_key,
        context.base_url,
        client_id,
        native_session_id,
    )
    host_session = HostSessionTicket.issue(
        context,
        native_session_id,
        query,
    )

    def reference(path: str) -> str:
        return relative_url(request_path, path)

    def routed(path: str) -> str:
        return reference(with_query(path, context.routing_query))

    native_editor_url = reference(
        editor_path(
            context.file_key,
            query,
            client_id,
            server_instance,
            native_session_id,
            binding_capability,
        )
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
        "serverToken": context.server_token,
        "urls": {
            "bootstrap": reference(
                with_query(
                    with_notebook_query(
                        f"{SUPPORT_PATH}/bootstrap",
                        query,
                        context.routing_query,
                    ),
                    (*client_query, *editor_query),
                )
            ),
            "editor": native_editor_url,
            "events": with_query(
                routed(f"{SUPPORT_PATH}/dev/events"),
                events_query,
            ),
            "views": routed(f"{SUPPORT_PATH}/views"),
        },
    }
    if state == "needs-view":
        assert default_view is not None and generation is not None
        host["defaultView"] = default_view
        host["generation"] = generation

    bootstrap: dict[str, object] | None = None
    if state == "ready":
        assert config is not None and selected is not None
        bootstrap = studio_bootstrap_payload(
            config,
            context,
            selected,
            query,
            runtimes,
            client_id,
            native_session_id,
            request_path=request_path,
            trusted_server_runtime=trusted_server_runtime,
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
                    link(rel="icon", href=reference("/favicon.ico")),
                    link(
                        rel="stylesheet",
                        href=reference(f"{SUPPORT_PATH}/assets/studio.css"),
                    ),
                    *(
                        (Markup(context.trusted_html_head),)
                        if context.trusted_html_head
                        else ()
                    ),
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
                    script(
                        id="marimo-studio-host-session",
                        type="application/json",
                    )[Markup(_json(host_session.browser_config("complete")))],
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
                    noscript[
                        node_list(
                            "Studio requires JavaScript. ",
                            a(href=native_editor_url)["Open the notebook editor"],
                            ".",
                        )
                    ],
                    script(
                        type="module",
                        src=reference(f"{SUPPORT_PATH}/assets/studio.js"),
                    ),
                )
            ],
        )
    ]
    return render(cast(Node, node))


def _json(value: object) -> str:
    return json.dumps(value, separators=(",", ":")).replace("<", "\\u003c")
