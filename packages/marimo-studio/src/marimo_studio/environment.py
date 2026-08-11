"""Run Studio commands in a notebook's uv environment."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from collections.abc import Callable
from typing import TextIO

from marimo_studio._composition import create_tooling_adapters
from marimo_studio._workspace.environment import (
    SANDBOX_ENV,
    EnvironmentTarget,
    environment_root,
    package_source_root,
)
from marimo_studio.errors import DependencyError


def _run_command(
    command: list[str],
    child_env: dict[str, str],
    diagnostic_stream: Callable[[TextIO], None] | None,
) -> int:
    if diagnostic_stream is None:
        return subprocess.run(command, env=child_env, check=False).returncode
    with tempfile.TemporaryFile(
        mode="w+t",
        encoding="utf-8",
        errors="replace",
    ) as stderr:
        result = subprocess.run(
            command,
            env=child_env,
            check=False,
            stderr=stderr,
        )
        stderr.seek(0)
        diagnostic_stream(stderr)
        return result.returncode


def environment_command(
    target: EnvironmentTarget,
    args: list[str],
    *,
    quiet: bool = False,
) -> list[str]:
    """Build the uv command for a notebook environment."""
    uv = shutil.which("uv")
    if uv is None:
        raise DependencyError("uv is required for notebook environment execution")

    command = [uv, "run"]
    if quiet:
        command.append("--quiet")
    root = environment_root(target)
    pyproject = root / "pyproject.toml"
    compose_project = pyproject.is_file()
    if compose_project:
        command.extend(["--project", str(root)])
        if (root / "uv.lock").is_file():
            command.append("--frozen")
    source_root = package_source_root()
    package_requirement = None if source_root is not None else "marimo-studio"
    command.extend(
        create_tooling_adapters().environment(
            target.notebook,
            package_requirement,
            compose_project=compose_project,
        )
    )
    if source_root is not None:
        command.extend(["--with-editable", str(source_root)])
    command.extend(["--", *args])
    return command


def run_in_notebook_environment(
    target: EnvironmentTarget,
    args: list[str],
    *,
    diagnostic_stream: Callable[[TextIO], None] | None = None,
) -> int:
    """Re-enter the CLI through the notebook's Python environment."""
    child_env = os.environ.copy()
    child_env[SANDBOX_ENV] = "1"
    child_env.pop("VIRTUAL_ENV", None)
    command = environment_command(
        target,
        ["marimo-studio", *args],
        quiet=diagnostic_stream is not None,
    )
    return _run_command(command, child_env, diagnostic_stream)


__all__ = ["environment_command", "run_in_notebook_environment"]
