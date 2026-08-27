from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Iterator
from typing import Any, cast

import pytest
from starlette.requests import Request

from marimo_studio._delivery.urls import PRIVATE_QUERY_KEYS
from marimo_studio._server.presentation.access import send_capability_app
from marimo_studio._server.presentation.isolation import isolated_presentation_document
from marimo_studio._server.presentation.ownership import studio_owned_request


def test_presentation_client_disconnect_finishes_native_delegation() -> None:
    sent: list[dict[str, object]] = []
    request_message: dict[str, object] = {
        "type": "http.request",
        "body": b"{",
        "more_body": True,
    }
    disconnect_message: dict[str, object] = {"type": "http.disconnect"}
    messages: Iterator[dict[str, object]] = iter((request_message, disconnect_message))

    async def disconnected(
        scope: object,
        receive: object,
        _send: object,
    ) -> None:
        await Request(cast(Any, scope), cast(Any, receive)).body()

    async def receive() -> dict[str, object]:
        return next(messages)

    async def send(message: dict[str, object]) -> None:
        sent.append(message)

    asyncio.run(
        send_capability_app(
            cast(Any, disconnected),
            cast(Any, {"type": "http"}),
            cast(Any, receive),
            cast(Any, send),
        )
    )

    assert [message["type"] for message in sent] == [
        "http.response.start",
        "http.response.body",
    ]
    assert sent[0]["status"] == 499


def test_presentation_delegation_propagates_application_failures() -> None:
    async def broken(_scope: object, _receive: object, _send: object) -> None:
        raise RuntimeError("delegate failed")

    async def receive() -> dict[str, object]:
        return {"type": "http.disconnect"}

    async def send(_message: dict[str, object]) -> None:
        return None

    with pytest.raises(RuntimeError, match="delegate failed"):
        asyncio.run(
            send_capability_app(
                cast(Any, broken),
                cast(Any, {"type": "http"}),
                cast(Any, receive),
                cast(Any, send),
            )
        )


def test_presentation_delegation_sandboxes_navigable_native_responses() -> None:
    sent: list[dict[str, object]] = []

    async def document(_scope: object, _receive: object, send: object) -> None:
        await cast(Any, send)(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [
                    (b"content-type", b"text/html"),
                    (
                        b"content-security-policy",
                        b"sandbox allow-same-origin allow-scripts",
                    ),
                ],
            }
        )
        await cast(Any, send)({"type": "http.response.body", "body": b"<html></html>"})

    async def receive() -> dict[str, object]:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict[str, object]) -> None:
        sent.append(message)

    asyncio.run(
        send_capability_app(
            cast(Any, document),
            cast(Any, {"type": "http"}),
            cast(Any, receive),
            cast(Any, send),
        )
    )

    headers = dict(cast(list[tuple[bytes, bytes]], sent[0]["headers"]))
    sandbox_policy = headers[b"content-security-policy"].decode().split()
    assert sandbox_policy[0] == "sandbox"
    assert "allow-same-origin" not in sandbox_policy[1:]


def test_presentation_websocket_close_ignores_a_closed_transport() -> None:
    async def close(_scope: object, _receive: object, send: object) -> None:
        await cast(Any, send)({"type": "websocket.close", "code": 1000})

    async def receive() -> dict[str, object]:
        return {"type": "websocket.disconnect", "code": 1006}

    async def disconnected_send(_message: dict[str, object]) -> None:
        raise OSError("transport closed")

    asyncio.run(
        send_capability_app(
            cast(Any, close),
            cast(Any, {"type": "websocket"}),
            cast(Any, receive),
            cast(Any, disconnected_send),
        )
    )


def test_isolated_presentation_binds_navigation_to_server_configuration() -> None:
    document = isolated_presentation_document(
        child_url="/_marimo-studio/presentation/token/dashboard/",
        internal_root_url="/_marimo-studio/presentation/token/",
        public_root_url="/base/",
        routing_query="file=notebook.py",
        view_name="dashboard",
        views=("dashboard", "report"),
        private_query_keys=tuple(sorted(PRIVATE_QUERY_KEYS)),
        runtime="server",
        runtime_explicit=False,
        title_text="Dashboard",
        nonce="test-nonce",
    )
    encoded = re.search(r"const config = Object\.freeze\((\{[^\n]+\})\);", document)

    assert encoded is not None
    assert json.loads(encoded.group(1)) == {
        "internalRootUrl": "/_marimo-studio/presentation/token/",
        "publicRootUrl": "/base/",
        "routingQuery": "file=notebook.py",
        "view": "dashboard",
        "views": ["dashboard", "report"],
        "privateQueryKeys": sorted(PRIVATE_QUERY_KEYS),
        "fallbackUrl": "/_marimo-studio/presentation/token/dashboard/",
        "replayPathPrefix": "/base/_marimo-studio/presentation/d.",
        "replayEnabled": False,
        "replayScope": None,
        "runtime": "server",
        "runtimeExplicit": False,
    }
    assert (
        'id="marimo-studio-presentation" '
        'src="/_marimo-studio/presentation/token/dashboard/"'
    ) in document


def test_preserved_session_wrapper_creates_its_frame_after_replay_admission() -> None:
    document = isolated_presentation_document(
        child_url="/_marimo-studio/presentation/token/dashboard/",
        internal_root_url="/_marimo-studio/presentation/token/",
        public_root_url="/base/",
        routing_query="file=notebook.py",
        view_name="dashboard",
        views=("dashboard",),
        private_query_keys=tuple(sorted(PRIVATE_QUERY_KEYS)),
        runtime="server",
        runtime_explicit=True,
        replay_enabled=True,
        replay_scope="replay-scope",
        title_text="Dashboard",
        nonce="test-nonce",
    )

    assert "<iframe" not in document
    assert 'data-marimo-studio-frame-blueprint=""' in document
    assert 'data-frame-sandbox="allow-downloads allow-forms allow-modals ' in document

    encoded = re.search(r"const config = Object\.freeze\((\{[^\n]+\})\);", document)
    assert encoded is not None
    config = json.loads(encoded.group(1))
    assert config["runtime"] == "server"
    assert config["runtimeExplicit"] is True


@pytest.mark.parametrize(
    ("query", "expected"),
    (
        ("marimo_studio_client=client-123456", False),
        (
            "marimo_studio_client=client-123456&marimo_studio_lifecycle=7",
            True,
        ),
        (
            "marimo_studio_client=client-123456&marimo_studio_lifecycle=0",
            False,
        ),
        (
            "marimo_studio_client=client-123456&marimo_studio_lifecycle="
            "9007199254740992",
            False,
        ),
        (
            "marimo_studio_client=client-123456&marimo_studio_client=other"
            "&marimo_studio_lifecycle=7",
            False,
        ),
        (
            "marimo_studio_client=client-123456&marimo_studio_lifecycle=7"
            "&marimo_studio_lifecycle=8",
            False,
        ),
    ),
)
def test_studio_frame_ownership_requires_a_bounded_lifecycle(
    query: str,
    expected: bool,
) -> None:
    request = Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": "/dashboard/",
            "raw_path": b"/dashboard/",
            "query_string": query.encode(),
            "headers": [],
            "client": ("test", 123),
            "server": ("test", 80),
        }
    )

    assert studio_owned_request(request) is expected
