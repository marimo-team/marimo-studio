"""Deliver Studio event streams over WebSocket connections.

Browsers allow six HTTP/1.1 connections per host and port. Each Studio tab
and standalone view page holds its event stream open, so a stream that
occupied one of those connections would leave later tabs waiting for a socket.
WebSocket connections use a separate browser pool.

The WebSocket handshake follows the HTTP ``GET`` route policy of the event
route. The route answers with :class:`EventSocketResponse`, which accepts the
socket and sends one JSON text frame per event. Any other HTTP response
rejects the handshake: Studio accepts the socket and closes it with
``4000 + status``, because browsers hide the status of a refused handshake.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send
from starlette.websockets import WebSocket, WebSocketDisconnect, WebSocketState

from marimo_studio._delivery.urls import SUPPORT_PATH
from marimo_studio._processes.ownership import propagate_cancellation, settle_ownership
from marimo_studio._server.headers import NO_STORE
from marimo_studio._server.streaming import StreamingResponseCleanupError

EVENT_SOCKET_SCOPE_KEY = "marimo_studio.event_socket"
REJECTED_CLOSE_BASE = 4000
_EVENTS_SUFFIX = "/dev/events"
_INTERNAL_ERROR_CLOSE = 1011


def is_event_socket_route(relative: str) -> bool:
    """Return whether a Studio-relative path names an event stream."""
    return relative.startswith(SUPPORT_PATH) and relative.endswith(_EVENTS_SUFFIX)


async def serve_event_socket(
    dispatch: ASGIApp,
    scope: Scope,
    receive: Receive,
    send: Send,
) -> None:
    """Route one event socket handshake as an HTTP ``GET`` request."""
    socket = WebSocket(scope, receive, send)
    scheme = "https" if scope.get("scheme") == "wss" else "http"
    handshake: dict[str, object] = {
        **scope,
        "type": "http",
        "method": "GET",
        "scheme": scheme,
        EVENT_SOCKET_SCOPE_KEY: socket,
    }
    request_sent = False
    status = 500

    async def handshake_receive() -> Message:
        nonlocal request_sent
        if request_sent:
            return {"type": "http.disconnect"}
        request_sent = True
        return {"type": "http.request", "body": b"", "more_body": False}

    async def reject(message: Message) -> None:
        nonlocal status
        if message["type"] == "http.response.start":
            status = int(message["status"])
        elif message["type"] == "http.response.body" and not message.get(
            "more_body", False
        ):
            await _close(socket, REJECTED_CLOSE_BASE + status)

    try:
        await dispatch(handshake, handshake_receive, reject)
    finally:
        if socket.application_state == WebSocketState.CONNECTING:
            await _close(socket, REJECTED_CLOSE_BASE + status)


class EventSocketResponse(Response):
    """Send event frames to the socket that requested them."""

    def __init__(self, events: AsyncIterator[str]) -> None:
        super().__init__()
        self.events = events

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        socket = scope.get(EVENT_SOCKET_SCOPE_KEY)
        if not isinstance(socket, WebSocket):
            await self._close_events()
            await JSONResponse(
                {
                    "error": "websocket-required",
                    "message": "Studio event streams use WebSocket connections.",
                },
                status_code=426,
                headers={**NO_STORE, "Upgrade": "websocket"},
            )(scope, receive, send)
            return
        await socket.accept()
        deliver = asyncio.create_task(self._deliver(socket))
        disconnect = asyncio.create_task(_wait_for_disconnect(socket))
        observed: set[asyncio.Task[None]] = set()
        failed = False
        try:
            completed, _pending = await asyncio.wait(
                (deliver, disconnect),
                return_when=asyncio.FIRST_COMPLETED,
            )
            if deliver in completed:
                observed.add(deliver)
                await deliver
            if disconnect in completed:
                observed.add(disconnect)
                await disconnect
        except Exception:
            failed = True
            raise
        finally:
            deliver.cancel()
            disconnect.cancel()
            results, cancellation = await settle_ownership(
                asyncio.gather(deliver, disconnect, return_exceptions=True)
            )
            errors = tuple(
                result
                for task, result in zip((deliver, disconnect), results, strict=True)
                if task not in observed and isinstance(result, Exception)
            )
            if socket.client_state == WebSocketState.CONNECTED:
                await _close(
                    socket,
                    _INTERNAL_ERROR_CLOSE if failed or errors else 1000,
                )
            if errors:
                error = StreamingResponseCleanupError(errors)
                if cancellation is not None:
                    raise error from cancellation
                raise error
            propagate_cancellation(cancellation)

    async def _deliver(self, socket: WebSocket) -> None:
        try:
            async for frame in self.events:
                try:
                    await socket.send_text(frame)
                except (WebSocketDisconnect, OSError, RuntimeError):
                    return
        finally:
            await self._close_events()

    async def _close_events(self) -> None:
        close = getattr(self.events, "aclose", None)
        if close is not None:
            await close()


async def _wait_for_disconnect(socket: WebSocket) -> None:
    while (await socket.receive())["type"] != "websocket.disconnect":
        pass


async def _close(socket: WebSocket, code: int) -> None:
    try:
        if socket.application_state == WebSocketState.CONNECTING:
            await socket.accept()
        await socket.close(code)
    except (WebSocketDisconnect, OSError, RuntimeError):
        return
