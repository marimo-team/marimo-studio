"""Shared Click parameters for Studio commands."""

import math
from pathlib import Path

import click

from marimo_studio._runtime_limits import (
    DEFAULT_RUNTIME_TIMEOUT,
    MAX_RUNTIME_TIMEOUT,
)


def finite_timeout(
    _context: click.Context,
    _parameter: click.Parameter,
    value: float,
) -> float:
    """Reject non-finite Click float values."""
    if not math.isfinite(value):
        raise click.BadParameter("must be a finite number")
    return value


output_format_option = click.option(
    "--format",
    "output_format",
    type=click.Choice(("text", "json")),
    default="text",
    show_default=True,
    help="Set the result format.",
)
runtime_timeout_option = click.option(
    "--runtime-timeout",
    type=click.FloatRange(min=0, max=MAX_RUNTIME_TIMEOUT),
    callback=finite_timeout,
    default=DEFAULT_RUNTIME_TIMEOUT,
    show_default=True,
    help="Seconds to wait for isolated notebook execution.",
)
target_argument = click.argument(
    "target",
    required=False,
    type=click.Path(path_type=Path),
)
