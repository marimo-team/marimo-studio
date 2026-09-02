"""Register Studio commands and provide the console-script boundary."""

from __future__ import annotations

import sys
from importlib.metadata import version

import click

from marimo_studio._cli.commands.doctor import doctor
from marimo_studio._cli.commands.notebook import notebook
from marimo_studio._cli.commands.starters import starters
from marimo_studio._cli.commands.status import status
from marimo_studio._cli.commands.validate import validate
from marimo_studio._cli.commands.view import view
from marimo_studio._cli.diagnostics import (
    capture_command_output,
    diagnostics_from_argv,
)
from marimo_studio._cli.help import ColoredGroup
from marimo_studio._cli.output import echo_error
from marimo_studio.errors import MarimoStudioError

_STUDIO_REQUIREMENT = f"marimo-studio=={version('marimo-studio')}"


@click.group(
    cls=ColoredGroup,
    context_settings={"help_option_names": ["-h", "--help"]},
    epilog=f"""\b
Examples:
  marimo-studio status --target analysis.py
  marimo-studio view create dashboard --target analysis.py

Default Vanilla authoring:
  uvx --with {_STUDIO_REQUIREMENT} marimo edit analysis.py --sandbox
""",
    no_args_is_help=True,
)
@click.version_option(prog_name="marimo-studio", package_name="marimo-studio")
def cli() -> None:
    """Design custom views for Marimo notebooks."""


cli.add_command(doctor)
cli.add_command(notebook)
cli.add_command(starters)
cli.add_command(status)
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


def _error_details(error: MarimoStudioError) -> dict[str, object] | None:
    details = error.diagnostic_details()
    if error.public_hint:
        details["hint"] = error.public_hint
    if error.transient:
        details["transient"] = True
    return details or None


def main() -> None:
    """Run the Marimo Studio console script."""
    diagnostics = diagnostics_from_argv(sys.argv[1:])
    machine_result = diagnostics.format == "jsonl"
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
            details=_error_details(error),
        ):
            echo_error(f"Error: {error}")
            if error.public_hint:
                click.echo(f"Hint: {error.public_hint}", err=True)
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
