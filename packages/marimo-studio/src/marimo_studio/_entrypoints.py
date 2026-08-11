"""Marimo extension entry points."""

from starlette.middleware import Middleware

from marimo_studio._composition import create_server_adapters, kernel_lifespan
from marimo_studio._server.middleware import PresentationMiddleware

server_middleware = Middleware(
    PresentationMiddleware,
    adapter_factory=create_server_adapters,
)

__all__ = ["kernel_lifespan", "server_middleware"]
