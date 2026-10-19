"""Create, rename, select, and remove the named views of a notebook."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import click

from marimo_studio._authoring.view import make_default_view, remove_view, rename_view
from marimo_studio._authoring.workspace import create_view
from marimo_studio._cli.diagnostics import json_option, run_in_environment
from marimo_studio._cli.environment import (
    include_provider_ids,
    provider_bootstrap_required,
)
from marimo_studio._cli.help import ColoredCommand
from marimo_studio._cli.options import (
    target_option,
    view_name_argument,
)
from marimo_studio._cli.output import (
    echo_json,
    emit_view_catalog,
    render_view_next_command,
    render_view_setup,
)
from marimo_studio._cli.targets import resolve_environment_target, resolve_notebook
from marimo_studio._views.catalog import starter_settings
from marimo_studio._views.records import ViewChoices
from marimo_studio.view_providers._host.package_policy import DEFAULT_STARTER_ID


def _stdin_is_interactive() -> bool:
    # Embedded interpreters may run without stdin, and a closed stdin raises.
    try:
        return sys.stdin.isatty()
    except (AttributeError, ValueError):
        return False


def _starter_provider_id(starter: str | None) -> str | None:
    if starter is None:
        return None
    provider_id, separator, local_key = starter.rpartition(":")
    distribution, provider_separator, registration = provider_id.partition("/")
    if not (
        separator and local_key and distribution and provider_separator and registration
    ):
        return None
    return provider_id


def _setting_values(
    values: tuple[str, ...], starter: str | None
) -> dict[str, str | bool]:
    switches = (
        {
            setting.key
            for setting in starter_settings(starter or DEFAULT_STARTER_ID)
            if setting.kind == "boolean"
        }
        if values
        else set()
    )
    settings: dict[str, str | bool] = {}
    for value in values:
        key, separator, text = value.partition("=")
        if not separator or not key:
            raise click.BadParameter(
                f"expected KEY=VALUE, got {value!r}", param_hint="--setting"
            )
        if key not in switches:
            settings[key] = text
        elif text in {"true", "false"}:
            settings[key] = text == "true"
        else:
            raise click.BadParameter(
                f"{key} is a switch, so write {key}=true or {key}=false",
                param_hint="--setting",
            )
    return settings


@click.command("create", cls=ColoredCommand)
@view_name_argument
@target_option
@click.option(
    "--starter",
    default=None,
    metavar="ID",
    help="Choose an installed starting point for the view.",
)
@click.option(
    "--title",
    default=None,
    help=(
        "Set the title the starter writes into the view. Defaults to one made "
        "from its name."
    ),
)
@click.option(
    "--setting",
    "settings",
    multiple=True,
    metavar="KEY=VALUE",
    help=(
        "Set one of the starter's settings. Write true or false for a switch. "
        "`marimo-studio starters` lists each starter's settings."
    ),
)
@click.option(
    "--make-default",
    is_flag=True,
    help="Serve the new view at the notebook's main route.",
)
@click.option("--dry-run", is_flag=True, help="Report changes without writing.")
@json_option
def create(
    view_name: str,
    target: Path | None,
    starter: str | None,
    title: str | None,
    settings: tuple[str, ...],
    make_default: bool,
    dry_run: bool,
    json_output: bool,
) -> None:
    """Create one named view.

    When needed, Studio reruns the command through uv with requirements derived
    from the target's saved views and Python metadata. uv may resolve and install
    packages before provider code loads. Reviewed provider code then runs with
    the current user's filesystem, environment, and network authority.
    """
    notebook = resolve_notebook(target)
    environment = resolve_environment_target(target, notebook)
    provider_id = _starter_provider_id(starter)
    if provider_id is not None:
        environment = include_provider_ids(environment, (provider_id,))
    if provider_bootstrap_required(environment):
        raise click.exceptions.Exit(run_in_environment(environment, sys.argv[1:]))
    result = asyncio.run(
        create_view(
            notebook,
            view_name,
            starter=starter,
            choices=ViewChoices(
                title=title, settings=_setting_values(settings, starter)
            ),
            make_default=make_default,
            dry_run=dry_run,
        )
    )
    if json_output:
        echo_json(result.to_dict())
        render_view_next_command(result)
        return
    render_view_setup(result)


@click.command("remove", cls=ColoredCommand)
@view_name_argument
@target_option
@click.option("--yes", is_flag=True, help="Remove the view without prompting.")
@json_option
def remove(
    view_name: str,
    target: Path | None,
    yes: bool,
    json_output: bool,
) -> None:
    """Remove one view and its source files."""
    if not yes and (json_output or not _stdin_is_interactive()):
        raise click.UsageError(
            "Pass --yes for machine output or non-interactive input."
        )
    if not yes and not click.confirm(
        f"Remove view {view_name!r} and its project directory?",
        default=False,
        err=True,
    ):
        raise click.exceptions.Exit(0)
    catalog = asyncio.run(remove_view(resolve_notebook(target), view_name))
    emit_view_catalog(
        catalog, view_name, "Removed", f"view {view_name}", json_output=json_output
    )


@click.command("rename", cls=ColoredCommand)
@view_name_argument
@click.argument("new_name", metavar="NEW_NAME")
@target_option
@json_option
def rename(
    view_name: str,
    new_name: str,
    target: Path | None,
    json_output: bool,
) -> None:
    """Move one view and its project files to a new name."""
    catalog = asyncio.run(rename_view(resolve_notebook(target), view_name, new_name))
    emit_view_catalog(
        catalog,
        new_name,
        "Renamed",
        f"view {view_name} to {new_name}",
        json_output=json_output,
    )


@click.command("default", cls=ColoredCommand)
@view_name_argument
@target_option
@json_option
def default(view_name: str, target: Path | None, json_output: bool) -> None:
    """Serve one view at the notebook's main route."""
    catalog = asyncio.run(make_default_view(resolve_notebook(target), view_name))
    emit_view_catalog(
        catalog,
        view_name,
        "Selected",
        f"default view {view_name}",
        json_output=json_output,
    )
