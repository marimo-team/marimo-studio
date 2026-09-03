"""Marimo extension entry points."""

import atexit
import os
from collections.abc import Mapping
from typing import cast

import click
from starlette.middleware import Middleware

from marimo_studio._composition import (
    create_security_policy,
    create_server_adapters,
    install_presentation_authorization,
)
from marimo_studio._composition import kernel_lifespan as kernel_lifespan
from marimo_studio._server.middleware import PresentationMiddleware
from marimo_studio._server.route_policy import EditRootOwner, StudioRoutePolicy
from marimo_studio.errors import ConfigurationError

EDIT_ROOT_ENV = "MARIMO_STUDIO_EDIT_ROOT"


def route_policy_from_environment(
    environment: Mapping[str, str],
) -> StudioRoutePolicy:
    """Adapt process configuration into one immutable route policy."""
    value = environment.get(EDIT_ROOT_ENV, "studio")
    try:
        return StudioRoutePolicy(edit_root=cast(EditRootOwner, value))
    except ValueError as error:
        raise RuntimeError(
            f"{EDIT_ROOT_ENV} must be 'studio' or 'marimo', received {value!r}"
        ) from error


try:
    _security_policy = create_security_policy()
    _route_policy = route_policy_from_environment(os.environ)
except (ConfigurationError, RuntimeError) as error:
    raise click.ClickException(str(error)) from None
_presentation_authorization_handle = install_presentation_authorization()
atexit.register(_presentation_authorization_handle.close)

server_middleware = Middleware(
    PresentationMiddleware,
    adapter_factory=create_server_adapters,
    security_policy=_security_policy,
    route_policy=_route_policy,
)
