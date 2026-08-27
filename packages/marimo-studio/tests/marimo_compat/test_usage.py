from __future__ import annotations

import asyncio
import json
from typing import cast

import pytest
from psutil import AccessDenied, NoSuchProcess
from starlette.types import Message, Receive, Scope, Send

from marimo_studio._compat.server.usage import _usage_route, _wrap_usage_app
from marimo_studio._composition import create_server_adapters


def _scope() -> Scope:
    return {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/api/usage",
        "raw_path": b"/api/usage",
        "query_string": b"",
        "root_path": "",
        "headers": [],
        "client": ("test", 1),
        "server": ("test", 80),
    }


async def _receive() -> Message:
    return {"type": "http.request", "body": b"", "more_body": False}


@pytest.mark.parametrize(
    "error",
    (NoSuchProcess(42), AccessDenied(42)),
    ids=("missing", "denied"),
)
def test_usage_process_sample_unavailable_returns_an_unavailable_snapshot(
    error: Exception,
) -> None:
    async def unavailable(_scope: Scope, _receive: Receive, _send: Send) -> None:
        raise error

    messages: list[Message] = []

    async def send(message: Message) -> None:
        messages.append(message)

    async def run() -> None:
        await _wrap_usage_app(unavailable)(_scope(), _receive, send)

    asyncio.run(run())

    assert messages[0]["type"] == "http.response.start"
    assert messages[0]["status"] == 200
    assert json.loads(cast(bytes, messages[1]["body"])) == {
        "memory": {
            "total": None,
            "available": None,
            "percent": None,
            "used": None,
            "free": None,
            "has_cgroup_mem_limit": False,
        },
        "server": {"memory": None},
        "kernel": {"memory": None},
        "cpu": {"percent": None},
        "gpu": [],
    }


def test_usage_adapter_propagates_unrelated_failures() -> None:
    async def failed(_scope: Scope, _receive: Receive, _send: Send) -> None:
        raise RuntimeError("usage failed")

    async def send(_message: Message) -> None:
        raise AssertionError("The failed usage request cannot send a response")

    async def run() -> None:
        await _wrap_usage_app(failed)(_scope(), _receive, send)

    with pytest.raises(RuntimeError, match="usage failed"):
        asyncio.run(run())


@pytest.mark.parametrize(
    "error",
    (NoSuchProcess(42), AccessDenied(42)),
    ids=("missing", "denied"),
)
def test_usage_process_sample_unavailable_after_headers_propagates(
    error: Exception,
) -> None:
    async def unavailable(scope: Scope, receive: Receive, send: Send) -> None:
        await send({"type": "http.response.start", "status": 200, "headers": []})
        raise error

    async def send(_message: Message) -> None:
        return

    async def run() -> None:
        await _wrap_usage_app(unavailable)(_scope(), _receive, send)

    with pytest.raises(type(error)):
        asyncio.run(run())


def test_server_lifecycles_reference_count_and_restore_the_usage_route() -> None:
    route = _usage_route()
    original = route.app
    first = create_server_adapters().lifecycle.open()
    replacement = route.app
    second = create_server_adapters().lifecycle.open()

    try:
        assert replacement is not original
        first.close()
        assert route.app is replacement
        second.close()
        assert route.app is original
    finally:
        first.close()
        second.close()
