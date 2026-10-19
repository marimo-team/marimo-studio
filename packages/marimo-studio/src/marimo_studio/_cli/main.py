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
from marimo_studio._workspace.tools import command_installs
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
  uvx --with {_STUDIO_REQUIREMENT} marimo edit analysis.py --sandbox --watch
""",
    no_args_is_help=True,
)
@click.version_option(prog_name="marimo-studio", package_name="marimo-studio")
@click.pass_context
def cli(context: click.Context) -> None:
    """Design custom views for marimo notebooks."""
    # A command targets one notebook, so its provider calls may install the
    # pixi environment that notebook's metadata declares.
    context.with_resource(command_installs())


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


_GENERATION_CONFLICTS = frozenset(
    {"view-generation-conflict", "workspace-generation-conflict"}
)


def _hint(error: MarimoStudioError, command: str | None) -> str:
    # Each CLI run opens the workspace again, so the browser and agent hints
    # for stale state become a rerun or, for a conditional write, a new read.
    if command == "view write" and (
        error.code in _GENERATION_CONFLICTS or error.code == "source-conflict"
    ):
        return (
            "Run `marimo-studio view read VIEW PATH --target TARGET --json` with "
            "the same --target as the write for the current revision and "
            "generations, then retry the write."
        )
    if error.code in _GENERATION_CONFLICTS:
        return "Run the command again."
    if error.code == "authentication-required" and not error.public_hint:
        return (
            "Set MARIMO_STUDIO_ACCESS_TOKEN to the server's access token, the "
            "access_token value in the URL that marimo printed, then run the "
            "command again."
        )
    return error.public_hint


def _error_details(error: MarimoStudioError, hint: str) -> dict[str, object] | None:
    details = error.diagnostic_details()
    if hint:
        details["hint"] = hint
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
        hint = _hint(error, diagnostics.command)
        if not diagnostics.emit(
            code=error.code,
            message=str(error),
            severity="error",
            exit_code=error.exit_code,
            details=_error_details(error, hint),
        ):
            echo_error(f"Error: {error}")
            if hint:
                click.echo(f"Hint: {hint}", err=True)
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
