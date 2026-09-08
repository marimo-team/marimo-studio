"""Serve runtime configuration for standalone and Studio-owned views."""

from __future__ import annotations

import asyncio
import re

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from marimo_studio._delivery.runtime_config import encode_runtime_config
from marimo_studio._delivery.urls import STUDIO_CLIENT_QUERY_PARAM
from marimo_studio._server.agent.clients import StudioClientRegistry
from marimo_studio._server.auth import (
    error_response,
    forbidden_response,
    has_edit_access,
)
from marimo_studio._server.headers import NO_STORE
from marimo_studio._server.ports import (
    ExistingSessionAttachment,
    SessionState,
)
from marimo_studio._server.presentation.access import capability_forbidden
from marimo_studio._server.presentation.capability import (
    PresentationCapability,
)
from marimo_studio._server.presentation.payload import build_runtime_config
from marimo_studio._server.presentation.service import NotebookPresentation
from marimo_studio._server.presentation.session_ids import SessionIdAllocator
from marimo_studio._server.records import ServerContext
from marimo_studio._server.runtime.catalog import RuntimeRegistry
from marimo_studio._server.runtime.progress import RuntimeProgressSink
from marimo_studio._server.runtime.stream import (
    RUNTIME_STREAM_MEDIA_TYPE,
    runtime_config_stream,
)
from marimo_studio._workspace.models import StudioWorkspace
from marimo_studio.errors import RuntimeConfigTooLargeError
from marimo_studio.errors._internal import RuntimeSyncError

_CLIENT_PATTERN = re.compile(r"[A-Za-z0-9_-]{16,128}")
_PREVIEW_SESSION_HEADER = "Marimo-Studio-Preview-Session-Id"


async def available_runtime_options(
    context: ServerContext,
    presentation: NotebookPresentation,
    studio: StudioWorkspace,
    view_name: str,
    runtimes: RuntimeRegistry,
) -> tuple[tuple[tuple[str, str], ...], str]:
    """Return runtimes compatible with one current presentation snapshot."""
    snapshot = await presentation.snapshot_async(view_name)
    available = list(runtimes.options_for(studio, context))
    if any(site.allowed_targets is None for site in snapshot.mounts):
        available = [item for item in available if item[0] != "zero-python"]
    return tuple(available), snapshot.revision


async def runtime_availability_response(
    request: Request,
    context: ServerContext,
    presentation: NotebookPresentation,
    studio: StudioWorkspace,
    view_name: str,
    runtimes: RuntimeRegistry,
) -> JSONResponse:
    available, revision = await available_runtime_options(
        context,
        presentation,
        studio,
        view_name,
        runtimes,
    )
    return JSONResponse(
        {
            "schema": 1,
            "view": view_name,
            "runtimes": [runtime_id for runtime_id, _label in available],
            "revision": revision,
        },
        headers=NO_STORE,
    )


