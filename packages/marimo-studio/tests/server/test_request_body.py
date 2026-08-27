from __future__ import annotations

import asyncio
import json
from collections.abc import Callable

import pytest
from starlette.authentication import AuthCredentials
from starlette.requests import Request
from starlette.types import Message, Scope

from marimo_studio._server.request_body import (
    InvalidJSONBody,
    JSONBodyDisconnected,
    JSONBodyTooLarge,
    json_body_error_response,
    read_json_body,
)
from marimo_studio._server.studio.routes import create_view_response
from marimo_studio._views.api import ensure_view
from marimo_studio._workspace.config import load_studio_definition


def _request(
    chunks: tuple[bytes, ...],
    *,
    content_lengths: tuple[str, ...] = (),
    disconnect: bool = False,
    extra_headers: tuple[tuple[bytes, bytes], ...] = (),
    edit: bool = False,
) -> tuple[Request, Callable[[], int]]:
    messages: list[Message] = (
        [
            {"type": "http.request", "body": b"", "more_body": True},
            {"type": "http.disconnect"},
        ]
        if disconnect
        else [
            {
                "type": "http.request",
                "body": chunk,
                "more_body": index < len(chunks) - 1,
            }
            for index, chunk in enumerate(chunks)
        ]
    )
    calls = 0

    async def receive() -> Message:
        nonlocal calls
        calls += 1
        if not messages:
            raise AssertionError("The JSON reader consumed past the terminal chunk")
        return messages.pop(0)

    headers = [(b"content-length", value.encode()) for value in content_lengths]
    headers.extend(extra_headers)
    scope: Scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/",
        "raw_path": b"/",
        "query_string": b"",
        "root_path": "",
        "headers": headers,
        "client": ("test", 1),
        "server": ("test", 80),
    }
    if edit:
        scope["auth"] = AuthCredentials(["edit"])
    return Request(scope, receive), lambda: calls


def test_json_reader_rejects_declared_oversize_before_receiving() -> None:
    request, receive_calls = _request((b"{}",), content_lengths=("9",))

    with pytest.raises(JSONBodyTooLarge):
        asyncio.run(read_json_body(request, max_bytes=8))

    assert receive_calls() == 0


def test_json_reader_stops_an_oversized_chunked_body_at_the_budget() -> None:
    request, receive_calls = _request((b'{"ok":', b"true}", b"ignored"))

    with pytest.raises(JSONBodyTooLarge):
        asyncio.run(read_json_body(request, max_bytes=8))

    assert receive_calls() == 2


@pytest.mark.parametrize("payload", (b"\xff", b'{"missing":'))
def test_json_reader_rejects_malformed_utf8_and_json(payload: bytes) -> None:
    request, _receive_calls = _request((payload,))

    with pytest.raises(InvalidJSONBody):
        asyncio.run(read_json_body(request, max_bytes=64))


def test_json_reader_accepts_a_valid_body_at_the_exact_limit() -> None:
    payload = b'{"ok":true}'
    request, _receive_calls = _request(
        (b'{"ok":', b"true}"),
        content_lengths=(str(len(payload)),),
    )

    parsed = asyncio.run(read_json_body(request, max_bytes=len(payload)))

    assert parsed == {"ok": True}


def test_json_reader_maps_a_short_declared_body_to_disconnect() -> None:
    request, receive_calls = _request(
        (b"{}",),
        content_lengths=("3",),
    )

    with pytest.raises(JSONBodyDisconnected) as captured:
        asyncio.run(read_json_body(request, max_bytes=8))

    assert receive_calls() == 1
    assert json_body_error_response(captured.value).status_code == 499


def test_json_reader_rejects_bytes_past_the_declared_length_immediately() -> None:
    request, receive_calls = _request(
        (b"{}", b"ignored"),
        content_lengths=("1",),
    )

    with pytest.raises(InvalidJSONBody):
        asyncio.run(read_json_body(request, max_bytes=64))

    assert receive_calls() == 1


@pytest.mark.parametrize("content_lengths", (("2", "2"), ("2", "3")))
def test_json_reader_rejects_ambiguous_content_length_declarations(
    content_lengths: tuple[str, ...],
) -> None:
    request, receive_calls = _request(
        (b"{}",),
        content_lengths=content_lengths,
    )

    with pytest.raises(InvalidJSONBody):
        asyncio.run(read_json_body(request, max_bytes=64))

    assert receive_calls() == 0


def test_json_reader_maps_client_disconnect_to_a_terminal_response() -> None:
    request, receive_calls = _request((), disconnect=True)

    with pytest.raises(JSONBodyDisconnected) as captured:
        asyncio.run(read_json_body(request, max_bytes=64))

    assert receive_calls() == 2
    assert json_body_error_response(captured.value).status_code == 499


@pytest.mark.parametrize(
    ("declared_delta", "expected_status"),
    ((1, 499), (-1, 400)),
    ids=("short", "long"),
)
def test_view_creation_rejects_mismatched_body_length_without_mutation(
    notebook_path,
    declared_delta: int,
    expected_status: int,
) -> None:
    ensure_view(notebook_path)
    definition = load_studio_definition(notebook_path)
    payload = b'{"name":"operations"}'
    request, receive_calls = _request(
        (payload,),
        content_lengths=(str(len(payload) + declared_delta),),
        extra_headers=((b"marimo-server-token", b"server-token"),),
        edit=True,
    )

    response = asyncio.run(
        create_view_response(
            request,
            definition,
            "server-token",
        )
    )

    assert response.status_code == expected_status
    assert receive_calls() == 1
    assert not (definition.view_root / "operations").exists()


def test_json_body_errors_have_one_shared_http_contract() -> None:
    invalid = json_body_error_response(InvalidJSONBody())
    oversized = json_body_error_response(JSONBodyTooLarge())

    assert invalid.status_code == 400
    assert json.loads(bytes(invalid.body))["error"] == "invalid-json"
    assert oversized.status_code == 413
    assert json.loads(bytes(oversized.body))["error"] == "request-body-too-large"
