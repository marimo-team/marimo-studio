"""Emit human and JSON Lines diagnostics for CLI commands."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

import click

from marimo_studio._cli.help import LAUNCH_COMMAND
from marimo_studio._workspace.environment import (
    EnvironmentTarget,
    run_in_notebook_environment,
)

_COMMAND_NAMES = frozenset({"bind", "check", "inspect", "view"})


@dataclass
class DiagnosticStream:
    """Write structured diagnostics to stderr when JSON Lines is selected."""

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
        """Write one diagnostic and return whether JSON Lines is active."""
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
        """Forward a child diagnostic or wrap plain child stderr."""
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
    return first if first in _COMMAND_NAMES else "launch"


def diagnostics_from_argv(args: list[str]) -> DiagnosticStream:
    """Create the root diagnostic stream before Click parses arguments."""
    stream = DiagnosticStream(command=_command_from_argv(args))
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


def diagnostics() -> DiagnosticStream:
    """Return the diagnostic stream attached to the root Click context."""
    return click.get_current_context().find_root().ensure_object(DiagnosticStream)


def _configure_diagnostics(
    context: click.Context,
    _parameter: click.Parameter,
    value: str,
) -> str:
    stream = context.find_root().ensure_object(DiagnosticStream)
    stream.format = value
    command = context.command_path.removeprefix("cli ")
    stream.command = (
        "launch"
        if command.endswith(LAUNCH_COMMAND)
        else command.removeprefix("marimo-studio ")
    )
    return value


diagnostic_format_option = click.option(
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
def capture_runtime_stderr() -> Iterator[None]:
    """Relay native runtime stderr as structured diagnostics."""
    stream = diagnostics()
    if stream.format != "jsonl":
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
                stream.emit(
                    code="process-output",
                    message=line,
                    severity="warning",
                )


def run_in_environment(target: EnvironmentTarget, args: list[str]) -> int:
    """Run the current CLI command in the notebook's uv environment."""
    stream = diagnostics()
    errors_before = stream.error_count
    exit_code = run_in_notebook_environment(
        target,
        args,
        diagnostic_line=stream.relay if stream.format == "jsonl" else None,
    )
    if exit_code and stream.format == "jsonl" and stream.error_count == errors_before:
        stream.emit(
            code="notebook-environment-error",
            message="Notebook environment exited before the command completed",
            severity="error",
            exit_code=exit_code,
        )
    return exit_code
