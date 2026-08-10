"""HTTP adapters for Studio-authored views and source files."""

from __future__ import annotations

import json
from collections.abc import Collection, Sequence
from typing import Literal, cast

from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse, Response

from marimo_studio._compat.server.sessions import has_edit_access, server_token_matches
from marimo_studio._server.presentation import NotebookPresentation
from marimo_studio._urls import studio_url, view_url, with_query
from marimo_studio._workspace.config import validate_view_name
from marimo_studio._workspace.models import StudioDefinition, StudioWorkspace
from marimo_studio._workspace.sources import read_source, write_source
from marimo_studio._workspace.views import delete_view
from marimo_studio.errors import MarimoStudioError, SourceConflictError
from marimo_studio.types import (
    BrowserDiagnostic,
    BrowserObservation,
    BrowserObservationState,
)
from marimo_studio.workspace import ensure_view

_NO_STORE = {"Cache-Control": "no-store"}


def _error(error: MarimoStudioError) -> JSONResponse:
    return JSONResponse(
        {
            "error": error.code,
            "message": error.public_message(),
            **error.diagnostic_details(),
        },
        status_code=error.status_code,
        headers=_NO_STORE,
    )


def _forbidden() -> JSONResponse:
    return JSONResponse(
        {
            "error": "edit-access-required",
            "message": "Open Studio from an editable Marimo session.",
        },
        status_code=403,
        headers=_NO_STORE,
    )


def _invalid_server_token(request: Request, expected: str) -> JSONResponse | None:
    if server_token_matches(request.scope, expected):
        return None
    missing = request.headers.get("Marimo-Server-Token") is None
    return JSONResponse(
        {
            "error": "missing-server-token" if missing else "invalid-server-token",
            "message": (
                "Marimo-Server-Token is required."
                if missing
                else "Marimo-Server-Token does not match this server."
            ),
        },
        status_code=401,
        headers=_NO_STORE,
    )


async def create_view_response(
    request: Request,
    definition: StudioDefinition,
    existing_views: Collection[str],
    base_url: str,
    server_token: str,
    routing_query: Sequence[tuple[str, str]] = (),
) -> Response:
    """Create a named view from an authenticated Studio definition."""
    if request.method != "POST":
        return Response(status_code=405)
    if not has_edit_access(request.scope):
        return _forbidden()
    if token_error := _invalid_server_token(request, server_token):
        return token_error
    try:
        body = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        body = None
    name = body.get("name") if isinstance(body, dict) else None
    if not isinstance(name, str):
        return JSONResponse(
            {
                "error": "invalid-view-name",
                "message": "name must be a string.",
            },
            status_code=400,
            headers=_NO_STORE,
        )
    try:
        validate_view_name(name)
    except MarimoStudioError as error:
        return JSONResponse(
            {"error": "invalid-view-name", "message": str(error)},
            status_code=400,
            headers=_NO_STORE,
        )
    if name in existing_views:
        return JSONResponse(
            {
                "error": "view-exists",
                "message": f"A view named {name!r} already exists.",
            },
            status_code=409,
            headers=_NO_STORE,
        )
    try:
        ensure_view(definition.notebook, name)
    except MarimoStudioError as error:
        return _error(error)
    return JSONResponse(
        {
            "schema": 1,
            "name": name,
            "studio_url": with_query(studio_url(base_url, name), routing_query),
            "view_url": with_query(view_url(base_url, name), routing_query),
        },
        status_code=201,
        headers=_NO_STORE,
    )


async def delete_view_response(
    request: Request,
    studio: StudioWorkspace,
    name: str,
    server_token: str,
) -> Response:
    """Delete a named view from an authenticated Studio workspace."""
    if request.method != "DELETE":
        return Response(status_code=405)
    if not has_edit_access(request.scope):
        return _forbidden()
    if token_error := _invalid_server_token(request, server_token):
        return token_error
    try:
        updated = delete_view(studio, name)
    except MarimoStudioError as error:
        return _error(error)
    return JSONResponse(
        {
            "schema": 1,
            "name": name,
            "default_view": updated.default_view,
            "views": list(updated.views),
        },
        headers=_NO_STORE,
    )


async def source_response(
    request: Request,
    studio: StudioWorkspace,
    view_name: str,
    name: str,
    server_token: str,
) -> Response:
    """Read or conditionally replace one authored view file."""
    if request.method == "GET":
        try:
            source = read_source(studio, view_name, name)
        except MarimoStudioError as error:
            return _error(error)
        return PlainTextResponse(
            source.content,
            media_type="text/plain",
            headers={**_NO_STORE, "ETag": f'"{source.revision}"'},
        )
    if request.method != "PUT":
        return Response(status_code=405)
    if not has_edit_access(request.scope):
        return _forbidden()
    if token_error := _invalid_server_token(request, server_token):
        return token_error
    expected = request.headers.get("If-Match")
    if expected is None:
        return JSONResponse(
            {
                "error": "source-revision-required",
                "message": "If-Match must contain the loaded source revision.",
            },
            status_code=428,
            headers=_NO_STORE,
        )
    expected = expected.removeprefix("W/").strip('"')
    try:
        content = (await request.body()).decode("utf-8")
    except UnicodeDecodeError:
        return JSONResponse(
            {
                "error": "invalid-source-encoding",
                "message": "Studio source files must be UTF-8 text.",
            },
            status_code=400,
            headers=_NO_STORE,
        )
    try:
        source = write_source(studio, view_name, name, content, expected)
    except SourceConflictError as error:
        return _error(error)
    except MarimoStudioError as error:
        return _error(error)
    return Response(
        status_code=204,
        headers={**_NO_STORE, "ETag": f'"{source.revision}"'},
    )


