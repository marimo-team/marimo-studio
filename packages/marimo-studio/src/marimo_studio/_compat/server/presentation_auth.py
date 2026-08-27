"""Let Studio validate signed presentation requests before Marimo skew checks."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from starlette.types import Receive, Scope, Send

from marimo_studio._compat.patch import CompositeCloseHandle, ReversiblePatch
from marimo_studio._server.presentation.capability import PRESENTATION_PATH


def _wrap_skew_call(
    original: Callable[[Any, Scope, Receive, Send], Any],
) -> Callable[[Any, Scope, Receive, Send], Any]:
    async def call(
        middleware: Any,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        path = str(scope.get("path", ""))
        if (
            scope["type"] == "http"
            and scope.get("method") == "POST"
            and f"{PRESENTATION_PATH}/" in path
        ):
            await middleware.app(scope, receive, send)
            return
        await original(middleware, scope, receive, send)

    return call


def _wrap_cors_call(
    original: Callable[[Any, Scope, Receive, Send], Any],
) -> Callable[[Any, Scope, Receive, Send], Any]:
    async def call(
        middleware: Any,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        if scope["type"] == "http" and f"{PRESENTATION_PATH}/" in str(
            scope.get("path", "")
        ):
            await middleware.app(scope, receive, send)
            return
        await original(middleware, scope, receive, send)

    return call


def _skew_patch() -> ReversiblePatch:
    from marimo._server.api.middleware import SkewProtectionMiddleware

    return ReversiblePatch(
        "presentation capability skew delegation",
        SkewProtectionMiddleware,
        "__call__",
        _wrap_skew_call,
    )


def _cors_patch() -> ReversiblePatch:
    from starlette.middleware.cors import CORSMiddleware

    return ReversiblePatch(
        "presentation capability CORS delegation",
        CORSMiddleware,
        "__call__",
        _wrap_cors_call,
    )


class PrivatePresentationAuthorization:
    """Install the Marimo adapter for Studio presentation authorization."""

    def __init__(self) -> None:
        self._patches: tuple[ReversiblePatch, ...] | None = None

    def open(self) -> CompositeCloseHandle:
        if self._patches is None:
            from marimo_studio._compat.server.existing_session import (
                _SESSION_CONNECT_PATCH,
            )

            self._patches = (
                _cors_patch(),
                _skew_patch(),
                _SESSION_CONNECT_PATCH,
            )
        return CompositeCloseHandle(patch.open() for patch in self._patches)
