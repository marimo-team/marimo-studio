"""Inspect, configure, and open Studio views for Marimo notebooks."""

from __future__ import annotations

import asyncio
import json
import os
import secrets
import subprocess
import sys
import tempfile
import threading
import webbrowser
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import click

from marimo_studio._workspace import (
    bind_cell,
    check_runtime_studio,
    check_studio,
    ensure_view,
    load_studio,
)
from marimo_studio._workspace.environment import (
    environment_command,
    run_in_notebook_environment,
    should_reenter,
)
from marimo_studio._workspace.models import StudioConfig
from marimo_studio.errors import ConfigurationError, MarimoStudioError
from marimo_studio.inspect import RuntimeInspection, inspect_notebook, inspect_runtime
from marimo_studio.types import CellSpec

_COMMAND_NAMES = frozenset({"bind", "check", "inspect", "view"})
_LAUNCH_COMMAND = "\N{ZERO WIDTH SPACE}launch"
_CHECK_SEVERITY = {"pass": "info", "warn": "warning", "fail": "error"}


class _DirectGroup(click.Group):
    """Dispatch every non-command token to the internal launch command."""

    def parse_args(self, ctx: click.Context, args: list[str]) -> list[str]:
        if not args or args[0] not in _COMMAND_NAMES | {"-h", "--help", "--version"}:
            args.insert(0, _LAUNCH_COMMAND)
        return super().parse_args(ctx, args)

    def format_usage(
        self,
        ctx: click.Context,
        formatter: click.HelpFormatter,
    ) -> None:
        formatter.write("Usage:\n")
        formatter.write(f"  {ctx.command_path} [NOTEBOOK] [OPTIONS]\n")
        formatter.write(f"  {ctx.command_path} COMMAND [ARGS]...\n")


class _LaunchCommand(click.Command):
    """Render direct-launch help without exposing the dispatch command."""

    def format_usage(
        self,
        ctx: click.Context,
        formatter: click.HelpFormatter,
    ) -> None:
        command_path = ctx.parent.command_path if ctx.parent else "marimo-studio"
        formatter.write_usage(command_path, "[NOTEBOOK] [OPTIONS] [-- MARIMO_ARGS]")


_output_format_option = click.option(
    "--format",
    "output_format",
    type=click.Choice(("text", "json")),
    default="text",
    show_default=True,
    help="Set the result format.",
)


@dataclass
class _DiagnosticStream:
    format: str = "text"
    command: str | None = None
    error_count: int = 0

    def _write(self, event: dict[str, object]) -> None:
        click.echo(
            json.dumps(
                event,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ),
            err=True,
        )

    def emit(
        self,
        *,
        code: str,
        message: str,
        severity: str,
        exit_code: int | None = None,
        status: str | None = None,
    ) -> bool:
        if self.format != "jsonl":
            return False
        if severity == "error":
            self.error_count += 1
        event: dict[str, object] = {
            "schema": 1,
            "event": "diagnostic",
            "command": self.command,
            "severity": severity,
            "code": code,
            "message": message,
        }
        if exit_code is not None:
            event["exit_code"] = exit_code
        if status is not None:
            event["status"] = status
        self._write(event)
        return True

    def relay(self, line: str) -> None:
        if not line:
            return
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            event = None
        if (
            isinstance(event, dict)
            and event.get("schema") == 1
            and event.get("event") == "diagnostic"
            and event.get("severity") in {"info", "warning", "error"}
            and isinstance(event.get("code"), str)
            and isinstance(event.get("message"), str)
        ):
            if event["severity"] == "error":
                self.error_count += 1
            self._write(event)
            return
        self.emit(code="process-output", message=line, severity="warning")


def _command_from_argv(args: list[str]) -> str:
    if not args:
        return "launch"
    first = args[0]
    if first == "view" and len(args) > 1 and args[1] in {"add", "list"}:
        return f"view {args[1]}"
    if first in _COMMAND_NAMES:
        return first
    return "launch"


def _diagnostics_from_argv(args: list[str]) -> _DiagnosticStream:
    stream = _DiagnosticStream(command=_command_from_argv(args))
    for index, argument in enumerate(args):
        if argument == "--":
            break
        if argument == "--diagnostics" and index + 1 < len(args):
            stream.format = args[index + 1]
        elif argument.startswith("--diagnostics="):
            stream.format = argument.partition("=")[2]
    if stream.format not in {"text", "jsonl"}:
        stream.format = "text"
    return stream


