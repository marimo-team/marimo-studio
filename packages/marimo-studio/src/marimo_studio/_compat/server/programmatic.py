"""Adapt programmatic Marimo applications to an outer ASGI mount."""

from __future__ import annotations

from pathlib import Path
from threading import Lock
from typing import Any

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from marimo_studio._compat.server.gateway import (
    config_manager_at_notebook,
    effective_base_url,
)
from marimo_studio.errors import ProtocolError


class _ProgrammaticApp:
    def __init__(
        self,
        app: ASGIApp,
        state: Any,
        configured_base_url: str,
    ) -> None:
        self.app = app
        self.state = state
        self.configured_base_url = configured_base_url
        self._public_base_url: str | None = None
        self._lock = Lock()

    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        if scope["type"] not in {"http", "websocket"}:
            await self.app(scope, receive, send)
            return

        public_base_url = effective_base_url(scope, self.configured_base_url)
        with self._lock:
            if self._public_base_url is None:
                self._public_base_url = public_base_url
                self.state.base_url = public_base_url
            elif self._public_base_url != public_base_url:
                raise ProtocolError(
                    "A programmatic Marimo app must use one public mount path"
                )

        if scope["type"] != "http" or not public_base_url:
            await self.app(scope, receive, send)
            return

        async def send_with_public_base(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers: list[tuple[bytes, bytes]] = []
                for name, value in message.get("headers", []):
                    if name.lower() == b"location" and (
                        value == b"/auth/login" or value.startswith(b"/auth/login?")
                    ):
                        value = (f"{public_base_url}{value.decode('latin-1')}").encode(
                            "latin-1"
                        )
                    headers.append((name, value))
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_with_public_base)


class _ProgrammaticMiddleware:
    def __init__(self, notebook: Path) -> None:
        self.notebook = notebook

    def __call__(self, app: ASGIApp) -> ASGIApp:
        state = getattr(app, "state", None)
        session_manager = getattr(state, "session_manager", None)
        if state is None or session_manager is None:
            raise ProtocolError("Marimo did not expose single-notebook server state")
        config_manager = config_manager_at_notebook(
            state.config_manager,
            self.notebook,
        )
        state.config_manager = config_manager
        session_manager._config_manager = config_manager
        state._marimo_studio_configured_notebook = self.notebook
        return _ProgrammaticApp(
            app,
            state,
            str(getattr(state, "base_url", "")),
        )


def programmatic_middleware(notebook: Path) -> _ProgrammaticMiddleware:
    """Bind notebook configuration and its public mount to a Marimo app."""
    return _ProgrammaticMiddleware(notebook)
