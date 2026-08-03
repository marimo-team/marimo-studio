"""Marimo extension entry points."""

from starlette.middleware import Middleware

from marimo_studio._compat.kernel_values import kernel_lifespan
from marimo_studio._server.middleware import PresentationMiddleware

server_middleware = Middleware(PresentationMiddleware)

__all__ = ["kernel_lifespan", "server_middleware"]