def _diagnostics() -> _DiagnosticStream:
    return click.get_current_context().find_root().ensure_object(_DiagnosticStream)


def _configure_diagnostics(
    context: click.Context,
    _parameter: click.Parameter,
    value: str,
) -> str:
    stream = context.find_root().ensure_object(_DiagnosticStream)
    stream.format = value
    command = context.command_path.removeprefix("cli ")
    stream.command = (
        "launch"
        if command.endswith(_LAUNCH_COMMAND)
        else command.removeprefix("marimo-studio ")
    )
    return value


_diagnostic_format_option = click.option(
    "--diagnostics",
    type=click.Choice(("text", "jsonl")),
    default="text",
    show_default=True,
    expose_value=False,
    is_eager=True,
    callback=_configure_diagnostics,
    help="Set the stderr diagnostic format.",
)


@contextmanager
def _capture_runtime_stderr() -> Iterator[None]:
    diagnostics = _diagnostics()
    if diagnostics.format != "jsonl":
        yield
        return
    with tempfile.TemporaryFile(mode="w+b") as captured:
        sys.stderr.flush()
        stderr_fd = sys.stderr.fileno()
        saved_fd = os.dup(stderr_fd)
        try:
            os.dup2(captured.fileno(), stderr_fd)
            yield
        finally:
            sys.stderr.flush()
            os.dup2(saved_fd, stderr_fd)
            os.close(saved_fd)
            captured.seek(0)
            for line in captured.read().decode("utf-8", errors="replace").splitlines():
                diagnostics.emit(
                    code="process-output",
                    message=line,
                    severity="warning",
                )


def _json(value: Any) -> None:
    click.echo(json.dumps(value, indent=2, sort_keys=True))


def _studio(target: str | Path | None) -> StudioConfig:
    return load_studio(target or ".")


def _notebook(target: str | Path | None) -> Path:
    if target is None:
        return _studio(None).notebook
    path = Path(target).expanduser()
    if path.is_dir() or path.suffix == ".toml":
        return _studio(path).notebook
    return path.resolve()


@dataclass(frozen=True)
class _NotebookTarget:
    root: Path
    notebook: Path


def _environment_target(
    target: str | Path | None,
    notebook: Path,
) -> StudioConfig | _NotebookTarget:
    if target is None:
        return _studio(None)
    path = Path(target).expanduser()
    if path.is_dir() or path.suffix == ".toml":
        return _studio(path)
    root = next(
        (
            parent
            for parent in notebook.parents
            if (parent / "pyproject.toml").is_file()
        ),
        notebook.parent,
    )
    return _NotebookTarget(root, notebook)


def _run_in_environment(
    target: StudioConfig | _NotebookTarget,
    args: list[str],
) -> int:
    diagnostics = _diagnostics()
    errors_before = diagnostics.error_count
    exit_code = run_in_notebook_environment(
        target,
        args,
        diagnostic_line=diagnostics.relay if diagnostics.format == "jsonl" else None,
    )
    if (
        exit_code
        and diagnostics.format == "jsonl"
        and diagnostics.error_count == errors_before
    ):
        diagnostics.emit(
            code="notebook-environment-error",
            message="Notebook environment exited before the command completed",
            severity="error",
            exit_code=exit_code,
        )
    return exit_code


def _runtime_payload(
    inspection: RuntimeInspection,
    cells: tuple[CellSpec, ...],
) -> dict[str, Any]:
    payload = inspection.notebook.to_dict()
    payload["cells"] = [
        {
            **cell.to_dict(),
            "runtime": inspection.runtime.cells[cell.runtime_id].to_dict(),
        }
        for cell in cells
    ]
    payload["runtime"] = inspection.runtime.values.to_dict()
    return payload


def _json_preview(value: object, *, limit: int = 160) -> str:
    rendered = json.dumps(value, ensure_ascii=False, sort_keys=True)
    return rendered if len(rendered) <= limit else rendered[: limit - 1] + "…"


def _open_later(url: str) -> None:
    timer = threading.Timer(1.2, webbrowser.open, args=(url,))
    timer.daemon = True
    timer.start()


def _validate_marimo_args(args: tuple[str, ...]) -> None:
    managed = {
        "--base-url",
        "--headless",
        "--host",
        "--no-sandbox",
        "--open",
        "--port",
        "--proxy",
    }
    for argument in args:
        option = argument.partition("=")[0]
        if option in managed or option == "-p" or option.startswith("-p"):
            raise click.UsageError(
                f"Pass {option} before `--`. Marimo Studio manages this option."
            )


