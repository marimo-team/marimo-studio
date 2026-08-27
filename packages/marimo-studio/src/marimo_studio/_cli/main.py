"""Register Studio commands and provide the console-script boundary."""

from __future__ import annotations

import sys

import click

from marimo_studio._cli.commands.bind import bind
from marimo_studio._cli.commands.export import export as export_command
from marimo_studio._cli.commands.inspect import inspect
from marimo_studio._cli.commands.overview import overview
from marimo_studio._cli.commands.provider import provider
from marimo_studio._cli.commands.starter import starter
from marimo_studio._cli.commands.validate import validate
from marimo_studio._cli.commands.view import view
from marimo_studio._cli.diagnostics import (
    capture_command_output,
    diagnostics_from_argv,
    machine_output_from_argv,
)
from marimo_studio._cli.help import ColoredGroup
from marimo_studio._cli.output import echo_error
from marimo_studio.errors import MarimoStudioError


@click.group(
    cls=ColoredGroup,
    context_settings={"help_option_names": ["-h", "--help"]},
    epilog="""\b
Examples:
  marimo-studio overview analysis.py
  marimo-studio view create analysis.py
  marimo edit analysis.py --sandbox
""",
    no_args_is_help=True,
)
@click.version_option(prog_name="marimo-studio", package_name="marimo-studio")
def cli() -> None:
    """Design custom views for Marimo notebooks."""


cli.add_command(bind)
cli.add_command(export_command)
cli.add_command(inspect)
cli.add_command(overview)
cli.add_command(provider)
cli.add_command(starter)
cli.add_command(validate)
cli.add_command(view)


def _show_click_error(error: click.ClickException) -> None:
    context = error.ctx if isinstance(error, click.UsageError) else None
    if context is not None:
        click.echo(context.get_usage().rstrip(), err=True, color=context.color)
        help_option = context.command.get_help_option(context)
        if help_option is not None:
            help_name = max(
                context.command.get_help_option_names(context),
                key=len,
            )
            click.echo(
                f"Try '{context.command_path} {help_name}' for help.",
                err=True,
                color=context.color,
            )
        click.echo(err=True)
    echo_error(f"Error: {error.format_message()}")


def main() -> None:
    """Run the Marimo Studio console script."""
    diagnostics = diagnostics_from_argv(sys.argv[1:])
    machine_result = machine_output_from_argv(sys.argv[1:])
    try:
        with capture_command_output(
            diagnostics,
            capture_stdout=machine_result,
            capture_stderr=diagnostics.format == "jsonl",
        ):
            exit_code = cli(
                standalone_mode=False,
                obj=diagnostics,
                prog_name="marimo-studio",
            )
        if exit_code:
            raise SystemExit(exit_code)
    except MarimoStudioError as error:
        if not diagnostics.emit(
            code=error.code,
            message=str(error),
            severity="error",
            exit_code=error.exit_code,
            details=error.diagnostic_details() or None,
        ):
            echo_error(f"Error: {error}")
        raise SystemExit(error.exit_code) from None
    except click.ClickException as error:
        if not diagnostics.emit(
            code="usage-error",
            message=error.format_message(),
            severity="error",
            exit_code=error.exit_code,
        ):
            _show_click_error(error)
        raise SystemExit(error.exit_code) from None
    except click.exceptions.Exit as error:
        raise SystemExit(error.exit_code) from None
    except click.Abort:
        if not diagnostics.emit(
            code="interrupted",
            message="Command interrupted",
            severity="error",
            exit_code=130,
        ):
            echo_error("Command interrupted")
        raise SystemExit(130) from None
    finally:
        diagnostics.close()


if __name__ == "__main__":
    main()
