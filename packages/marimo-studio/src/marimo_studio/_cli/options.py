"""Shared Click parameters for Studio commands."""

from pathlib import Path

import click

output_format_option = click.option(
    "--format",
    "output_format",
    type=click.Choice(("text", "json")),
    default="text",
    show_default=True,
    help="Set the result format.",
)
target_argument = click.argument(
    "target",
    required=False,
    type=click.Path(path_type=Path),
)