def _validate_base_url(
    _context: click.Context,
    parameter: click.Parameter,
    value: str,
) -> str:
    if value and not value.startswith("/"):
        raise click.BadParameter("must start with /", param=parameter)
    return value


def _browser_auth(
    marimo_args: tuple[str, ...],
    *,
    open_browser: bool,
) -> tuple[tuple[str, ...], str | None]:
    if not open_browser:
        return marimo_args, None

    token_enabled: bool | None = None
    token_password: str | None = None
    token_file: str | None = None
    index = 0
    while index < len(marimo_args):
        argument = marimo_args[index]
        if argument == "--no-token":
            token_enabled = False
            token_password = None
            token_file = None
        elif argument == "--token":
            token_enabled = True
        elif argument == "--token-password":
            if index + 1 >= len(marimo_args):
                raise click.UsageError("--token-password requires a value")
            index += 1
            token_enabled = True
            token_password = marimo_args[index]
            token_file = None
        elif argument.startswith("--token-password="):
            token_enabled = True
            token_password = argument.partition("=")[2]
            token_file = None
        elif argument == "--token-password-file":
            if index + 1 >= len(marimo_args):
                raise click.UsageError("--token-password-file requires a path")
            index += 1
            token_enabled = True
            token_file = marimo_args[index]
            token_password = None
        elif argument.startswith("--token-password-file="):
            token_enabled = True
            token_file = argument.partition("=")[2]
            token_password = None
        index += 1

    if token_enabled is False:
        return marimo_args, None
    if token_file is not None:
        if token_file == "-":
            raise click.UsageError(
                "Use --headless when --token-password-file reads from stdin"
            )
        try:
            token_password = Path(token_file).read_text(encoding="utf-8").strip()
        except OSError as error:
            raise click.UsageError(
                f"Could not read --token-password-file {token_file!r}: {error}"
            ) from error
    if token_password is not None:
        if not token_password:
            raise click.UsageError("Marimo access tokens must not be empty")
        return marimo_args, token_password

    token_password = secrets.token_urlsafe(24)
    return (
        (*marimo_args, "--token-password", token_password),
        token_password,
    )


@click.group(
    cls=_DirectGroup,
    context_settings={"help_option_names": ["-h", "--help"]},
    no_args_is_help=False,
)
@click.version_option(prog_name="marimo-studio", package_name="marimo-studio")
def cli() -> None:
    """Design custom views for Marimo notebooks."""


@cli.group("view")
def view_group() -> None:
    """Create and list notebook views."""


@view_group.command("add")
@click.argument("name")
@click.argument("notebook", required=False, type=click.Path(path_type=Path))
@click.option("--dry-run", is_flag=True, help="Report changes without writing.")
@_output_format_option
@_diagnostic_format_option
def view_add_command(
    name: str,
    notebook: Path | None,
    dry_run: bool,
    output_format: str,
) -> None:
    """Add the named view to NOTEBOOK."""
    result = ensure_view(_notebook(notebook), name, dry_run=dry_run)
    if output_format == "json":
        _json(result.to_dict())
        return
    verb = "Would add" if dry_run else "Added"
    click.echo(f"{verb} view {name} at {result.root}")
    for path in result.created:
        click.echo(f"  create {path}")
    for path in result.updated:
        click.echo(f"  update {path}")


@view_group.command("list")
@click.argument("notebook", required=False, type=click.Path(path_type=Path))
@_output_format_option
@_diagnostic_format_option
def view_list_command(notebook: Path | None, output_format: str) -> None:
    """List views configured for NOTEBOOK."""
    studio = _studio(notebook)
    payload = {
        "schema": 1,
        "notebook": str(studio.notebook),
        "default_view": studio.default_view,
        "views": [
            {
                "name": name,
                "path": str(view.root),
                "default": name == studio.default_view,
            }
            for name, view in studio.views.items()
        ],
    }
    if output_format == "json":
        _json(payload)
        return
    for item in payload["views"]:
        assert isinstance(item, dict)
        suffix = " (default)" if item["default"] else ""
        click.echo(f"{item['name']}{suffix}\n  {item['path']}")


