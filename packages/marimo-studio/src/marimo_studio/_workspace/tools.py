"""Give view providers the commands a notebook's pixi metadata declares.

A notebook whose PEP 723 metadata has a ``[tool.pixi]`` table describes a pixi
script environment, the one ``marimo edit --sandbox=pixi`` runs its kernel in.
Conda packages under ``[tool.pixi.dependencies]``, such as ``tectonic``,
install their executables there. Provider calls for that notebook search the
environment's executable directories before ``PATH``.

Studio installs the environment only where the user chose it. A process Marimo
runs with the pixi sandbox backend uses it for every notebook, because the
sandbox ignores an enclosing Python project. A Studio command uses it for the
standalone notebook it targets, and runs a project's notebook in that
project's environment.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path

from marimo_studio._processes.cancellation import current_provider_cancellation
from marimo_studio._processes.operation import ProviderCommandError
from marimo_studio._processes.supervisor import ProcessCleanupError, ProcessSupervisor
from marimo_studio._processes.tools import NO_TOOLS, ProviderTools, provider_tools
from marimo_studio._workspace.metadata import read_notebook_metadata
from marimo_studio._workspace.python_project import project_environment
from marimo_studio.errors import ConfigurationError, DependencyError

_LOGGER = logging.getLogger("marimo.studio")
# A first install downloads Python, the notebook's packages, and its tools.
INSTALL_TIMEOUT = 600.0
# A failed install runs again after this many seconds, for example once pixi
# is installed.
_RETRY = 60.0
_MAX_PROBLEM_CHARACTERS = 2_000
_COMMAND_INSTALLS: ContextVar[bool] = ContextVar(
    "marimo_studio_command_installs", default=False
)


@dataclass
class _Environment:
    """One notebook's environment, installed once per metadata revision."""

    lock: threading.Lock = field(default_factory=threading.Lock)
    revision: str | None = None
    directories: tuple[str, ...] = ()
    problem: str | None = None
    failed_at: float = 0.0


_LOCK = threading.Lock()
_ENVIRONMENTS: dict[Path, _Environment] = {}


@contextmanager
def command_installs() -> Iterator[None]:
    """Let provider calls in a Studio command install their notebook's environment."""
    token = _COMMAND_INSTALLS.set(True)
    try:
        yield
    finally:
        _COMMAND_INSTALLS.reset(token)


def _pixi_metadata(notebook: Path) -> Mapping[str, object] | None:
    """Return a notebook's PEP 723 metadata when it has a ``[tool.pixi]`` table."""
    try:
        document = read_notebook_metadata(notebook)
    except (ConfigurationError, OSError):
        return None
    if document is None:
        return None
    tool = document.get("tool")
    if not isinstance(tool, Mapping) or not isinstance(tool.get("pixi"), Mapping):
        return None
    return document.unwrap()


def _standalone(notebook: Path) -> bool:
    """Return whether no Python project owns the notebook's environment."""
    try:
        return project_environment(notebook) is None
    except (DependencyError, OSError):
        return False


def declares_pixi_environment(notebook: Path) -> bool:
    """Return whether a standalone notebook's metadata describes a pixi environment."""
    return _standalone(notebook) and _pixi_metadata(notebook) is not None


def _revision(metadata: Mapping[str, object]) -> str:
    """Return a digest of the metadata pixi installs from."""
    tool = metadata.get("tool")
    pixi = tool.get("pixi") if isinstance(tool, Mapping) else None
    relevant = {
        "dependencies": metadata.get("dependencies"),
        "requires-python": metadata.get("requires-python"),
        "pixi": pixi,
    }
    encoded = json.dumps(relevant, sort_keys=True, default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


def _acquire(lock: threading.Lock) -> None:
    """Wait for another call's install unless this provider call is cancelled."""
    cancellation = current_provider_cancellation()
    while not lock.acquire(timeout=0.1):
        if cancellation is not None and cancellation.cancelled:
            raise ProviderCommandError("Provider operation was cancelled")


def _install(notebook: Path) -> tuple[str, ...]:
    """Install the notebook's environment and return its executable directories.

    Raises ``DependencyError`` when pixi is missing or the install fails, and
    ``ProviderCommandError`` when the provider call is cancelled.
    """
    from marimo_studio._composition import create_script_environments

    install = create_script_environments().install(notebook)
    supervisor = ProcessSupervisor()
    cancellation = current_provider_cancellation()
    unregister = cancellation.register(supervisor.cancel) if cancellation else None
    try:
        completed = supervisor.run(
            list(install.command),
            INSTALL_TIMEOUT,
            cwd=notebook.parent,
            env=install.environment,
        )
    except ProcessCleanupError:
        raise
    except OSError as error:
        raise DependencyError(f"pixi could not start: {error}") from error
    finally:
        if unregister is not None:
            unregister()
    if cancellation is not None and cancellation.cancelled:
        raise ProviderCommandError("Provider operation was cancelled")
    report = completed.stderr.decode(errors="replace")
    if completed.timed_out:
        raise DependencyError(
            f"pixi did not install the environment within {INSTALL_TIMEOUT:g} seconds."
        )
    if completed.returncode != 0 or completed.output_too_large:
        raise DependencyError(
            report.strip()[-_MAX_PROBLEM_CHARACTERS:]
            or f"pixi exited with status {completed.returncode}."
        )
    return install.executable_directories(report)


def notebook_provider_tools(notebook: Path) -> ProviderTools:
    """Return the tools the notebook's pixi metadata provides to provider calls.

    Returns no directories for a notebook without ``[tool.pixi]`` metadata and
    where the user has not chosen its pixi environment. A failed install leaves
    the directories empty and names the failure in ``ProviderTools.problem``.
    """
    metadata = _pixi_metadata(notebook)
    if metadata is None:
        return NO_TOOLS
    if _COMMAND_INSTALLS.get():
        if not _standalone(notebook):
            return NO_TOOLS
    else:
        from marimo_studio._composition import create_script_environments

        if not create_script_environments().selected():
            return NO_TOOLS
    path = notebook.resolve()
    revision = _revision(metadata)
    identity = f"{path}\0{revision}"
    with _LOCK:
        environment = _ENVIRONMENTS.setdefault(path, _Environment())
    _acquire(environment.lock)
    try:
        if environment.revision == revision:
            # `pixi clean cache` removes an environment Studio installed before.
            if environment.directories and Path(environment.directories[0]).is_dir():
                return ProviderTools(environment.directories, identity)
            if time.monotonic() - environment.failed_at < _RETRY:
                return ProviderTools((), identity, environment.problem)
        try:
            directories = _install(path)
        except DependencyError as error:
            _LOGGER.warning(
                "Studio cannot use the pixi environment of %s: %s", notebook, error
            )
            environment.revision = revision
            environment.directories = ()
            environment.problem = str(error)
            environment.failed_at = time.monotonic()
            return ProviderTools((), identity, environment.problem)
        environment.revision = revision
        environment.directories = directories
        environment.problem = None
        return ProviderTools(directories, identity)
    finally:
        environment.lock.release()


@contextmanager
def notebook_tools(notebook: Path | None) -> Iterator[None]:
    """Search the notebook's pixi environment first for provider calls.

    ``None`` leaves provider calls on ``PATH``, for work that serves no notebook.
    """
    tools = (
        notebook_provider_tools(notebook) if notebook is not None else ProviderTools()
    )
    with provider_tools(tools):
        yield