async def activate_view_response(
    request: Request,
    studio: StudioWorkspace,
    view_name: str,
    presentation: NotebookPresentation,
) -> Response:
    """Request that connected Studio workspaces select one view."""
    if request.method != "PATCH":
        return Response(status_code=405)
    if not has_edit_access(request.scope):
        return _forbidden()
    if view_name not in studio.views:
        return Response(status_code=404)
    activation = presentation.agent_state.activate(view_name)
    return JSONResponse(
        {
            "schema": 1,
            "notebook": str(studio.notebook),
            "view": view_name,
            "state": "requested",
            "generation": activation.generation,
        },
        status_code=202,
        headers=_NO_STORE,
    )


async def browser_observation_response(
    request: Request,
    studio: StudioWorkspace,
    view_name: str,
    presentation: NotebookPresentation,
    server_token: str,
) -> Response:
    """Record readiness reported by a rendered Studio preview."""
    if request.method != "PUT":
        return Response(status_code=405)
    if not has_edit_access(request.scope):
        return _forbidden()
    if token_error := _invalid_server_token(request, server_token):
        return token_error
    try:
        body = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        body = None
    observation = _parse_browser_observation(body, view_name)
    if observation is None:
        return JSONResponse(
            {
                "error": "invalid-browser-observation",
                "message": "The browser observation payload is invalid.",
            },
            status_code=400,
            headers=_NO_STORE,
        )
    presentation.agent_state.record(observation)
    return Response(status_code=204, headers=_NO_STORE)


def browser_observations_response(
    request: Request,
    studio: StudioWorkspace,
    presentation: NotebookPresentation,
) -> Response:
    """Return current rendered evidence for selected view revisions."""
    if request.method != "GET":
        return Response(status_code=405)
    requested = request.query_params.getlist("view")
    views = tuple(dict.fromkeys(requested)) if requested else tuple(studio.views)
    if any(view not in studio.views for view in views):
        return JSONResponse(
            {
                "error": "view-not-found",
                "message": "Every requested view must exist in this workspace.",
            },
            status_code=404,
            headers=_NO_STORE,
        )
    runtime = request.query_params.get("runtime") or studio.default_runtime
    observations: list[BrowserObservation] = []
    for view in views:
        current_revision = presentation.snapshot(view).revision
        observed = presentation.agent_state.observation(view, runtime)
        if observed is None:
            observations.append(
                BrowserObservation(
                    view=view,
                    runtime=runtime,
                    state="not-observed",
                    revision=current_revision,
                    message="No browser has reported this view revision.",
                )
            )
        elif observed.revision != current_revision:
            observations.append(
                BrowserObservation(
                    view=view,
                    runtime=runtime,
                    state="stale",
                    revision=current_revision,
                    message=(
                        "The browser observation belongs to an earlier view revision."
                    ),
                )
            )
        else:
            observations.append(observed)
    return JSONResponse(
        {
            "schema": 1,
            "notebook": str(studio.notebook),
            "observations": [item.to_dict() for item in observations],
        },
        headers=_NO_STORE,
    )


def _parse_browser_observation(
    value: object,
    view_name: str,
) -> BrowserObservation | None:
    if not isinstance(value, dict):
        return None
    runtime = value.get("runtime")
    revision = value.get("revision")
    state = value.get("state")
    diagnostics = value.get("diagnostics")
    if (
        not isinstance(runtime, str)
        or not runtime
        or not isinstance(revision, str)
        or not revision
        or state not in {"ready", "loading", "error"}
        or not isinstance(diagnostics, list)
        or len(diagnostics) > 200
    ):
        return None
    parsed: list[BrowserDiagnostic] = []
    for diagnostic in diagnostics:
        item = _parse_browser_diagnostic(diagnostic, view_name)
        if item is None:
            return None
        parsed.append(item)
    observed_state = (
        "error"
        if any(diagnostic.severity == "error" for diagnostic in parsed)
        else state
    )
    return BrowserObservation(
        view=view_name,
        runtime=runtime,
        revision=revision,
        state=cast(BrowserObservationState, observed_state),
        diagnostics=tuple(parsed),
    )


def _parse_browser_diagnostic(
    value: object,
    view_name: str,
) -> BrowserDiagnostic | None:
    if not isinstance(value, dict):
        return None
    code = value.get("code")
    severity = value.get("severity")
    message = value.get("message")
    hint = value.get("hint")
    reported_view = value.get("view")
    scope = value.get("scope", "projection")
    target = value.get("target")
    source = value.get("source")
    if (
        not isinstance(code, str)
        or not code
        or severity not in {"warning", "error"}
        or not isinstance(message, str)
        or not isinstance(hint, str)
        or reported_view != view_name
        or not isinstance(scope, str)
        or not scope
        or (target is not None and not isinstance(target, str))
        or not _valid_source(source)
    ):
        return None
    return BrowserDiagnostic(
        code=code,
        severity=cast(Literal["warning", "error"], severity),
        message=message,
        hint=hint,
        view=view_name,
        scope=scope,
        target=target,
        source=cast(dict[str, object] | None, source),
    )


def _valid_source(value: object) -> bool:
    if value is None:
        return True
    if not isinstance(value, dict):
        return False
    path = value.get("path")
    line = value.get("line")
    column = value.get("column")
    return isinstance(path, str) and isinstance(line, int) and isinstance(column, int)
