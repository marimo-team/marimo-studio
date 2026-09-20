"""Emit human and JSON Lines diagnostics for CLI commands."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from collections.abc import Iterator, Mapping
from contextlib import ExitStack, contextmanager, redirect_stderr, redirect_stdout
from dataclasses import dataclass, field
from io import StringIO
from threading import Lock
from typing import TYPE_CHECKING, TextIO

import click

from marimo_studio._cli.environment import (
    _DIAGNOSTIC_CHANNEL_ENV,
    _RESULT_CHANNEL_ENV,
    SANDBOX_ENV,
    EnvironmentTarget,
    run_in_notebook_environment,
)
from marimo_studio.errors import DependencyError

if TYPE_CHECKING:
    from marimo_studio._delivery.progress import StaticExportProgress

_MAX_PROCESS_OUTPUT_CHARS = 16 * 1024
_MAX_DIAGNOSTIC_EVENT_CHARS = 64 * 1024


@dataclass
class _PlainOutput:
    line_count: int = 0
    char_count: int = 0
    tail: str = ""
    has_content: bool = False

    def append(self, line: str) -> None:
        piece = f"\n{line}" if self.line_count else line
        self.line_count += 1
        self.char_count += len(piece)
        self.has_content = self.has_content or bool(line.strip())
        if len(piece) >= _MAX_PROCESS_OUTPUT_CHARS:
            self.tail = piece[-_MAX_PROCESS_OUTPUT_CHARS:]
        else:
            self.tail = (self.tail + piece)[-_MAX_PROCESS_OUTPUT_CHARS:]

    def append_text(self, value: str) -> None:
        self.line_count += value.count("\n")
        self.char_count += len(value)
        self.has_content = self.has_content or bool(value.strip())
        self.tail = (self.tail + value)[-_MAX_PROCESS_OUTPUT_CHARS:]


@dataclass
class DiagnosticStream:
    """Write structured diagnostics to stderr when JSON Lines is selected."""

    format: str = "text"
    command: str | None = None
    error_count: int = 0
    result_stream: TextIO | None = None
    diagnostic_stream: TextIO | None = None
    _owned_streams: tuple[TextIO, ...] = field(default=(), repr=False)
    _write_lock: Lock = field(default_factory=Lock, repr=False)

    def _write(self, event: dict[str, object]) -> None:
        with self._write_lock:
            click.echo(
                json.dumps(
                    event,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                ),
                file=self.diagnostic_stream,
                err=self.diagnostic_stream is None,
            )

    def write_activity(self, message: str) -> None:
        click.echo(
            message, file=self.diagnostic_stream, err=self.diagnostic_stream is None
        )

    def relay_activity_stream(self, output: TextIO) -> None:
        for line in output:
            self.write_activity(line.rstrip("\r\n"))

    def emit(
        self,
        *,
        code: str,
        message: str,
        severity: str,
        exit_code: int | None = None,
        status: str | None = None,
        details: Mapping[str, object] | None = None,
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
        if details:
            event["details"] = dict(details)
        self._write(event)
        return True

    def emit_progress(self, progress: StaticExportProgress) -> None:
        """Write export progress to stderr without changing result stdout."""
        if self.format == "jsonl":
            self._write(
                {
                    "schema": 1,
                    "event": "progress",
                    "command": self.command,
                    "progress": progress.to_dict(),
                }
            )
            return
        self.write_activity(progress.format_message())

    def _trusted_event(self, line: str) -> dict[str, object] | None:
        if len(line) > _MAX_DIAGNOSTIC_EVENT_CHARS:
            return None
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            return None
        diagnostic = (
            isinstance(event, dict)
            and type(event.get("schema")) is int
            and event.get("schema") == 1
            and event.get("event") == "diagnostic"
            and event.get("severity") in {"info", "warning", "error"}
            and isinstance(event.get("code"), str)
            and isinstance(event.get("message"), str)
            and event.get("command") == self.command
        )
        progress_value = event.get("progress") if isinstance(event, dict) else None
        progress_event = (
            progress_value.get("event") if isinstance(progress_value, dict) else None
        )
        progress = (
            isinstance(event, dict)
            and type(event.get("schema")) is int
            and event.get("schema") == 1
            and event.get("event") == "progress"
            and event.get("command") == self.command
            and isinstance(progress_value, dict)
            and progress_value.get("source") in {"marimo-export", "marimo-studio"}
            and isinstance(progress_value.get("view"), str)
            and progress_value.get("runtime") in {"zero-python", "wasm"}
            and isinstance(progress_event, dict)
            and isinstance(progress_event.get("kind"), str)
        )
        if diagnostic or progress:
            return event
        return None

    def _relay_event(self, event: dict[str, object]) -> None:
        if event.get("event") == "diagnostic" and event["severity"] == "error":
            self.error_count += 1
        self._write(event)

    def _relay_plain(self, output: _PlainOutput) -> None:
        if not output.has_content:
            return
        details: dict[str, object] = {"line_count": output.line_count}
        if output.char_count > _MAX_PROCESS_OUTPUT_CHARS:
            prefix = "[Earlier process output omitted]\n"
            retained = _MAX_PROCESS_OUTPUT_CHARS - len(prefix)
            details["omitted_chars"] = output.char_count - retained
            message = prefix + output.tail[-retained:].rstrip()
            details["truncated"] = True
        else:
            message = output.tail.strip()
        self.emit(
            code="process-output",
            message=message,
            severity="warning",
            details=details,
        )

    def relay_trusted_output(self, output: str) -> None:
        """Relay diagnostics emitted by a re-entered Studio CLI."""
        self.relay_trusted_stream(StringIO(output))

    def relay_trusted_stream(self, output: TextIO) -> None:
        """Relay bounded diagnostics from a trusted Studio stream."""
        plain = _PlainOutput()
        for record in output:
            line = record.removesuffix("\n").removesuffix("\r")
            event = self._trusted_event(line)
            if event is None:
                plain.append(line)
                continue
            self._relay_plain(plain)
            plain = _PlainOutput()
            self._relay_event(event)
        self._relay_plain(plain)

    def write_result(self, value: str) -> None:
        click.echo(value, file=self.result_stream)

    def relay_process_stream(self, output: TextIO) -> None:
        """Relay uncontrolled extension output without trusting its contents."""
        plain = _PlainOutput()
        last_character = ""
        while chunk := output.read(8192):
            plain.append_text(chunk)
            last_character = chunk[-1]
        if plain.char_count and last_character != "\n":
            plain.line_count += 1
        if not plain.has_content:
            return
        if self.format == "jsonl":
            self._relay_plain(plain)
            return
        message = plain.tail.rstrip()
        if plain.char_count > _MAX_PROCESS_OUTPUT_CHARS:
            message = f"[Earlier process output omitted]\n{message}"
        click.echo(message, err=True)

    def relay_captured_stdout(self, output: TextIO) -> None:
        self.relay_process_stream(output)

    def close(self) -> None:
        for output in self._owned_streams:
            output.close()
        self._owned_streams = ()


def _open_child_channel(variable: str) -> TextIO | None:
    channel = os.environ.pop(variable, None)
    if channel is None or os.environ.get(SANDBOX_ENV) != "1":
        return None
    return open(
        channel,
        mode="a",
        encoding="utf-8",
        errors="replace",
        buffering=1,
    )


def diagnostics_from_argv(args: list[str]) -> DiagnosticStream:
    """Create the root diagnostic stream before Click parses arguments."""
    result_stream = _open_child_channel(_RESULT_CHANNEL_ENV)
    diagnostic_stream = _open_child_channel(_DIAGNOSTIC_CHANNEL_ENV)
    stream = DiagnosticStream(
        command="marimo-studio",
        result_stream=result_stream,
        diagnostic_stream=diagnostic_stream,
        _owned_streams=tuple(
            output
            for output in (result_stream, diagnostic_stream)
            if output is not None
        ),
    )
    for argument in args:
        if argument == "--":
            break
        if argument == "--json":
            stream.format = "jsonl"
            break
    return stream


def diagnostics() -> DiagnosticStream:
    """Return the diagnostic stream attached to the root Click context."""
    return click.get_current_context().find_root().ensure_object(DiagnosticStream)


def _configure_json(
    context: click.Context,
    _parameter: click.Parameter,
    value: bool,
) -> bool:
    stream = context.find_root().ensure_object(DiagnosticStream)
    if value:
        stream.format = "jsonl"
    command = context.command_path.removeprefix("cli ")
    stream.command = command.removeprefix("marimo-studio ")
    return value


json_option = click.option(
    "--json",
    "json_output",
    is_flag=True,
    is_eager=True,
    callback=_configure_json,
    help="Write JSON to stdout and JSON Lines diagnostics to stderr.",
)


@contextmanager
def capture_runtime_stderr() -> Iterator[None]:
    """Relay native runtime stderr as structured diagnostics."""
    stream = diagnostics()
    if stream.format != "jsonl":
        yield
        return
    try:
        sys.stderr.fileno()
    except (AttributeError, OSError, ValueError):
        captured = StringIO()
        with redirect_stderr(captured):
            yield
        stream.relay_trusted_output(captured.getvalue())
        return
    with tempfile.TemporaryFile(
        mode="w+t",
        encoding="utf-8",
        errors="replace",
    ) as captured:
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
            stream.relay_process_stream(captured)


@contextmanager
def capture_command_output(
    stream: DiagnosticStream,
    *,
    capture_stdout: bool,
    capture_stderr: bool,
) -> Iterator[None]:
    """Isolate machine descriptors and relay bounded extension output."""
    if not capture_stdout and not capture_stderr:
        yield
        return
    configured_result = stream.result_stream
    configured_diagnostics = stream.diagnostic_stream
    try:
        sys.stdout.fileno()
        sys.stderr.fileno()
    except (AttributeError, OSError):
        with (
            tempfile.TemporaryFile(
                mode="w+t",
                encoding="utf-8",
                errors="replace",
            ) as out,
            tempfile.TemporaryFile(
                mode="w+t",
                encoding="utf-8",
                errors="replace",
            ) as error,
            ExitStack() as redirects,
        ):
            result_destination = (
                configured_result
                if configured_result is not None
                else sys.stdout
                if capture_stdout
                else None
            )
            diagnostic_destination = (
                configured_diagnostics
                if configured_diagnostics is not None
                else sys.stderr
                if capture_stderr
                else None
            )
            stream.result_stream = result_destination
            stream.diagnostic_stream = diagnostic_destination
            if capture_stdout:
                redirects.enter_context(redirect_stdout(out))
            if capture_stderr:
                redirects.enter_context(redirect_stderr(error))
            try:
                yield
            finally:
                try:
                    if capture_stdout:
                        out.seek(0)
                        stream.relay_captured_stdout(out)
                    if capture_stderr:
                        error.seek(0)
                        stream.relay_process_stream(error)
                finally:
                    stream.result_stream = configured_result
                    stream.diagnostic_stream = configured_diagnostics
        return
    with (
        tempfile.TemporaryFile(mode="w+t", encoding="utf-8", errors="replace") as out,
        tempfile.TemporaryFile(mode="w+t", encoding="utf-8", errors="replace") as error,
        os.fdopen(os.dup(1), "w", encoding="utf-8", closefd=True) as result,
        os.fdopen(
            os.dup(2),
            "w",
            encoding="utf-8",
            closefd=True,
        ) as diagnostic,
        ExitStack() as redirects,
    ):
        stdout_fd = 1
        stderr_fd = 2
        result_destination = (
            configured_result
            if configured_result is not None
            else result
            if capture_stdout
            else None
        )
        diagnostic_destination = (
            configured_diagnostics
            if configured_diagnostics is not None
            else diagnostic
            if capture_stderr
            else None
        )
        stream.result_stream = result_destination
        stream.diagnostic_stream = diagnostic_destination
        sys.stdout.flush()
        sys.stderr.flush()
        if capture_stdout:
            os.dup2(out.fileno(), stdout_fd)
            redirects.enter_context(redirect_stdout(out))
        if capture_stderr:
            os.dup2(error.fileno(), stderr_fd)
            redirects.enter_context(redirect_stderr(error))
        try:
            yield
        finally:
            sys.stdout.flush()
            sys.stderr.flush()
            result.flush()
            diagnostic.flush()
            if capture_stdout:
                os.dup2(result.fileno(), stdout_fd)
            if capture_stderr:
                os.dup2(diagnostic.fileno(), stderr_fd)
            try:
                if capture_stdout:
                    out.seek(0)
                    stream.relay_captured_stdout(out)
                if capture_stderr:
                    error.seek(0)
                    stream.relay_process_stream(error)
            finally:
                stream.result_stream = configured_result
                stream.diagnostic_stream = configured_diagnostics


def run_in_environment(target: EnvironmentTarget, args: list[str]) -> int:
    """Run the current CLI command in the notebook's uv environment."""
    stream = diagnostics()
    errors_before = stream.error_count
    machine_result = stream.format == "jsonl"
    completed = run_in_notebook_environment(
        target,
        args,
        capture_result=machine_result,
        diagnostic_stream=(
            stream.relay_trusted_stream
            if stream.format == "jsonl"
            else stream.relay_activity_stream
        ),
        process_stream=stream.relay_process_stream,
    )
    if machine_result and completed.result.strip():
        try:
            json.loads(completed.result)
        except json.JSONDecodeError as error:
            stream.relay_process_stream(StringIO(completed.result))
            if completed.returncode in {0, 1}:
                raise DependencyError(
                    "Notebook environment returned an invalid JSON result"
                ) from error
        else:
            stream.write_result(completed.result.rstrip("\r\n"))
    elif machine_result and completed.returncode in {0, 1}:
        raise DependencyError("Notebook environment returned no JSON result")
    exit_code = completed.returncode
    if exit_code and stream.format == "jsonl" and stream.error_count == errors_before:
        stream.emit(
            code="notebook-environment-error",
            message="Notebook environment exited before the command completed",
            severity="error",
            exit_code=exit_code,
        )
    return exit_code
