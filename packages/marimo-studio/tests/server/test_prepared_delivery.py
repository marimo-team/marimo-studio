"""Release Prepared asset leases on every response exit."""

from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from marimo_export._prepared_integrity import ClosureMember
from marimo_export.prepared import PreparedAsset
from starlette.requests import Request
from starlette.types import Message

from marimo_studio._server.ready_handler import _send_artifact_response
from marimo_studio._server.zero_python_api import zero_python_response

_INSTANCE = "a" * 64


class _Lease:
    def __init__(self) -> None:
        self.closed = False

    @property
    def alive(self) -> bool:
        return not self.closed

    def renew(self) -> bool:
        return not self.closed

    def close(self) -> None:
        self.closed = True


def _scope(headers: list[tuple[bytes, bytes]] | None = None) -> dict[str, Any]:
    return {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.4"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": f"/_marimo-studio/views/dashboard/zero-python/{_INSTANCE}/value.bin",
        "raw_path": b"/",
        "query_string": b"",
        "root_path": "",
        "headers": headers or [],
        "server": ("testserver", 80),
        "client": ("testclient", 123),
    }


async def _response(
    tmp_path: Path,
    content: bytes,
    headers: list[tuple[bytes, bytes]] | None = None,
) -> tuple[Any, _Lease]:
    path = tmp_path / "assets" / "value.bin"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    lease = _Lease()
    member = ClosureMember(
        sha256=hashlib.sha256(content).hexdigest(), size=len(content)
    )
    asset = cast(Any, PreparedAsset)._create(path, lease, "assets/value.bin", member)

    class Publications:
        async def publication_asset(self, *_args: object) -> PreparedAsset:
            return asset

    response = await zero_python_response(
        Request(_scope(headers)),
        cast(Any, Publications()),
        "dashboard",
        f"{_INSTANCE}/assets/value.bin",
        clients=cast(Any, SimpleNamespace()),
        allow_refresh=False,
    )
    return response, lease


async def _never() -> Message:
    await asyncio.Future()
    raise AssertionError("unreachable")


@pytest.mark.parametrize("failure_at", ["http.response.start", "http.response.body"])
def test_a_failed_prepared_download_releases_its_lease(
    tmp_path: Path, failure_at: str
) -> None:
    async def exercise() -> bool:
        response, lease = await _response(tmp_path, b"value")

        async def send(message: Message) -> None:
            if message["type"] == failure_at:
                raise OSError("peer disconnected")

        with pytest.raises(OSError, match="peer disconnected"):
            await _send_artifact_response(response, _scope(), _never, send)
        return lease.closed

    assert asyncio.run(exercise()) is True


def test_a_cancelled_prepared_download_releases_its_lease(tmp_path: Path) -> None:
    async def exercise() -> bool:
        response, lease = await _response(tmp_path, b"x" * 131072)
        sending = asyncio.Event()

        async def send(message: Message) -> None:
            if message["type"] == "http.response.body":
                sending.set()
                await asyncio.Future()

        serving = asyncio.create_task(
            _send_artifact_response(response, _scope(), _never, send)
        )
        await asyncio.wait_for(sending.wait(), timeout=2)
        serving.cancel()
        with pytest.raises(asyncio.CancelledError):
            await serving
        return lease.closed

    assert asyncio.run(exercise()) is True


def test_a_rejected_range_releases_its_lease(tmp_path: Path) -> None:
    async def exercise() -> tuple[list[int], bool]:
        headers = [(b"range", b"bytes=999-1000")]
        response, lease = await _response(tmp_path, b"value", headers)
        statuses: list[int] = []

        async def send(message: Message) -> None:
            if message["type"] == "http.response.start":
                statuses.append(message["status"])

        await _send_artifact_response(response, _scope(headers), _never, send)
        return statuses, lease.closed

    assert asyncio.run(exercise()) == ([416], True)
