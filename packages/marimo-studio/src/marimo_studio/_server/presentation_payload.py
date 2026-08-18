"""Build browser documents and runtime payloads from immutable snapshots."""

from __future__ import annotations

from pathlib import Path

from marimo_studio._capabilities import ServerContext
from marimo_studio._html import runtime_document
from marimo_studio._server.presentation import PresentationSnapshot
from marimo_studio._server.runtimes import RuntimeRegistry
from marimo_studio._server.server_instance import server_instance_id
from marimo_studio._urls import (
    SERVER_INSTANCE_QUERY_PARAM,
    SUPPORT_PATH,
    authored_view_root_url,
    public_url,
    view_url,
    with_query,
)
from marimo_studio._workspace.models import ProjectionDiagnostic


def _support_query(context: ServerContext) -> tuple[tuple[str, str], ...]:
    return (
        *context.routing_query,
        (SERVER_INSTANCE_QUERY_PARAM, server_instance_id(context.server_token)),
    )


def render_presentation_document(
    snapshot: PresentationSnapshot,
    context: ServerContext,
    *,
    marimo_version: str,
) -> str:
    view_name = snapshot.view_name
    root_url = (
        f"{authored_view_root_url(context.base_url, context.file_key)}{view_name}/"
        if context.routing_query
        else view_url(context.base_url, view_name)
    )
    support_url = with_query(
        public_url(
            context.base_url,
            f"{SUPPORT_PATH}/views/{view_name}",
        ),
        _support_query(context),
    )
    return runtime_document(
        snapshot.document,
        root_url=root_url,
        support_url=support_url,
        assets_url=public_url(
            context.base_url,
            f"{SUPPORT_PATH}/assets",
        ),
        dev=context.dev,
        revision=snapshot.revision,
        runtime=snapshot.resolved.workspace.default_runtime,
        filename=context.file_key,
        marimo_version=marimo_version,
    )


def build_runtime_config(
    snapshot: PresentationSnapshot,
    context: ServerContext,
    runtimes: RuntimeRegistry,
    runtime_id: str | None = None,
    session_id: str | None = None,
    binding_id: str | None = None,
) -> dict[str, object]:
    resolved = snapshot.resolved
    view_name = snapshot.view_name
    view = resolved.views[view_name]
    provider, available = runtimes.select(
        resolved.workspace,
        context,
        runtime_id,
    )
    projection = provider.project(snapshot, context, session_id, binding_id)
    public_root_url = with_query(
        public_url(context.base_url, "/"),
        context.routing_query,
    )
    return {
        "schema": 1,
        "revision": snapshot.revision,
        "view": view_name,
        "views": list(resolved.workspace.views),
        "runtime": {
            "id": provider.id,
            "instance": projection.instance,
            "available": list(available),
            "data": projection.data,
            **(
                {"controls": {"cells": projection.control_cells}}
                if projection.control_cells is not None
                else {}
            ),
        },
        "rootUrl": public_url(context.base_url, "/"),
        "publicRootUrl": public_root_url,
        "documentRootUrl": (
            authored_view_root_url(context.base_url, context.file_key)
            if context.routing_query
            else public_root_url
        ),
        "supportUrl": with_query(
            public_url(
                context.base_url,
                f"{SUPPORT_PATH}/views/{view_name}",
            ),
            _support_query(context),
        ),
        "showCellLogs": resolved.workspace.show_cell_logs,
        "cellBindings": projection.cell_bindings,
        "valueBindings": projection.value_bindings,
        "outputBindings": projection.output_bindings,
        "diagnostics": [
            _browser_diagnostic(
                diagnostic,
                notebook=resolved.workspace.notebook,
                developer=context.dev or context.mode == "edit",
            )
            for diagnostic in view.diagnostics
        ],
        "appConfig": resolved.notebook.app_config,
        "userConfig": context.user_config,
        "configOverrides": context.config_overrides,
        "dev": context.dev,
        "mode": context.mode,
    }


def _browser_diagnostic(
    diagnostic: ProjectionDiagnostic,
    *,
    notebook: Path,
    developer: bool,
) -> dict[str, object]:
    try:
        source = diagnostic.source.relative_to(notebook.parent)
    except ValueError:
        source = Path(diagnostic.source.name)
    return {
        "code": diagnostic.code,
        "severity": diagnostic.severity,
        "message": diagnostic.message,
        "hint": diagnostic.hint if developer else "",
        "view": diagnostic.view,
        "projection": diagnostic.projection,
        "target": diagnostic.target,
        "source": {
            "path": str(source),
            "line": diagnostic.line,
            "column": diagnostic.column,
        },
    }


__all__ = ["build_runtime_config", "render_presentation_document"]