async def runtime_config_response(
    request: Request,
    context: ServerContext,
    presentation: NotebookPresentation,
    clients: StudioClientRegistry,
    view_name: str,
    *,
    sessions: SessionState,
    attachment: ExistingSessionAttachment,
    runtimes: RuntimeRegistry,
    session_ids: SessionIdAllocator,
    presentation_capability: PresentationCapability | None = None,
) -> Response:
    """Return configuration bound to the requesting Studio editor session."""
    client_id = request.query_params.get(STUDIO_CLIENT_QUERY_PARAM)
    preview_session_id = request.headers.get(_PREVIEW_SESSION_HEADER)
    if client_id is not None:
        if presentation_capability is None and not has_edit_access(request.scope):
            return forbidden_response()
        if (
            _CLIENT_PATTERN.fullmatch(client_id) is None
            or preview_session_id is None
            or not sessions.is_session_id(preview_session_id)
        ):
            return _invalid_studio_session()
    if presentation_capability is not None:
        runtime_session_id = presentation_capability.runtime_session_id
        if runtime_session_id is None:
            return capability_forbidden()
        presentation_session_id = presentation_capability.session_id
        lookup_session_id = (
            runtime_session_id if sessions.exists(context, runtime_session_id) else None
        )
    else:
        if client_id is not None and preview_session_id is not None:
            presentation_session_id = preview_session_id
            runtime_session_id = session_ids.assign_runtime(
                context,
                sessions,
                view_name,
                presentation_session_id,
            )
        else:
            presentation_session_id, runtime_session_id = session_ids.assign_pair(
                context,
                sessions,
                view_name,
            )
        lookup_session_id = None

    requested_revision = request.query_params.get("revision")
    if presentation_capability is not None:
        if presentation_capability.kind == "renewal":
            if requested_revision is None:
                return _revision_unavailable()
            current = await presentation.snapshot_async(
                view_name,
                profile="development" if context.mode == "edit" else "production",
            )
            if current.revision != requested_revision:
                return _revision_unavailable()
            snapshot = current
        else:
            capability_revision = presentation_capability.revision
            if capability_revision is None:
                return _revision_unavailable()
            if (
                requested_revision is not None
                and requested_revision != capability_revision
            ):
                return _revision_unavailable()
            snapshot = presentation.snapshot_for_revision(
                view_name,
                capability_revision,
            )
            if snapshot is None:
                return _revision_unavailable()
    else:
        current = await presentation.snapshot_async(
            view_name,
            profile="development" if context.mode == "edit" else "production",
        )
        if requested_revision is not None and requested_revision != current.revision:
            return _revision_unavailable()
        snapshot = current
    if client_id is not None:
        lookup_session_id = await clients.session_for_client(client_id)
        if lookup_session_id is None:
            return _session_pending()
        if not sessions.exists(context, lookup_session_id):
            return _session_pending()
        if not sessions.ensure_started(context, lookup_session_id):
            return _session_pending(
                "Studio is waiting for notebook startup.",
                code="runtime-startup-pending",
            )

    async def configuration(progress: RuntimeProgressSink | None = None) -> Response:
        try:
            payload = await build_runtime_config(
                snapshot,
                context,
                runtimes,
                request.query_params.get("runtime"),
                lookup_session_id,
                lookup_session_id if client_id is not None else None,
                presentation_session_id,
                runtime_session_id,
                client_id=client_id,
                progress=progress,
            )
            encoded = await asyncio.to_thread(encode_runtime_config, payload)
        except RuntimeSyncError as error:
            return _session_pending(str(error))
        except RuntimeConfigTooLargeError as error:
            return error_response(error)
        if client_id is not None:
            assert preview_session_id is not None
            runtime = payload.get("runtime")
            if (
                isinstance(runtime, dict)
                and runtime.get("id") == "server"
                and runtime_session_id is not None
                and lookup_session_id is not None
                and not attachment.attach(
                    context,
                    runtime_session_id,
                    lookup_session_id,
                )
            ):
                return _session_pending(
                    "Studio is waiting for an earlier preview connection to finish."
                )
        return Response(encoded, media_type="application/json", headers=NO_STORE)

    if any(
        accepted.strip() == RUNTIME_STREAM_MEDIA_TYPE
        for accepted in request.headers.get("accept", "").split(",")
    ):
        return runtime_config_stream(configuration)
    return await configuration()


def _invalid_studio_session() -> JSONResponse:
    return JSONResponse(
        {
            "error": "invalid-studio-session",
            "message": "The Studio preview session context is invalid.",
        },
        status_code=400,
        headers=NO_STORE,
    )


def _session_pending(
    message: str = "The Studio editor session is still connecting.",
    *,
    code: str = "runtime-sync-pending",
) -> JSONResponse:
    return JSONResponse(
        {
            "error": code,
            "message": message,
            "transient": True,
        },
        status_code=409,
        headers=NO_STORE,
    )


def _revision_unavailable() -> JSONResponse:
    return JSONResponse(
        {
            "error": "presentation-revision-unavailable",
            "message": "The requested presentation revision is no longer available.",
            "transient": True,
        },
        status_code=409,
        headers=NO_STORE,
    )
