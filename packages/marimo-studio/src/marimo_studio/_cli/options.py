"""Shared Click parameters for Studio commands."""

import math
from pathlib import Path

import click

from marimo_studio._processes.limits import (
    DEFAULT_RUNTIME_TIMEOUT,
    MAX_RUNTIME_TIMEOUT,
)


class OwnerGenerationType(click.ParamType[str]):
    """Parse one opaque SHA-256 workspace owner generation."""

    name = "generation"

    def convert(
        self,
        value: object,
        param: click.Parameter | None,
        ctx: click.Context | None,
    ) -> str:
        if (
            isinstance(value, str)
            and len(value) == 64
            and all(character in "0123456789abcdef" for character in value)
        ):
            return value
        self.fail(
            "must be a 64-character lowercase hexadecimal string",
            param,
            ctx,
        )


owner_generation_type = OwnerGenerationType()


def finite_timeout(
    _context: click.Context,
    _parameter: click.Parameter,
    value: float,
) -> float:
    """Reject non-finite Click float values."""
    if not math.isfinite(value):
        raise click.BadParameter("must be a finite number")
    return value


runtime_timeout_option = click.option(
    "--runtime-timeout",
    type=click.FloatRange(min=0, max=MAX_RUNTIME_TIMEOUT),
    callback=finite_timeout,
    default=DEFAULT_RUNTIME_TIMEOUT,
    show_default=True,
    help="Seconds to wait for isolated notebook execution.",
)
browser_client_option = click.option(
    "--browser-client",
    envvar="MARIMO_STUDIO_BROWSER_CLIENT",
    show_envvar=True,
    help="Target one connected Studio browser client.",
)


def server_option(*, required: bool = False):
    """Add the running Studio server URL option."""
    return click.option(
        "--server",
        "server_url",
        envvar="MARIMO_STUDIO_SERVER_URL",
        show_envvar=True,
        required=required,
        help=(
            "Connect to this running Studio server URL. Set "
            "MARIMO_STUDIO_ACCESS_TOKEN when the server requires authentication."
        ),
    )


target_option = click.option(
    "--target",
    type=click.Path(path_type=Path),
    help=(
        "Select a notebook, project directory, or pyproject.toml. "
        "Defaults to the current Studio configuration."
    ),
)
view_name_argument = click.argument("view_name", metavar="VIEW")
