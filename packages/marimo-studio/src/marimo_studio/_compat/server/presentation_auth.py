"""Let Studio validate signed presentation requests before Marimo skew checks."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from starlette.types import Receive, Scope, Send

from marimo_studio._compat.patch import (
    CallbackCloseHandle,
    CompositeCloseHandle,
    ReversiblePatch,
)
from marimo_studio._server.presentation.capability import PRESENTATION_PATH

_INVALID_SKEW_WARNING = (
    "Received request with invalid server token (skew protection token)."
)
_REDACTED_SKEW_WARNING = (
    "Received request with invalid server token (skew protection token). "
    "This could mean the server has new code deployed but the client is still "
    "using an old version."
)


def _wrap_skew_warning(
    original: Callable[..., Any],
) -> Callable[..., Any]:
    def warning(message: object, *args: object, **kwargs: object) -> Any:
        if isinstance(message, str) and message.startswith(_INVALID_SKEW_WARNING):
            return original(_REDACTED_SKEW_WARNING, **kwargs)
        return original(message, *args, **kwargs)

    return warning


class _SkewLogRedactor:
    def __init__(self, logger: Any) -> None:
        self._logger = logger
        self.warning = _wrap_skew_warning(logger.warning)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._logger, name)


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


def _skew_log_patch() -> ReversiblePatch:
    from marimo._server.api import middleware

    return ReversiblePatch(
        "skew protection log redaction",
        middleware,
        "LOGGER",
        _SkewLogRedactor,
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
                _skew_log_patch(),
                _skew_patch(),
                _SESSION_CONNECT_PATCH,
            )
        handles: list[CallbackCloseHandle] = []
        try:
            for patch in self._patches:
                handles.append(patch.open())
        except BaseException as setup_error:
            try:
                CompositeCloseHandle(handles).close()
            except BaseException as cleanup_error:
                raise setup_error from cleanup_error
            raise
        return CompositeCloseHandle(handles)
