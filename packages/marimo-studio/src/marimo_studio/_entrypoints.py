"""Marimo extension entry points."""

import atexit

from starlette.middleware import Middleware

from marimo_studio._composition import (
    create_server_adapters,
    install_presentation_authorization,
)
from marimo_studio._composition import kernel_lifespan as kernel_lifespan
from marimo_studio._server.middleware import PresentationMiddleware

_presentation_authorization_handle = install_presentation_authorization()
atexit.register(_presentation_authorization_handle.close)

server_middleware = Middleware(
    PresentationMiddleware,
    adapter_factory=create_server_adapters,
)
