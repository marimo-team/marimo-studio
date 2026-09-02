"""Marimo extension entry points."""

import atexit

import click
from starlette.middleware import Middleware

from marimo_studio._composition import (
    create_security_policy,
    create_server_adapters,
    install_presentation_authorization,
)
from marimo_studio._composition import kernel_lifespan as kernel_lifespan
from marimo_studio._server.middleware import PresentationMiddleware
from marimo_studio.errors import ConfigurationError

try:
    _security_policy = create_security_policy()
except ConfigurationError as error:
    raise click.ClickException(str(error)) from None
_presentation_authorization_handle = install_presentation_authorization()
atexit.register(_presentation_authorization_handle.close)

server_middleware = Middleware(
    PresentationMiddleware,
    adapter_factory=create_server_adapters,
    security_policy=_security_policy,
)
