"""Render published document templates with the values and outputs a reader sees.

The Python runtime reads values and outputs from the reader's kernel session
through the same authorization as the value and output routes. Each output
arrives in the first media type its document site accepts. The browser runtime
computes them in the reader's tab, so it posts what its hosts show, and Studio
accepts that only in edit mode.

Each render belongs to its HTTP request. A client that aborts the request
cancels the render and its provider commands. ``DocumentRenders`` owns the
render workers and the rendition cache.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from marimo_studio._projections.resolution import MAX_UNIQUE_CELL_TARGETS
from marimo_studio._projections.runtime_records import (
    ValueReadResult,
    output_representation,
)
from marimo_studio._server.headers import NO_STORE
from marimo_studio._server.ports import SessionState
from marimo_studio._server.presentation.document_renders import (
    DocumentRenders,
    RenderUnavailable,
)
from marimo_studio._server.presentation.ports import KernelProjectionHost
from marimo_studio._server.presentation.projection_routes import (
    projection_snapshot,
    read_kernel_outputs,
    read_kernel_values,
    read_session_cells,
)
from marimo_studio._server.presentation.service import (
    NotebookPresentation,
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
from marimo_studio._views.documents import (
    RenderInputError,
    Rendition,
    admit_render_inputs,
    check_render_budget,
    value_not_json,
)
from marimo_studio._views.records import DiagnosticsError
from marimo_studio.view_providers import (
    ProjectDiagnostic,
    Representation,
)
from marimo_studio.view_providers._artifact_sites import media_accept

# Room for the value and output budgets, with outputs as base64 data URLs.
_REQUEST_MAX_BYTES = 32 * 1024 * 1024


def _error(code: str, message: str, status: int) -> JSONResponse:
    return JSONResponse(
        {"error": code, "message": message},
        status_code=status,
        headers=NO_STORE,
    )


def _failure(diagnostics: tuple[ProjectDiagnostic, ...]) -> JSONResponse:
    return JSONResponse(
        {
            "error": "render-failed",
            "diagnostics": [item.to_dict() for item in diagnostics],
        },
        status_code=422,
        headers=NO_STORE,
    )


def _kernel_values(result: ValueReadResult) -> dict[str, object] | JSONResponse:
    values: dict[str, object] = {}
    for target, descriptor in result.values.items():
        if not isinstance(descriptor, dict) or descriptor.get("codec") != "json-v1":
            return _failure((value_not_json(target, "it arrived as a table"),))
        values[target] = descriptor["value"]
    return values


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


async def _kernel_inputs(
    request: Request,
    body: dict[str, object],
    context: ServerContext,
    presentation: NotebookPresentation,
    view_name: str,
    projections: KernelProjectionHost,
    sessions: SessionState,
    authorized_revision: str | None,
    cell_accept: Mapping[str, tuple[str, ...]],
) -> (
    tuple[dict[str, object], dict[str, Representation], dict[str, Representation]]
    | JSONResponse
):
    value_projections = body["valueProjections"]
    output_projections = body["outputProjections"]
    cell_projections = body["cellProjections"]
    if not (
        isinstance(value_projections, list)
        and isinstance(output_projections, list)
        and isinstance(cell_projections, list)
    ):
        return _error(
            "invalid-render-request",
            "valueProjections, outputProjections, and cellProjections must be arrays.",
            400,
        )
    if len(cell_projections) > MAX_UNIQUE_CELL_TARGETS:
        return _error(
            "invalid-render-request",
            f"cellProjections holds at most {MAX_UNIQUE_CELL_TARGETS} projection "
            "requests.",
            400,
        )
    arguments = (context, presentation, view_name, projections, sessions)
    values: dict[str, object] = {}
    if value_projections:
        read = await read_kernel_values(
            request,
            {
                "revision": body["revision"],
                "projections": value_projections,
                "activeProjections": value_projections,
            },
            *arguments,
            authorized_revision,
        )
        if isinstance(read, JSONResponse):
            return read
        decoded = _kernel_values(read[1])
        if isinstance(decoded, JSONResponse):
            return decoded
        values = decoded
    # Each output reads on its own, so every figure has the full output budget,
    # as in the page's hosts. The reads queue on the kernel in turn, and a cell
    # run between them pairs values with a newer output until the next host
    # event renders again. As with values, an output that fails to read or
    # shows nothing leaves the template's default, and the viewer names it.
    outputs: dict[str, Representation] = {}
    for projection in output_projections:
        read = await read_kernel_outputs(
            request,
            {
                "revision": body["revision"],
                "projections": [projection],
                "activeProjections": output_projections,
            },
            *arguments,
            authorized_revision,
        )
        if isinstance(read, JSONResponse):
            return read
        for target, output in read[1].outputs.items():
            if (
                media := output_representation(output.mimetype, output.data)
            ) is not None:
                outputs[target] = media
        try:
            check_render_budget({}, outputs, {})
        except DiagnosticsError as error:
            return _failure(error.diagnostics)
    cells: dict[str, Representation] = {}
    if cell_projections:
        read_cells = await read_session_cells(
            request,
            cast(str, body["revision"]),
            cell_projections,
            context,
            presentation,
            view_name,
            sessions,
            authorized_revision,
        )
        if isinstance(read_cells, JSONResponse):
            return read_cells
        for target, (mimetype, data) in read_cells.items():
            media = output_representation(mimetype, data, cell_accept.get(target, ()))
            if media is not None:
                cells[target] = media
    return values, outputs, cells


async def render_response(
    request: Request,
    context: ServerContext,
    presentation: NotebookPresentation,
    view_name: str,
    projections: KernelProjectionHost,
    sessions: SessionState,
    renders: DocumentRenders,
    *,
    authorized_revision: str | None,
) -> Response:
    """Return the current document for one reader's notebook values and outputs.

    The Python runtime names the projections Studio reads from the kernel.
    Browser runtimes post the values and outputs their hosts show.
    """
    try:
        body = await read_json_body(request, max_bytes=_REQUEST_MAX_BYTES)
    except JSONBodyError as error:
        return json_body_error_response(error)
    fields = set(body) if isinstance(body, dict) else set()
    posted = fields == {"revision", "values", "outputs", "cells"}
    if (
        not isinstance(body, dict)
        or not (
            posted
            or fields
            == {"revision", "valueProjections", "outputProjections", "cellProjections"}
        )
        or not isinstance(body["revision"], str)
    ):
        return _error(
            "invalid-render-request",
            "A render request names its revision with its values, outputs, and "
            "cells, or with the value, output, and cell projections to read.",
            400,
        )
    if posted and context.mode != "edit":
        return _error(
            "render-values-unverified",
            "Published views render documents from Python session values.",
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
    if snapshot.artifact.template is None:
        return _error(
            "render-template-missing",
            "This view publishes no document template.",
            404,
        )
    cell_accept = media_accept(snapshot.sites, "cell")

    # Reading kernel inputs and rendering share one disconnect scope, so a
    # reader who leaves stops both.
    async def rendered() -> Rendition | JSONResponse:
        if posted:
            values = body["values"]
            outputs = _posted_media(body["outputs"], {})
            cells = _posted_media(body["cells"], cell_accept)
            if not isinstance(values, dict) or outputs is None or cells is None:
                return _error(
                    "invalid-render-request",
                    "values must be an object, and outputs and cells objects of "
                    "marimo outputs with a mimetype and data.",
                    400,
                )
        else:
            inputs = await _kernel_inputs(
                request,
                body,
                context,
                presentation,
                view_name,
                projections,
                sessions,
                authorized_revision,
                cell_accept,
            )
            if isinstance(inputs, JSONResponse):
                return inputs
            values, outputs, cells = inputs
        try:
            admit_render_inputs(snapshot.sites, values, outputs, cells)
        except RenderInputError as error:
            return _error(error.code, str(error), 400)
        return await renders.render(presentation, snapshot, values, outputs, cells)

    try:
        rendition = await run_while_connected(request, rendered())
    except RequestDisconnected:
        return Response(status_code=499, headers=NO_STORE)
    except RenderUnavailable as error:
        return JSONResponse(
            {"error": "render-unavailable", "message": str(error), "transient": True},
            status_code=409,
            headers=NO_STORE,
        )
    except DiagnosticsError as error:
        return _failure(error.diagnostics)
    if isinstance(rendition, JSONResponse):
        return rendition
    return Response(
        rendition.content,
        media_type=rendition.media_type,
        headers={**NO_STORE, "X-Content-Type-Options": "nosniff"},
    )