@cli.command("inspect")
@click.argument("notebook", required=False, type=click.Path(path_type=Path))
@click.option("--include-code", is_flag=True, help="Include complete cell source.")
@click.option(
    "--display",
    "output_expressions",
    is_flag=True,
    help="Return cells with a final output expression.",
)
@click.option(
    "--runtime",
    is_flag=True,
    help="Execute cells and include MIME outputs and JSON values.",
)
@click.option("--limit", type=click.IntRange(min=1), help="Limit cell records.")
@_output_format_option
@_diagnostic_format_option
def inspect_command(
    notebook: Path | None,
    include_code: bool,
    output_expressions: bool,
    runtime: bool,
    limit: int | None,
    output_format: str,
) -> None:
    """Inspect cells in NOTEBOOK."""
    notebook_path = _notebook(notebook)
    if not notebook_path.is_file():
        raise ConfigurationError(f"Notebook does not exist: {notebook_path}")
    runtime_inspection: RuntimeInspection | None = None
    if runtime:
        environment = _environment_target(notebook, notebook_path)
        if should_reenter(environment, None):
            raise click.exceptions.Exit(_run_in_environment(environment, sys.argv[1:]))
        with _capture_runtime_stderr():
            runtime_inspection = asyncio.run(
                inspect_runtime(notebook_path, include_code=include_code)
            )
        spec = runtime_inspection.notebook
    else:
        spec = inspect_notebook(notebook_path, include_code=include_code)
    cells = tuple(
        cell
        for cell in spec.cells
        if not output_expressions or cell.has_output_expression
    )
    if limit is not None:
        cells = cells[:limit]
    if output_format == "json":
        _json(
            _runtime_payload(runtime_inspection, cells)
            if runtime_inspection is not None
            else {
                **spec.to_dict(),
                "cells": [cell.to_dict() for cell in cells],
            }
        )
        return
    click.echo(f"{spec.path} · {len(spec.cells)} cells")
    for position, cell in enumerate(cells):
        if position:
            click.echo()
        label = cell.name or f"cell {cell.index}"
        kind = "output" if cell.has_output_expression else "compute"
        click.echo(
            f"{cell.index:>3}  {cell.runtime_id:<6} {kind:<7} "
            f"line {cell.source.start_line:<4} {label}"
        )
        click.echo(f"     {cell.ref}")
        if cell.definitions:
            click.echo(f"     defines: {', '.join(cell.definitions)}")
        if runtime_inspection is not None:
            runtime_cell = runtime_inspection.runtime.cells[cell.runtime_id]
            click.echo(f"     runtime: {runtime_cell.status or 'missing'}")
            outputs = ", ".join(
                (
                    f"{output.channel}:{output.mimetype}"
                    + (" (empty)" if output.empty else "")
                )
                for output in runtime_cell.outputs
            )
            click.echo(f"     outputs: {outputs or 'none'}")
            if runtime_cell.errors:
                click.echo(f"     error: {runtime_cell.errors[0]}")
    if runtime_inspection is not None:
        values = runtime_inspection.runtime.values
        click.echo("\nJSON values")
        for name, value in values.values.items():
            click.echo(f"  {name} = {_json_preview(value)}")
        if not values.values:
            click.echo("  none")
        if values.errors:
            click.echo("\nValue errors")
            for name, error in values.errors.items():
                click.echo(f"  {name}: {error.code}: {error.message}")


@cli.command("bind")
@click.argument("alias")
@click.argument("notebook", required=False, type=click.Path(path_type=Path))
@click.option(
    "--cell",
    "cell_index",
    required=True,
    type=click.IntRange(min=0),
    help="Select a zero-based notebook cell.",
)
@click.option("--dry-run", is_flag=True, help="Report the binding without writing.")
@click.option("--overwrite", is_flag=True, help="Replace an existing binding.")
@_output_format_option
@_diagnostic_format_option
def bind_command(
    alias: str,
    notebook: Path | None,
    cell_index: int,
    dry_run: bool,
    overwrite: bool,
    output_format: str,
) -> None:
    """Bind ALIAS to a cell in NOTEBOOK."""
    result = bind_cell(
        _studio(notebook),
        alias,
        cell_index,
        dry_run=dry_run,
        overwrite=overwrite,
    )
    if output_format == "json":
        payload = result.to_dict()
        payload["dry_run"] = dry_run
        _json(payload)
        return
    if result.previous_ref == result.cell.ref:
        click.echo(f"{alias} already points to cell {result.cell.index}")
        return
    verb = "Would bind" if dry_run else "Bound"
    click.echo(
        f"{verb} {alias} to cell {result.cell.index} "
        f"({result.cell.source.start_line}-{result.cell.source.end_line})"
    )


