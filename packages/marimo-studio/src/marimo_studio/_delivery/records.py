"""Public callable shape for a Studio ASGI application."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, MutableMapping
from typing import Any, Protocol, TypeAlias

Scope: TypeAlias = MutableMapping[str, Any]
Message: TypeAlias = MutableMapping[str, Any]
Receive: TypeAlias = Callable[[], Awaitable[Message]]
Send: TypeAlias = Callable[[Message], Awaitable[None]]


class ASGIApp(Protocol):
    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None: ...
