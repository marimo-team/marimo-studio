"""Render a view's declared renders for one reader, and serve rendered files.

A page asks for a render by name. With the Python runtime, Studio captures the
render's declared reads from the reader's kernel session, and rejects a
capture that spans a notebook run so one render never mixes results from two
runs. The reads use their own kernel-side owner, so they never release the
page's own output hosts. Browser runtimes compute results in the reader's tab
and post them, which Studio accepts only in edit mode.

Each render belongs to its HTTP request. A client that aborts the request
leaves the shared render job, which stops after a short grace period once no
request waits on it. The response names the bundle's files, which the reader
then fetches from the ``renders/<bundle>/<path>`` route with byte ranges.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Mapping
from pathlib import PurePosixPath

from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response

from marimo_studio._artifacts.paths import normalized_artifact_path
from marimo_studio._notebook.records import CellRef
from marimo_studio._projections.resolution import (
    ProjectionRequest,
    ProjectionResolutionError,
    ResolvedProjection,
    resolve_projection,
)
from marimo_studio._projections.runtime_records import output_representation
from marimo_studio._server.auth import error_response
from marimo_studio._server.headers import NO_STORE
from marimo_studio._server.ports import SessionState
from marimo_studio._server.presentation.ports import (
    KernelProjectionHost,
    ProjectionUnavailable,
)
from marimo_studio._server.presentation.projection_routes import projection_snapshot
from marimo_studio._server.presentation.renders import RenderStore, RenderUnavailable
from marimo_studio._server.presentation.service import (
    NotebookPresentation,
    PresentationSnapshot,
)
from marimo_studio._server.records import ServerContext
from marimo_studio._server.request_body import (
    JSONBodyError,
    json_body_error_response,
    read_json_body,
)
from marimo_studio._server.request_lifecycle import (
    RequestDisconnected,
    run_while_connected,
)
from marimo_studio._server.runtime.catalog import (
    revalidate_runtime_cells,
    runtime_cell_bindings,
)
from marimo_studio._views.records import DiagnosticsError
from marimo_studio._views.renders import (
    RenderBundle,
    RenderInputError,
    absent_reads,
    admit_render_inputs,
    check_render_budget,
    read_accept,
    value_read_failure,
)
from marimo_studio.errors import ConfigurationError
from marimo_studio.errors._internal import RuntimeSyncError
from marimo_studio.view_providers import ProjectDiagnostic, Representation
from marimo_studio.view_providers._artifact_sites import ArtifactSite, read_sites

# Media types a browser can run scripts in.
_ACTIVE_MEDIA = re.compile(r"(?:^text/html|xml)(?:$|;)", re.IGNORECASE)
# Room for the value and output budgets, with outputs as base64 data URLs.
_REQUEST_MAX_BYTES = 32 * 1024 * 1024
# A capture that spans a notebook run starts again briefly. A longer run
# answers `render-inputs-unsettled`, and the page requests again once the
# notebook settles.
_CAPTURE_DELAYS = (0.0, 0.1, 0.2, 0.4, 0.8)


def _error(
    code: str, message: str, status: int, *, transient: bool = False
) -> JSONResponse:
    body: dict[str, object] = {"error": code, "message": message}
    if transient:
        body["transient"] = True
    return JSONResponse(body, status_code=status, headers=NO_STORE)


def _failure(diagnostics: tuple[ProjectDiagnostic, ...]) -> JSONResponse:
    return JSONResponse(
        {
            "error": "render-failed",
            "diagnostics": [item.to_dict() for item in diagnostics],
        },
        status_code=422,
        headers=NO_STORE,
    )


class _Unsettled(Exception):
    """The notebook ran while Studio captured a render's inputs."""


def _read_requests(
    snapshot: PresentationSnapshot, sites: tuple[ArtifactSite, ...], kind: str
) -> tuple[ResolvedProjection, ...]:
    """Resolve the reads of one kind that have a notebook producer.

    A read without one, such as a value the notebook does not define, stays
    absent, and the render applies its default.
    """
    resolved: list[ResolvedProjection] = []
    for site in sites:
        if site.kind != kind or not site.targets:
            continue
        try:
            resolved.append(
                resolve_projection(
                    snapshot.symbols,
                    snapshot.sites,
                    ProjectionRequest(site.id, f"render-{site.id}", site.targets[0]),
                )
            )
        except ProjectionResolutionError:
            continue
    return tuple(resolved)


