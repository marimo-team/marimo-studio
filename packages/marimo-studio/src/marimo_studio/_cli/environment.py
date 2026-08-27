"""Resolve and enter the uv environment selected by a CLI target."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable
from contextlib import ExitStack
from dataclasses import dataclass
from importlib.metadata import metadata
from pathlib import Path
from typing import Protocol, TextIO

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import Version

from marimo_studio._composition import create_environment_flag_builder
from marimo_studio._workspace.metadata import read_notebook_metadata
from marimo_studio._workspace.models import NotebookEnvironment
from marimo_studio.errors import ConfigurationError, DependencyError

SANDBOX_ENV = "MARIMO_STUDIO_SANDBOX_BOOTSTRAPPED"
_RESULT_CHANNEL_ENV = "MARIMO_STUDIO_RESULT_CHANNEL"
_DIAGNOSTIC_CHANNEL_ENV = "MARIMO_STUDIO_DIAGNOSTIC_CHANNEL"


class EnvironmentTarget(Protocol):
    @property
    def root(self) -> Path: ...

    @property
    def notebook(self) -> Path: ...


@dataclass(frozen=True)
class EnvironmentRunResult:
    """Return one re-entered CLI process status and trusted result document."""

    returncode: int
    result: str = ""


def has_project_environment(root: Path) -> bool:
    """Return whether ``root`` declares a Python project or uv workspace."""
    pyproject = root / "pyproject.toml"
    try:
        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return False
    except OSError as error:
        raise DependencyError(
            f"Could not read project metadata: {pyproject}"
        ) from error
    except UnicodeError as error:
        raise DependencyError(
            f"Project metadata must be UTF-8 text: {pyproject}"
        ) from error
    except tomllib.TOMLDecodeError as error:
        raise DependencyError(
            f"Invalid project metadata in {pyproject}: {error}"
        ) from error
    project = data.get("project")
    tool = data.get("tool")
    uv = tool.get("uv") if isinstance(tool, dict) else None
    return isinstance(project, dict) or (
        isinstance(uv, dict) and isinstance(uv.get("workspace"), dict)
    )


def environment_root(target: EnvironmentTarget) -> Path:
    return next(
        (
            parent
            for parent in target.notebook.parents
            if (parent / "pyproject.toml").is_file()
        ),
        target.root,
    )


def parse_notebook_environment(path: Path) -> NotebookEnvironment:
    data = read_notebook_metadata(path)
    if data is None:
        return NotebookEnvironment(
            requires_python=_package_python_requirement(),
            dependencies=(),
        )

    dependencies = data.get("dependencies", [])
    if not isinstance(dependencies, list) or not all(
        isinstance(item, str) for item in dependencies
    ):
        raise ConfigurationError("PEP 723 dependencies must be an array of strings")
    requires_python = data.get(
        "requires-python",
        _package_python_requirement(),
    )
    if not isinstance(requires_python, str):
        raise ConfigurationError("PEP 723 requires-python must be a string")
    try:
        SpecifierSet(requires_python)
    except InvalidSpecifier as error:
        raise ConfigurationError(
            f"Invalid requires-python constraint: {error}"
        ) from error
    return NotebookEnvironment(
        requires_python=requires_python,
        dependencies=tuple(dependencies),
    )


def _package_python_requirement() -> str:
    try:
        requirement = metadata("marimo-studio")["Requires-Python"]
    except KeyError as error:
        raise DependencyError(
            "marimo-studio package metadata has no Requires-Python"
        ) from error
    if requirement is None:
        raise DependencyError("marimo-studio package metadata has no Requires-Python")
    return requirement


def package_source_root() -> Path | None:
    candidate = Path(__file__).resolve().parents[3]
    pyproject = candidate / "pyproject.toml"
    if not pyproject.is_file():
        return None
    try:
        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError:
        return None
    if data.get("project", {}).get("name") != "marimo-studio":
        return None
    return candidate


def should_reenter(target: EnvironmentTarget, requested: bool | None) -> bool:
    if os.environ.get(SANDBOX_ENV) == "1":
        return False
    if requested is not None:
        return requested
    environment = parse_notebook_environment(target.notebook)
    current_python = Version(
        f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    )
    return (
        has_project_environment(environment_root(target))
        or bool(environment.dependencies)
        or not SpecifierSet(environment.requires_python).contains(
            current_python,
            prereleases=True,
        )
    )


def _run_command(
    command: list[str],
    child_env: dict[str, str],
    capture_result: bool,
    diagnostic_stream: Callable[[TextIO], None] | None,
    process_stream: Callable[[TextIO], None] | None,
) -> EnvironmentRunResult:
    if not capture_result and diagnostic_stream is None and process_stream is None:
        return EnvironmentRunResult(
            subprocess.run(command, env=child_env, check=False).returncode
        )
    with ExitStack() as stack:
        directory = Path(
            stack.enter_context(
                tempfile.TemporaryDirectory(prefix="marimo-studio-cli-")
            )
        )
        result_channel = directory / "result"
        diagnostic_channel = directory / "diagnostics"
        if capture_result:
            result_channel.touch()
            child_env[_RESULT_CHANNEL_ENV] = str(result_channel)
        if diagnostic_stream is not None:
            diagnostic_channel.touch()
            child_env[_DIAGNOSTIC_CHANNEL_ENV] = str(diagnostic_channel)
        stdout = (
            stack.enter_context(
                tempfile.TemporaryFile(
                    mode="w+t",
                    encoding="utf-8",
                    errors="replace",
                )
            )
            if capture_result
            else None
        )
        stderr = stack.enter_context(
            tempfile.TemporaryFile(
                mode="w+t",
                encoding="utf-8",
                errors="replace",
            )
        )
        result = subprocess.run(
            command,
            env=child_env,
            check=False,
            stdout=stdout,
            stderr=stderr,
        )
        captured_result = (
            result_channel.read_text(encoding="utf-8") if capture_result else ""
        )
        if diagnostic_stream is not None:
            with diagnostic_channel.open(
                mode="r",
                encoding="utf-8",
                errors="replace",
            ) as diagnostics:
                diagnostic_stream(diagnostics)
        if process_stream is not None:
            for output in (stdout, stderr):
                if output is None:
                    continue
                output.seek(0)
                process_stream(output)
        return EnvironmentRunResult(result.returncode, captured_result)


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
    compose_project = has_project_environment(root)
    if compose_project:
        command.extend(["--project", str(root)])
        if (root / "uv.lock").is_file():
            command.append("--frozen")
    source_root = package_source_root()
    package_requirement = None if source_root is not None else "marimo-studio"
    command.extend(
        create_environment_flag_builder()(
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
    capture_result: bool = False,
    diagnostic_stream: Callable[[TextIO], None] | None = None,
    process_stream: Callable[[TextIO], None] | None = None,
) -> EnvironmentRunResult:
    """Re-enter the CLI through the notebook's Python environment."""
    child_env = os.environ.copy()
    child_env[SANDBOX_ENV] = "1"
    child_env.pop("VIRTUAL_ENV", None)
    child_env.pop(_RESULT_CHANNEL_ENV, None)
    child_env.pop(_DIAGNOSTIC_CHANNEL_ENV, None)
    command = environment_command(
        target,
        ["marimo-studio", *args],
        quiet=capture_result or diagnostic_stream is not None,
    )
    return _run_command(
        command,
        child_env,
        capture_result,
        diagnostic_stream,
        process_stream,
    )
