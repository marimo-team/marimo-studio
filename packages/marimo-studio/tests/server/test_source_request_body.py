"""Protect the source upload boundary before filesystem mutation begins."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import cast

from starlette.authentication import AuthCredentials
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import Message, Scope

from marimo_studio._server.development.coordinator import DevelopmentCoordinator
from marimo_studio._server.studio.routes import source_response
from marimo_studio._workspace.models import StudioWorkspace

from ..app_helpers import configured


def _request(
    messages: list[Message],
    content_length: str,
    studio: StudioWorkspace,
) -> tuple[Request, Callable[[], int]]:
    calls = 0

    async def receive() -> Message:
        nonlocal calls
        calls += 1
        if not messages:
            raise AssertionError(
                "The source reader consumed past the terminal body event"
            )
        return messages.pop(0)

    scope: Scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "PUT",
        "scheme": "http",
        "path": "/_marimo-studio/views/dashboard/source/index.html",
        "raw_path": b"/_marimo-studio/views/dashboard/source/index.html",
        "query_string": b"",
        "root_path": "",
        "headers": [
            (b"content-length", content_length.encode()),
            (b"if-match", b"sha256:loaded"),
            (b"marimo-server-token", b"server-token"),
            (
                b"marimo-studio-catalog-generation",
                studio.catalog_generation.encode(),
            ),
            (
                b"marimo-studio-view-generation",
                studio.view_generations["dashboard"].encode(),
            ),
        ],
        "client": ("test", 1),
        "server": ("test", 80),
        "auth": AuthCredentials(["edit"]),
    }
    return Request(scope, receive), lambda: calls


def _source_response(request: Request, studio: StudioWorkspace) -> Response:
    return asyncio.run(
        source_response(
            request,
            studio,
            "dashboard",
            "index.html",
            "server-token",
            cast(DevelopmentCoordinator, object()),
        )
    )


def test_partial_source_disconnect_returns_499_without_mutation(
    notebook_path,
) -> None:
    studio = configured(notebook_path)
    source = studio.views["dashboard"].root / "index.html"
    original = source.read_bytes()
    request, receive_calls = _request(
        [
            {"type": "http.request", "body": b"partial", "more_body": True},
            {"type": "http.disconnect"},
        ],
        "100",
        studio,
    )

    response = _source_response(request, studio)

    assert response.status_code == 499
    assert receive_calls() == 2
    assert source.read_bytes() == original


def test_source_body_longer_than_declared_is_rejected_without_mutation(
    notebook_path,
) -> None:
    studio = configured(notebook_path)
    source = studio.views["dashboard"].root / "index.html"
    original = source.read_bytes()
    request, receive_calls = _request(
        [{"type": "http.request", "body": b"too long", "more_body": False}],
        "3",
        studio,
    )

    response = _source_response(request, studio)

    assert response.status_code == 400
    assert receive_calls() == 1
    assert source.read_bytes() == original


def test_source_upload_rejects_invalid_content_length_before_receiving(
    notebook_path,
) -> None:
    studio = configured(notebook_path)
    source = studio.views["dashboard"].root / "index.html"
    original = source.read_bytes()

    request, receive_calls = _request([], "invalid", studio)
    response = _source_response(request, studio)

    assert response.status_code == 400
    assert receive_calls() == 0
    assert source.read_bytes() == original