async def _capture(
    context: ServerContext,
    snapshot: PresentationSnapshot,
    render: PurePosixPath,
    session_id: str,
    projections: KernelProjectionHost,
    sessions: SessionState,
) -> tuple[dict[str, object], dict[str, Representation], dict[str, Representation]]:
    """Read one render's inputs from the reader's kernel between two runs.

    Raises ``_Unsettled`` when the notebook ran during the capture, and
    ``DiagnosticsError`` for a value the render cannot read. A value the
    notebook has not computed stays absent.
    """
    sites = read_sites(snapshot.sites, render)
    values_requested = _read_requests(snapshot, sites, "value")
    outputs_requested = _read_requests(snapshot, sites, "output")
    cells_requested = _read_requests(snapshot, sites, "cell")
    before = await sessions.live_cells(context, session_id)
    if before is None or before.execution_pending:
        raise _Unsettled
    refs = runtime_cell_bindings(snapshot, before)
    runtime_cell_refs = {
        CellRef.parse(reference): runtime_id for reference, runtime_id in refs.items()
    }
    reader = f"{session_id}:render:{render}"
    values: dict[str, object] = {}
    if values_requested:
        read = await projections.read_values(
            context,
            session_id,
            snapshot.revision,
            values_requested,
            values_requested,
            consumer_id=session_id,
            runtime_cell_refs=runtime_cell_refs,
            reader=reader,
        )
        failures = tuple(
            value_read_failure(error.code, error.message)
            for error in read.errors.values()
            if error.code != "value-path-unavailable"
        )
        if failures:
            raise DiagnosticsError(failures)
        values = {
            target: descriptor["value"]
            for target, descriptor in read.values.items()
            if isinstance(descriptor, dict)
        }
    # Each output reads on its own, so every figure has the full output budget.
    # An output that fails to read or shows nothing leaves the template's
    # default, and the page names it. The kernel retains each output it
    # formats for its reader until a read with no active outputs releases it.
    outputs: dict[str, Representation] = {}
    try:
        for projection in outputs_requested:
            read = await projections.render_outputs(
                context,
                session_id,
                snapshot.revision,
                (projection,),
                outputs_requested,
                consumer_id=session_id,
                runtime_cell_refs=runtime_cell_refs,
                reader=reader,
            )
            for target, output in read.outputs.items():
                if (
                    media := output_representation(output.mimetype, output.data)
                ) is not None:
                    outputs[target] = media
            check_render_budget({}, outputs, {})
    finally:
        if outputs_requested:
            await projections.render_outputs(
                context,
                session_id,
                snapshot.revision,
                (),
                (),
                consumer_id=session_id,
                runtime_cell_refs=runtime_cell_refs,
                reader=reader,
            )
    cells: dict[str, Representation] = {}
    if cells_requested:
        accept = read_accept(sites, "cell")
        runtime_ids = {
            item.request.target: runtime_cell_refs[item.producer]
            for item in cells_requested
            if item.producer in runtime_cell_refs
        }
        shown = sessions.cell_outputs(context, session_id, runtime_ids.values())
        for target, cell_id in runtime_ids.items():
            if cell_id in shown:
                mimetype, data = shown[cell_id]
                media = output_representation(mimetype, data, accept.get(target, ()))
                if media is not None:
                    cells[target] = media
    await revalidate_runtime_cells(sessions, context, session_id, before)
    after = await sessions.live_cells(context, session_id)
    if (
        after is None
        or after.execution_pending
        or after.execution_generation != before.execution_generation
    ):
        raise _Unsettled
    return values, outputs, cells


def _posted_media(
    posted: object,
    accept: Mapping[str, tuple[str, ...]],
) -> dict[str, Representation] | None:
    """Decode posted marimo outputs, or cell outputs in their accepted types."""
    if not isinstance(posted, dict) or not all(
        isinstance(output, dict)
        and set(output) == {"mimetype", "data"}
        and isinstance(output["mimetype"], str)
        for output in posted.values()
    ):
        return None
    decoded = {
        target: output_representation(
            output["mimetype"], output["data"], accept.get(target, ())
        )
        for target, output in posted.items()
    }
    return {target: media for target, media in decoded.items() if media is not None}


