"""Serve current zero-Python metadata and immutable export generations."""

from __future__ import annotations

import mimetypes
import re
from collections.abc import Callable
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from marimo_export.errors import MarimoExportError
from marimo_export.manifest import (
    PreparedManifestLimitError,
    prepared_manifest_bytes,
)
from starlette.background import BackgroundTask
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response

from marimo_studio._delivery.urls import STUDIO_CLIENT_QUERY_PARAM
from marimo_studio._server.agent.clients import StudioClientRegistry
from marimo_studio._server.client_identity import parse_studio_client_id
from marimo_studio._server.headers import NO_STORE
from marimo_studio._server.prepared_views import PreparedViewRegistry
from marimo_studio.errors import PublicationError, PublicationLimitError

_INSTANCE = re.compile(r"[0-9a-f]{64}")
_REVISION = re.compile(r"[0-9a-f]{64}")


async def zero_python_response(
    request: Request,
    publications: PreparedViewRegistry,
    view: str,
    route: str,
    *,
    clients: StudioClientRegistry,
    allow_refresh: bool,
    public_path: str | None = None,
) -> Response:
    if request.method not in {"GET", "HEAD"}:
        return Response(status_code=405)
    if route == "current":
        raw_client_id = request.query_params.get(STUDIO_CLIENT_QUERY_PARAM)
        client_id = parse_studio_client_id(raw_client_id)
        if raw_client_id is not None and client_id is None:
            return _invalid_binding()
        if client_id is None:
            return _publication_unavailable()
        revision = request.query_params.get("revision")
        if revision is None or _REVISION.fullmatch(revision) is None:
            return _invalid_revision()
        binding_id = await clients.session_for_client(client_id)
        if binding_id is None:
            return _publication_unavailable()
        selection = (
            publications.poll_current(view, binding_id, revision)
            if allow_refresh
            else publications.current(view, binding_id, revision)
        )
        if selection is None:
            return _publication_unavailable()
        current = urlsplit(str(request.url))
        current_path = public_path or current.path
        export_query = urlencode(
            [
                (name, value)
                for name, value in parse_qsl(
                    current.query,
                    keep_blank_values=True,
                )
                if name not in {STUDIO_CLIENT_QUERY_PARAM, "revision"}
            ]
        )
        export_url = urlunsplit(
            (
                current.scheme,
                current.netloc,
                f"{current_path.removesuffix('/current')}/{selection.instance}/",
                export_query,
                "",
            )
        )
        try:
            manifest = prepared_manifest_bytes(selection.manifest(export_url))
        except PreparedManifestLimitError as error:
            raise PublicationLimitError(str(error)) from error
        except MarimoExportError as error:
            raise PublicationError(str(error)) from error
        return Response(
            manifest,
            media_type="application/json",
            headers=NO_STORE,
        )

    instance, separator, relative = route.partition("/")
    if not separator or _INSTANCE.fullmatch(instance) is None or not relative:
        return Response(status_code=404)
    asset = await publications.publication_asset(
        view,
        instance,
        relative,
    )
    if asset is None:
        return Response(status_code=404)
    try:
        return _immutable_file(asset.path, asset.close)
    except BaseException:
        asset.close()
        raise


def _immutable_file(candidate: Path, release: Callable[[], None]) -> Response:
    if not candidate.is_file():
        release()
        return Response(status_code=404)
    media_type = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
    try:
        return FileResponse(
            candidate,
            media_type=media_type,
            headers={"Cache-Control": "private, max-age=31536000, immutable"},
            background=BackgroundTask(release),
        )
    except BaseException:
        release()
        raise


def _publication_unavailable() -> JSONResponse:
    return JSONResponse(
        {
            "error": "zero-python-publication-unavailable",
            "message": "The prepared notebook export is still being created.",
            "transient": True,
        },
        status_code=409,
        headers=NO_STORE,
    )


def _invalid_binding() -> JSONResponse:
    return JSONResponse(
        {
            "error": "invalid-browser-client",
            "message": "The Studio browser client identifier is invalid.",
        },
        status_code=400,
        headers=NO_STORE,
    )


def _invalid_revision() -> JSONResponse:
    return JSONResponse(
        {
            "error": "invalid-presentation-revision",
            "message": "The zero-Python manifest revision is invalid.",
        },
        status_code=400,
        headers=NO_STORE,
    )


__all__ = ["zero_python_response"]