@cli.command("check")
@click.argument("notebook", required=False, type=click.Path(path_type=Path))
@click.option("--view", "view_name", help="Validate one named view.")
@click.option(
    "--runtime",
    "runtime_check",
    is_flag=True,
    help="Execute projected cells and resolve projected values.",
)
@_output_format_option
@_diagnostic_format_option
def check_command(
    notebook: Path | None,
    view_name: str | None,
    runtime_check: bool,
    output_format: str,
) -> None:
    """Validate the views configured for NOTEBOOK."""
    studio = _studio(notebook)
    if runtime_check and should_reenter(studio, None):
        raise click.exceptions.Exit(_run_in_environment(studio, sys.argv[1:]))
    results = check_studio(studio, view_name=view_name)
    if runtime_check and not any(result.status == "fail" for result in results):
        with _capture_runtime_stderr():
            results += asyncio.run(check_runtime_studio(studio, view_name=view_name))
    ok = not any(result.status == "fail" for result in results)
    diagnostics = _diagnostics()
    for result in results:
        diagnostics.emit(
            code=result.name,
            message=result.message,
            severity=_CHECK_SEVERITY[result.status],
            status=result.status,
        )
    if output_format == "json":
        _json(
            {
                "schema": 1,
                "ok": ok,
                "notebook": str(studio.notebook),
                "view": view_name,
                "checks": [result.to_dict() for result in results],
            }
        )
    else:
        for result in results:
            click.echo(f"{result.status.upper():<4} {result.name}: {result.message}")
    if not ok:
        raise click.exceptions.Exit(1)


@click.command(
    _LAUNCH_COMMAND,
    cls=_LaunchCommand,
    hidden=True,
    context_settings={"ignore_unknown_options": False},
)
@click.argument("notebook", required=False, type=click.Path(path_type=Path))
@click.argument("marimo_args", nargs=-1, type=click.UNPROCESSED)
@click.option("--view", "view_name", help="Open a named view.")
@click.option("--host", default="127.0.0.1", show_default=True)
@click.option("--port", default=8000, show_default=True, type=click.IntRange(1, 65535))
@click.option("--open/--headless", "open_browser", default=True, show_default=True)
@click.option(
    "--base-url",
    default="",
    callback=_validate_base_url,
    help="Serve beneath this URL path.",
)
def _launch_command(
    notebook: Path | None,
    marimo_args: tuple[str, ...],
    view_name: str | None,
    host: str,
    port: int,
    open_browser: bool,
    base_url: str,
) -> None:
    """Configure NOTEBOOK and open Studio."""
    _validate_marimo_args(marimo_args)
    marimo_args, access_token = _browser_auth(
        marimo_args,
        open_browser=open_browser,
    )
    result = ensure_view(_notebook(notebook), view_name)
    studio = result.studio
    assert studio is not None
    selected = result.name
    public_host = "127.0.0.1" if host in {"0.0.0.0", "::"} else host
    path = base_url.rstrip("/") + "/_marimo-studio/studio/"
    query = {"view": selected}
    if access_token is not None:
        query["access_token"] = access_token
    url = f"http://{public_host}:{port}{path}?{urlencode(query)}"
    click.echo(f"Studio: {url}")
    if open_browser:
        _open_later(url)
    command = environment_command(
        studio,
        [
            "marimo",
            "edit",
            str(studio.notebook),
            "--host",
            host,
            "--port",
            str(port),
            "--base-url",
            base_url,
            "--headless",
            "--no-sandbox",
            *marimo_args,
        ],
    )
    working_directory = (
        studio.notebook.parent if studio.uses_notebook_config else studio.root
    )
    raise click.exceptions.Exit(
        subprocess.run(
            command,
            cwd=working_directory,
            check=False,
            stdout=sys.stderr,
            stderr=sys.stderr,
        ).returncode
    )


cli.add_command(_launch_command)


def main() -> None:
    diagnostics = _diagnostics_from_argv(sys.argv[1:])
    try:
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
        ):
            click.echo(f"Error: {error}", err=True)
        raise SystemExit(error.exit_code) from None
    except click.ClickException as error:
        if not diagnostics.emit(
            code="usage-error",
            message=error.format_message(),
            severity="error",
            exit_code=error.exit_code,
        ):
            error.show()
        raise SystemExit(error.exit_code) from None
    except click.exceptions.Exit as error:
        raise SystemExit(error.exit_code) from None
    except click.Abort:
        diagnostics.emit(
            code="interrupted",
            message="Command interrupted",
            severity="error",
            exit_code=130,
        )
        raise SystemExit(130) from None


if __name__ == "__main__":
    main()
