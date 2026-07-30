"""Colored Click help and direct notebook dispatch."""

from __future__ import annotations

import click

from marimo_studio._cli.print import bright_green, light_blue

_LAUNCH_COMMAND = "\N{ZERO WIDTH SPACE}launch"


def section(text: str) -> str:
    return bright_green(text)


def option(text: str) -> str:
    return light_blue(text)


class ColoredCommand(click.Command):
    """Render option names and usage headings with terminal color."""

    def format_usage(
        self,
        ctx: click.Context,
        formatter: click.HelpFormatter,
    ) -> None:
        formatter.write_usage(
            ctx.command_path,
            " ".join(self.collect_usage_pieces(ctx)),
            section("Usage: "),
        )

    def format_options(
        self,
        ctx: click.Context,
        formatter: click.HelpFormatter,
    ) -> None:
        rows = []
        for parameter in self.get_params(ctx):
            record = parameter.get_help_record(ctx)
            if record is not None:
                name, description = record
                rows.append((option(name), description))
        if rows:
            with formatter.section(section("Options")):
                formatter.write_dl(rows)


class ColoredGroup(click.Group):
    """Render command groups with the same terminal palette."""

    command_class = ColoredCommand

    def format_usage(
        self,
        ctx: click.Context,
        formatter: click.HelpFormatter,
    ) -> None:
        formatter.write_usage(
            ctx.command_path,
            " ".join(self.collect_usage_pieces(ctx)),
            section("Usage: "),
        )

    def format_options(
        self,
        ctx: click.Context,
        formatter: click.HelpFormatter,
    ) -> None:
        rows = []
        for parameter in self.get_params(ctx):
            record = parameter.get_help_record(ctx)
            if record is not None:
                name, description = record
                rows.append((option(name), description))
        if rows:
            with formatter.section(section("Options")):
                formatter.write_dl(rows)
        self.format_commands(ctx, formatter)

    def format_commands(
        self,
        ctx: click.Context,
        formatter: click.HelpFormatter,
    ) -> None:
        rows = []
        for name in self.list_commands(ctx):
            command = self.get_command(ctx, name)
            if command is not None and not command.hidden:
                rows.append((option(name), command.get_short_help_str()))
        if rows:
            with formatter.section(section("Commands")):
                formatter.write_dl(rows)


class DirectGroup(ColoredGroup):
    """Dispatch notebook paths and launch options to the launch command."""

    def parse_args(self, ctx: click.Context, args: list[str]) -> list[str]:
        commands = {
            name for name, command in self.commands.items() if not command.hidden
        }
        root_options = {"-h", "--help", "--version"}
        if not args or args[0] not in commands | root_options:
            args.insert(0, _LAUNCH_COMMAND)
        return super().parse_args(ctx, args)

    def format_usage(
        self,
        ctx: click.Context,
        formatter: click.HelpFormatter,
    ) -> None:
        formatter.write(section("Usage:") + "\n")
        formatter.write(f"  {ctx.command_path} [NOTEBOOK] [OPTIONS]\n")
        formatter.write(f"  {ctx.command_path} COMMAND [ARGS]...\n")


class LaunchCommand(ColoredCommand):
    """Render direct-launch help under the root command name."""

    def format_usage(
        self,
        ctx: click.Context,
        formatter: click.HelpFormatter,
    ) -> None:
        command_path = ctx.parent.command_path if ctx.parent else "marimo-studio"
        formatter.write_usage(
            command_path,
            "[NOTEBOOK] [OPTIONS] [-- MARIMO_ARGS]",
            section("Usage: "),
        )


LAUNCH_COMMAND = _LAUNCH_COMMAND