async def render_response(
    request: Request,
    context: ServerContext,
    presentation: NotebookPresentation,
    view_name: str,
    projections: KernelProjectionHost,
    sessions: SessionState,
    store: RenderStore,
    *,
    authorized_revision: str | None,
) -> Response:
    """Return the bundle of one render for the reader's notebook results.

    The Python runtime names the render, and Studio reads its inputs from the
    kernel. Browser runtimes also post the values, outputs, and cells their
    notebook computed.
    """
    try:
        body = await read_json_body(request, max_bytes=_REQUEST_MAX_BYTES)
    except JSONBodyError as error:
        return json_body_error_response(error)
    fields = set(body) if isinstance(body, dict) else set()
    posted = fields == {"revision", "render", "values", "outputs", "cells"}
    if (
        not isinstance(body, dict)
        or not (posted or fields == {"revision", "render"})
        or not isinstance(body["revision"], str)
        or not isinstance(body["render"], str)
    ):
        return _error(
            "invalid-render-request",
            "A render request names its revision and render, and browser "
            "runtimes add the values, outputs, and cells it reads.",
            400,
        )
    if posted and context.mode != "edit":
        return _error(
            "render-values-unverified",
            "Published views render from Python session values.",
            403,
        )
    snapshot = await projection_snapshot(
        presentation,
        context,
        view_name,
        body["revision"],
        authorized_revision,
    )
    if isinstance(snapshot, JSONResponse):
        return snapshot
    template = snapshot.artifact.template
    try:
        render = normalized_artifact_path(body["render"], "Render source")
    except ConfigurationError:
        render = None
    if template is None or render not in template.renders:
        declared = (
            ", ".join(source.as_posix() for source in template.renders)
            if template is not None
            else "none"
        )
        return JSONResponse(
            {
                "error": "render-unknown",
                "message": f"This view renders no file named {body['render']!r}.",
                "hint": f"Show a file the view renders: {declared}.",
            },
            status_code=404,
            headers=NO_STORE,
        )
    sites = read_sites(snapshot.sites, render)
    session_id = request.headers.get("Marimo-Session-Id") or None
    if session_id is not None and sessions.ownership(context, session_id) == "foreign":
        session_id = None

    # Capturing inputs and rendering share one disconnect scope, so a reader
    # who leaves stops both.
    async def rendered() -> tuple[RenderBundle, list[str]] | JSONResponse:
        if posted:
            values = body["values"]
            outputs = _posted_media(body["outputs"], {})
            cells = _posted_media(body["cells"], read_accept(sites, "cell"))
            if not isinstance(values, dict) or outputs is None or cells is None:
                return _error(
                    "invalid-render-request",
                    "values must be an object, and outputs and cells objects of "
                    "marimo outputs with a mimetype and data.",
                    400,
                )
            try:
                admit_render_inputs(sites, values, outputs, cells)
            except RenderInputError as error:
                return _error(error.code, str(error), 400)
        elif sites:
            if session_id is None:
                return _error(
                    "session-unavailable",
                    "The notebook session is still connecting.",
                    409,
                    transient=True,
                )
            for delay in _CAPTURE_DELAYS:
                await asyncio.sleep(delay)
                try:
                    values, outputs, cells = await _capture(
                        context,
                        snapshot,
                        render,
                        session_id,
                        projections,
                        sessions,
                    )
                    break
                except _Unsettled:
                    continue
                except RuntimeSyncError as error:
                    # A run that changes the session's cells surfaces as a
                    # transient sync error, and the next capture reads its
                    # result. Cells that need running fail at once.
                    if not error.transient:
                        raise
                    continue
            else:
                return _error(
                    "render-inputs-unsettled",
                    "The notebook is running. The render starts when it settles.",
                    409,
                    transient=True,
                )
        else:
            values, outputs, cells = {}, {}, {}
        bundle = await store.render(
            presentation,
            snapshot,
            render,
            values,
            outputs,
            cells,
            holder=session_id,
            alive=lambda session: sessions.exists(context, session),
        )
        return bundle, absent_reads(sites, values, outputs, cells)

    try:
        result = await run_while_connected(request, rendered())
    except RequestDisconnected:
        return Response(status_code=499, headers=NO_STORE)
    except RenderUnavailable as error:
        return _error("render-unavailable", str(error), 409, transient=True)
    except ProjectionUnavailable as error:
        return _error(
            getattr(error, "code", "render-inputs-unavailable"),
            str(error),
            409,
            transient=True,
        )
    except RuntimeSyncError as error:
        return error_response(error)
    except DiagnosticsError as error:
        return _failure(error.diagnostics)
    if isinstance(result, JSONResponse):
        return result
    bundle, absent = result
    return JSONResponse(
        {**bundle.to_dict(), "render": render.as_posix(), "absent": absent},
        headers=NO_STORE,
    )


def render_file_response(
    store: RenderStore,
    view_name: str,
    route: str,
) -> Response:
    """Serve one file of a rendered bundle, with byte ranges for media seeking."""
    bundle, _separator, relative = route.partition("/")
    try:
        path = normalized_artifact_path(relative, "Rendered file path")
    except ConfigurationError:
        return Response(status_code=404, headers=NO_STORE)
    found = store.file(view_name, bundle, path)
    if found is None:
        return Response(status_code=404, headers=NO_STORE)
    file, media_type, digest = found
    headers = {
        # A bundle's ID is the digest of its files, so its URLs never change
        # content.
        "Cache-Control": "private, max-age=31536000, immutable",
        "ETag": f'"sha256:{digest}"',
        "X-Content-Type-Options": "nosniff",
    }
    if _ACTIVE_MEDIA.search(media_type):
        # Rendered HTML or SVG carries reader-controlled notebook data, so it
        # runs in an opaque origin even when opened directly. Other types stay
        # outside the sandbox, which would block the browser's PDF viewer.
        headers["Content-Security-Policy"] = "sandbox allow-scripts"
    return FileResponse(file, media_type=media_type, headers=headers)
