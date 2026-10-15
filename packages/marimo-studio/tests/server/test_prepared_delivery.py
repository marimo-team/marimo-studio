from __future__ import annotations

import asyncio
import hashlib
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import marimo_export.prepared as prepared_module
import pytest
from marimo_export._prepared_integrity import ClosureMember
from marimo_export.prepared import PreparedAsset
from starlette.requests import Request
from starlette.types import Message

from marimo_studio._server.ready_handler import _send_artifact_response
from marimo_studio._server.zero_python_api import zero_python_response

from ..async_test_support import wait_for_event

_INSTANCE = "a" * 64
_RELATIVE = "assets/value.bin"


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


def _stored_asset(tmp_path: Path, content: bytes) -> tuple[Any, _Lease]:
    path = tmp_path / _RELATIVE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    lease = _Lease()
    asset = cast(Any, PreparedAsset)._create(
        path,
        lease,
        _RELATIVE,
        ClosureMember(
            sha256=hashlib.sha256(content).hexdigest(),
            size=len(content),
        ),
    )
    return asset, lease


class _Publications:
    def __init__(self, asset: Any) -> None:
        self._asset = asset

    async def publication_asset(self, *_args: object) -> Any:
        return self._asset


async def _response(
    tmp_path: Path,
    content: bytes,
    headers: list[tuple[bytes, bytes]] | None = None,
) -> tuple[Any, _Lease]:
    asset, lease = _stored_asset(tmp_path, content)
    response = await zero_python_response(
        Request(_scope(headers)),
        cast(Any, _Publications(asset)),
        "dashboard",
        f"{_INSTANCE}/{_RELATIVE}",
        clients=cast(Any, SimpleNamespace()),
        allow_refresh=False,
    )
    return response, lease


async def _never() -> Message:
    await asyncio.Future()
    raise AssertionError("unreachable")


@pytest.mark.parametrize(
    "exit_path",
    ["start-disconnect", "body-disconnect", "cancelled-body", "rejected-range"],
    ids=["start-disconnect", "body-disconnect", "cancelled-body", "rejected-range"],
)
def test_prepared_download_releases_its_lease_on_every_exit(
    tmp_path: Path,
    exit_path: str,
) -> None:
    async def exercise() -> None:
        rejected = exit_path == "rejected-range"
        headers = [(b"range", b"bytes=999-1000")] if rejected else None
        content = b"x" * 131072 if exit_path == "cancelled-body" else b"value"
        response, lease = await _response(tmp_path, content, headers)
        statuses: list[int] = []
        sending = asyncio.Event()

        async def send(message: Message) -> None:
            kind = message["type"]
            if kind == "http.response.start":
                statuses.append(message["status"])
            if exit_path == "start-disconnect" and kind == "http.response.start":
                raise OSError("peer disconnected")
            if exit_path == "body-disconnect" and kind == "http.response.body":
                raise OSError("peer disconnected")
            if exit_path == "cancelled-body" and kind == "http.response.body":
                sending.set()
                await asyncio.Future()

        scope = _scope(headers)
        serving = _send_artifact_response(response, scope, _never, send)
        if exit_path == "cancelled-body":
            task = asyncio.create_task(serving)
            await wait_for_event(sending, timeout=2)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        elif rejected:
            await serving
            assert statuses == [416]
        else:
            with pytest.raises(OSError, match="peer disconnected"):
                await serving
        assert lease.closed

    asyncio.run(exercise())


def test_cancelling_during_verification_keeps_the_event_loop_running(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entered = threading.Event()
    release = threading.Event()
    verify = prepared_module.verify_member

    def slow_verify(*args: Any) -> Any:
        entered.set()
        assert release.wait(5)
        return verify(*args)

    async def exercise() -> None:
        asset, lease = _stored_asset(tmp_path, b"value")
        monkeypatch.setattr(prepared_module, "verify_member", slow_verify)
        serving = asyncio.create_task(
            zero_python_response(
                Request(_scope()),
                cast(Any, _Publications(asset)),
                "dashboard",
                f"{_INSTANCE}/{_RELATIVE}",
                clients=cast(Any, SimpleNamespace()),
                allow_refresh=False,
            )
        )
        await asyncio.to_thread(entered.wait, 2)
        serving.cancel()
        # close() waits on the lock verification still holds, so a second
        # thread has to see that the event loop still runs.
        loop_ran = threading.Event()
        frozen = threading.Event()

        def watch_loop() -> None:
            if not loop_ran.wait(5):
                frozen.set()
            release.set()

        asyncio.get_running_loop().call_soon(loop_ran.set)
        try:
            await asyncio.to_thread(watch_loop)
            with pytest.raises(asyncio.CancelledError):
                await serving
        finally:
            release.set()
        assert not frozen.is_set()
        assert lease.closed

    asyncio.run(exercise())
