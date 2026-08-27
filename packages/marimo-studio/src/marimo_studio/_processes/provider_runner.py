"""Compose provider commands with Studio process ownership."""

from __future__ import annotations

import math
import os
from collections.abc import Mapping, Sequence
from pathlib import Path
from time import monotonic

from marimo_studio._processes.supervisor import ProcessCleanupError, ProcessSupervisor
from marimo_studio.view_providers import (
    ProviderCancellation,
    ProviderCommandResult,
    ProviderRunner,
    ViewProject,
)


class ProviderCommandError(RuntimeError):
    """A supervised provider command could not complete safely."""


DEFAULT_PROVIDER_COMMAND_TIMEOUT = 120.0


def _positive_finite_timeout(value: object) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value <= 0
    ):
        raise ProviderCommandError(
            "Provider command timeout must be a finite positive number"
        )
    return float(value)


class _SupervisedProviderRunner:
    def __init__(
        self,
        project: ViewProject,
        cancellation: ProviderCancellation,
        command_timeout: float,
        *,
        owns_process_tree: bool,
    ) -> None:
        self._root = project.root.resolve()
        self._cancellation = cancellation
        self._limit = _positive_finite_timeout(command_timeout)
        self._remaining = self._limit
        self._owns_process_tree = owns_process_tree

    def run(
        self,
        command: Sequence[str],
        *,
        cwd: Path,
        timeout: float = 120.0,
        environment: Mapping[str, str] | None = None,
    ) -> ProviderCommandResult:
        if not command or any(
            not isinstance(item, str) or not item for item in command
        ):
            raise ProviderCommandError(
                "Provider command arguments must be non-empty strings"
            )
        working_directory = cwd.resolve()
        try:
            working_directory.relative_to(self._root)
        except ValueError as error:
            raise ProviderCommandError(
                f"Provider working directory is outside the view snapshot: {cwd}"
            ) from error
        requested_timeout = _positive_finite_timeout(timeout)
        if self._cancellation.cancelled:
            raise ProviderCommandError("Provider operation was cancelled")
        if self._remaining <= 0:
            raise ProviderCommandError(
                "Provider commands exceeded their "
                f"{self._limit:g} second aggregate budget"
            )
        selected_timeout = min(requested_timeout, self._remaining)
        aggregate_limited = selected_timeout == self._remaining
        supervisor = (
            ProcessSupervisor()
            if self._owns_process_tree
            else ProcessSupervisor(owns_process_tree=False)
        )
        unregister = self._cancellation.register(supervisor.cancel)
        child_environment = (
            os.environ.copy() if environment is None else dict(environment)
        )
        started = monotonic()
        try:
            completed = supervisor.run(
                list(command),
                selected_timeout,
                cwd=working_directory,
                env=child_environment,
            )
        except (OSError, ProcessCleanupError) as error:
            raise ProviderCommandError(str(error)) from error
        finally:
            self._remaining = max(0.0, self._remaining - (monotonic() - started))
            unregister()
        if completed.timed_out:
            message = (
                "Provider commands exceeded their "
                f"{self._limit:g} second aggregate budget"
                if aggregate_limited
                else f"Provider command exceeded its {requested_timeout:g} second limit"
            )
            raise ProviderCommandError(message)
        if completed.output_too_large:
            raise ProviderCommandError(
                "Provider command produced more output than Studio accepts"
            )
        if self._cancellation.cancelled:
            raise ProviderCommandError("Provider operation was cancelled")
        return ProviderCommandResult(
            completed.returncode,
            completed.stdout.decode(errors="replace"),
            completed.stderr.decode(errors="replace"),
        )


def create_provider_runner(
    project: ViewProject,
    cancellation: ProviderCancellation,
    command_timeout: float = DEFAULT_PROVIDER_COMMAND_TIMEOUT,
    *,
    owns_process_tree: bool = True,
) -> ProviderRunner:
    """Create one supervised command runner for a provider request."""
    return _SupervisedProviderRunner(
        project,
        cancellation,
        command_timeout,
        owns_process_tree=owns_process_tree,
    )
