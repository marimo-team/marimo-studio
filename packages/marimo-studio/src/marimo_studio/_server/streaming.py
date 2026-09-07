"""Close streaming response owners when delivery ends."""

from __future__ import annotations

import asyncio

from starlette.responses import StreamingResponse
from starlette.types import Receive, Scope, Send

from marimo_studio._processes.ownership import propagate_cancellation, settle_ownership


class StreamingResponseCleanupError(RuntimeError):
    """Report a body-owner failure observed during response teardown."""

    def __init__(self, errors: tuple[Exception, ...]) -> None:
        self.errors = errors
        super().__init__(
            "Streaming response cleanup failed: "
            + ", ".join(str(error) for error in errors)
        )


class OwnedStreamingResponse(StreamingResponse):
    """Close an async body iterator whenever response delivery ends."""

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        stream = asyncio.create_task(self.stream_response(send))
        disconnect = asyncio.create_task(self.listen_for_disconnect(receive))
        observed: set[asyncio.Task[None]] = set()
        try:
            completed, _pending = await asyncio.wait(
                (stream, disconnect),
                return_when=asyncio.FIRST_COMPLETED,
            )
            if stream in completed:
                observed.add(stream)
                await stream
            if disconnect in completed:
                observed.add(disconnect)
                await disconnect
        finally:
            stream.cancel()
            disconnect.cancel()
            results, cancellation = await settle_ownership(
                asyncio.gather(stream, disconnect, return_exceptions=True)
            )
            errors = tuple(
                result
                for task, result in zip(
                    (stream, disconnect),
                    results,
                    strict=True,
                )
                if task not in observed and isinstance(result, Exception)
            )
            if errors:
                error = StreamingResponseCleanupError(errors)
                if cancellation is not None:
                    raise error from cancellation
                raise error
            propagate_cancellation(cancellation)
        if self.background is not None:
            await self.background()

    async def stream_response(self, send: Send) -> None:
        try:
            await super().stream_response(send)
        finally:
            close = getattr(self.body_iterator, "aclose", None)
            if close is not None:
                await close()
