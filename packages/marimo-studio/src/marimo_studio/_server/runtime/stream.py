"""Deliver one runtime configuration with request-owned progress."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from threading import Lock

from starlette.responses import Response

from marimo_studio._processes.ownership import propagate_cancellation, settle_ownership
from marimo_studio._server.auth import error_response
from marimo_studio._server.headers import NO_STORE
from marimo_studio._server.runtime.progress import RuntimeProgress, RuntimeProgressSink
from marimo_studio._server.streaming import OwnedStreamingResponse
from marimo_studio.errors import MarimoStudioError

_LOGGER = logging.getLogger(__name__)
RUNTIME_STREAM_MEDIA_TYPE = "application/x-ndjson"


class _ProgressMailbox:
    def __init__(self, ready: asyncio.Event) -> None:
        self._lock = Lock()
        self._loop: asyncio.AbstractEventLoop | None = asyncio.get_running_loop()
        self._latest: RuntimeProgress | None = None
        self._scheduled = False
        self._ready: asyncio.Event | None = ready

    def __call__(self, progress: RuntimeProgress) -> None:
        with self._lock:
            if self._loop is None:
                return
            self._latest = progress
            if not self._scheduled:
                self._scheduled = True
                self._loop.call_soon_threadsafe(self._wake)

    def _wake(self) -> None:
        with self._lock:
            self._scheduled = False
            if self._ready is not None:
                self._ready.set()

    def take(self) -> RuntimeProgress | None:
        with self._lock:
            latest, self._latest = self._latest, None
            return latest

    def close(self) -> None:
        # Publication refreshes may retain the sink after this request finishes.
        with self._lock:
            self._loop = None
            self._ready = None
            self._latest = None


def runtime_config_stream(
    operation: Callable[[RuntimeProgressSink], Awaitable[Response]],
) -> OwnedStreamingResponse:
    return OwnedStreamingResponse(
        _events(operation),
        media_type=RUNTIME_STREAM_MEDIA_TYPE,
        headers={**NO_STORE, "X-Accel-Buffering": "no"},
    )


async def _events(
    operation: Callable[[RuntimeProgressSink], Awaitable[Response]],
) -> AsyncIterator[bytes]:
    ready = asyncio.Event()
    mailbox = _ProgressMailbox(ready)
    task = asyncio.ensure_future(operation(mailbox))
    task.add_done_callback(lambda _task: ready.set())
    observed = False
    try:
        while True:
            await ready.wait()
            ready.clear()
            progress = mailbox.take()
            if progress is not None:
                yield _encode({"type": "progress", "progress": progress.to_dict()})
            if task.done():
                break
        observed = True
        if task.cancelled():
            yield _encode(
                {
                    "type": "error",
                    "error": "runtime-sync-pending",
                    "message": (
                        "Runtime preparation changed. Retrying the current state."
                    ),
                    "transient": True,
                }
            )
            return
        try:
            response = task.result()
        except MarimoStudioError as error:
            response = error_response(error)
        except Exception:
            _LOGGER.exception("Runtime configuration failed during streaming")
            yield _encode(
                {
                    "type": "error",
                    "error": "runtime-config-failed",
                    "message": "The runtime could not start.",
                    "hint": "Check the server logs, then retry the preview.",
                }
            )
            return
        yield await asyncio.to_thread(_response_event, response)
    finally:
        mailbox.close()
        if not task.done():
            task.cancel()
        results, cancellation = await settle_ownership(
            asyncio.gather(task, return_exceptions=True)
        )
        if not observed and isinstance(results[0], Exception):
            raise results[0]
        propagate_cancellation(cancellation)


def _response_event(response: Response) -> bytes:
    payload = json.loads(bytes(response.body))
    if response.status_code >= 400:
        return _encode({**payload, "type": "error"})
    return _encode({"type": "config", "config": payload})


def _encode(payload: dict[str, object]) -> bytes:
    return (
        json.dumps(payload, separators=(",", ":"), ensure_ascii=False) + "\n"
    ).encode()
