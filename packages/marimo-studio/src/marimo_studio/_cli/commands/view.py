"""Register commands for named Studio views."""

import click

from marimo_studio._cli.commands.view_create import create, remove
from marimo_studio._cli.commands.view_delivery import build, export, show
from marimo_studio._cli.commands.view_source import inspect, read, write
from marimo_studio._cli.help import ColoredGroup


@click.group("view", cls=ColoredGroup)
def view() -> None:
    """Create and operate named notebook views."""


view.add_command(create)
view.add_command(inspect)
view.add_command(read)
view.add_command(write)
view.add_command(build)
view.add_command(show)
view.add_command(export)
view.add_command(remove)
