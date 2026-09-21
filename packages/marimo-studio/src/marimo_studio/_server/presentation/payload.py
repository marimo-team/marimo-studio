"""Build browser documents and runtime payloads from immutable snapshots."""

from __future__ import annotations

from pathlib import Path

from marimo_studio._delivery.html import runtime_document
from marimo_studio._delivery.runtime_config import (
    RuntimeConfigInputs,
    runtime_projection_revision,
)
from marimo_studio._delivery.urls import (
    EDITOR_SESSION_QUERY_PARAM,
    SERVER_INSTANCE_QUERY_PARAM,
    SUPPORT_PATH,
    artifact_document_root_url,
    artifact_view_url,
    authored_view_root_url,
    public_url,
    with_query,
)
from marimo_studio._projections.resolution import (
    projection_policy,
    projection_targets,
)
from marimo_studio._projections.resolved import ProjectionDiagnostic
from marimo_studio._server.presentation.capability import (
    presentation_revision_url,
)
from marimo_studio._server.presentation.service import PresentationSnapshot
from marimo_studio._server.records import ServerContext
from marimo_studio._server.runtime.catalog import RuntimeRegistry
from marimo_studio._server.runtime.progress import RuntimeProgressSink
from marimo_studio._server.server_instance import server_instance_id


def presentation_support_url(
    context: ServerContext,
    snapshot: PresentationSnapshot,
    session_id: str,
    runtime_session_id: str,
    *,
    editor_session_id: str | None = None,
) -> str:
    """Return revision-bound support authority for one presentation session."""
    return with_query(
        presentation_revision_url(
            context,
            snapshot,
            session_id,
            f"{SUPPORT_PATH}/views/{snapshot.view_name}",
            runtime_session_id=runtime_session_id,
        ),
        (
            *context.routing_query,
            (SERVER_INSTANCE_QUERY_PARAM, server_instance_id(context.server_token)),
            *(
                ((EDITOR_SESSION_QUERY_PARAM, editor_session_id),)
                if editor_session_id is not None
                else ()
            ),
        ),
    )


def render_presentation_document(
    snapshot: PresentationSnapshot,
    context: ServerContext,
    *,
    marimo_version: str,
    runtime: str,
    runtime_explicit: bool,
    replay: bool,
    renewal_token: str,
    session_id: str,
    runtime_session_id: str,
    client_id: str | None = None,
    lifecycle_id: int | None = None,
    editor_session_id: str | None = None,
) -> str:
    view_name = snapshot.view_name
    root_url = presentation_revision_url(
        context,
        snapshot,
        session_id,
        artifact_view_url(
            "",
            view_name,
            snapshot.artifact.artifact_revision,
        ),
        runtime_session_id=runtime_session_id if runtime == "server" else None,
    )
    root_url = artifact_document_root_url(root_url, snapshot.artifact.document)
    support_url = presentation_support_url(
        context,
        snapshot,
        session_id,
        runtime_session_id,
        editor_session_id=editor_session_id,
    )
    return runtime_document(
        snapshot.document,
        root_url=root_url,
        support_url=support_url,
        assets_url=presentation_revision_url(
            context,
            snapshot,
            session_id,
            f"{SUPPORT_PATH}/assets",
            runtime_session_id=runtime_session_id,
        ),
        dev=context.dev,
        revision=snapshot.revision,
        runtime=runtime,
        runtime_explicit=runtime_explicit,
        replay=replay,
        renewal_token=renewal_token,
        filename=context.file_key,
        marimo_version=marimo_version,
        session_id=session_id,
        client_id=client_id,
        lifecycle_id=lifecycle_id,
        runtime_session_id=runtime_session_id if runtime == "server" else None,
    )


async def build_runtime_config(
    snapshot: PresentationSnapshot,
    context: ServerContext,
    runtimes: RuntimeRegistry,
    runtime_id: str | None = None,
    session_id: str | None = None,
    binding_id: str | None = None,
    presentation_session_id: str | None = None,
    runtime_session_id: str | None = None,
    *,
    client_id: str | None = None,
    progress: RuntimeProgressSink | None = None,
) -> dict[str, object]:
    resolved = snapshot.resolved
    view_name = snapshot.view_name
    view = resolved.views[view_name]
    capability_session_id = presentation_session_id or session_id
    if capability_session_id is None:
        raise ValueError("A presentation session is required for runtime configuration")
    runtime_authority_session_id = runtime_session_id or capability_session_id
    projection = await runtimes.project(
        snapshot,
        context,
        runtime_id,
        session_id,
        binding_id,
        capability_session_id,
        runtime_authority_session_id,
        client_id=client_id,
        progress=progress,
    )
    targets = projection_targets(snapshot.symbols, snapshot.mounts)
    mounts = tuple(site.to_dict() for site in snapshot.mounts)
    policy = projection_policy()
    diagnostics = tuple(
        _browser_diagnostic(
            diagnostic,
            notebook=resolved.workspace.notebook,
            developer=context.dev or context.mode == "edit",
        )
        for diagnostic in view.diagnostics
    )
    projection_revision = runtime_projection_revision(
        source_revision=snapshot.source_revision,
        view=view_name,
        runtime_id=projection.runtime_id,
        runtime_instance=projection.instance,
        mounts=mounts,
        projection_targets=targets,
        projection_policy=policy,
        runtime_cell_refs=projection.cell_refs,
        diagnostics=diagnostics,
    )
    public_root_url = with_query(
        public_url(context.base_url, "/"),
        context.routing_query,
    )
    inputs = RuntimeConfigInputs(
        view=view_name,
        views=tuple(resolved.workspace.views),
        runtime_id=projection.runtime_id,
        runtime_instance=projection.instance,
        runtime_data=projection.data,
        root_url=public_url(context.base_url, "/"),
        public_root_url=public_root_url,
        document_root_url=(
            authored_view_root_url(context.base_url, context.file_key)
            if context.routing_query
            else public_root_url
        ),
        support_url=presentation_support_url(
            context,
            snapshot,
            capability_session_id,
            runtime_authority_session_id,
            editor_session_id=session_id if client_id is not None else None,
        ),
        projection_revision=projection_revision,
        show_cell_logs=resolved.workspace.show_cell_logs,
        projection_targets=targets,
        mounts=mounts,
        projection_policy=policy,
        runtime_cell_refs=projection.cell_refs,
        diagnostics=diagnostics,
        app_config=resolved.notebook.app_config,
        user_config=context.user_config,
        config_overrides=context.config_overrides,
        dev=context.dev,
        mode=context.mode,
        presentation_session_id=capability_session_id,
    )
    return inputs.to_dict(revision=snapshot.revision)


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
    value: dict[str, object] = {
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
    if diagnostic.site_id is not None:
        value["siteId"] = diagnostic.site_id
    return value
