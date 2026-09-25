"""Run the installed Deno executable inside one view project boundary."""

from __future__ import annotations

import os
from collections.abc import Iterable, Mapping
from functools import lru_cache
from importlib import import_module
from importlib.metadata import PackageNotFoundError, distribution
from importlib.metadata import version as distribution_version
from pathlib import Path, PurePosixPath

from packaging.version import InvalidVersion, Version

from marimo_studio._processes.cancellation import current_provider_cancellation
from marimo_studio._processes.provider_runner import ProviderCommandError
from marimo_studio._processes.supervisor import ProcessCleanupError, ProcessSupervisor
from marimo_studio.view_providers import (
    ProviderAvailability,
    ProviderCancellation,
    ProviderCommandResult,
    ProviderRunner,
    ViewProject,
)
from marimo_studio.view_providers._bundled._deno.cache import ensure_cache_directory


def permission_paths(*paths: Path) -> str:
    """Encode filesystem allowlists using Deno's doubled-comma escaping."""
    return ",".join(str(path.resolve()).replace(",", ",,") for path in paths)


DENO_MIN_VERSION = "2.9.5"
INSTALL_ACTION = (
    "Install marimo-studio[deno] in the Python environment that runs Studio."
)
_AVAILABILITY_TIMEOUT = 15.0
_SAFE_ENVIRONMENT = frozenset(
    {
        "COMSPEC",
        "PATHEXT",
        "SYSTEMDRIVE",
        "SYSTEMROOT",
        "TEMP",
        "TMP",
        "TMPDIR",
        "WINDIR",
    }
)
_NETWORK_ENVIRONMENT = frozenset(
    {
        "ALL_PROXY",
        "all_proxy",
        "DENO_CERT",
        "HTTP_PROXY",
        "http_proxy",
        "HTTPS_PROXY",
        "https_proxy",
        "NO_PROXY",
        "no_proxy",
        "SSL_CERT_DIR",
        "SSL_CERT_FILE",
    }
)


class DenoExecutionError(RuntimeError):
    """Deno could not start or finish inside its execution limit."""


class DenoExecution:
    """Adapt Deno commands to one request-owned runner."""

    def __init__(
        self,
        project: ViewProject,
        *,
        cache_root: Path,
        cancellation: ProviderCancellation,
        runner: ProviderRunner,
    ) -> None:
        self._project = project
        self._root = project.root.resolve()
        self._binary = deno_binary()
        self._cache_root = cache_root.absolute()
        self._cache_relative = PurePosixPath("deno") / distribution_version("deno")
        self._cancellation = cancellation
        self._runner = runner

    def run(
        self,
        arguments: Iterable[str],
        *,
        cwd: Path,
        timeout: float | None = None,
        environment: Mapping[str, str] | None = None,
        network_environment: bool = False,
    ) -> ProviderCommandResult:
        return self._run(
            tuple(arguments),
            cwd=cwd,
            timeout=timeout,
            environment=environment,
            network_environment=network_environment,
        )

    def _run(
        self,
        arguments: tuple[str, ...],
        *,
        cwd: Path,
        timeout: float | None,
        environment: Mapping[str, str] | None,
        network_environment: bool,
    ) -> ProviderCommandResult:
        working_directory = cwd.resolve()
        try:
            working_directory.relative_to(self._root)
        except ValueError as error:
            raise DenoExecutionError(
                f"Deno working directory is outside view {self._project.name!r}: {cwd}"
            ) from error
        try:
            cache = ensure_cache_directory(
                self._cache_root,
                self._cache_relative,
            )
        except (OSError, ValueError) as error:
            raise DenoExecutionError(str(error)) from error
        child_environment = _deno_environment(
            cache,
            network=network_environment,
        )
        if environment is not None:
            child_environment.update(environment)
        try:
            if timeout is None:
                completed = self._runner.run(
                    [self._binary, *arguments],
                    cwd=working_directory,
                    environment=child_environment,
                )
            else:
                completed = self._runner.run(
                    [self._binary, *arguments],
                    timeout=timeout,
                    cwd=working_directory,
                    environment=child_environment,
                )
        except ProviderCommandError as error:
            raise DenoExecutionError(str(error)) from error
        if self._cancellation.cancelled:
            raise DenoExecutionError("Deno build was cancelled")
        return completed


def create_execution(
    project: ViewProject,
    *,
    cache_root: Path,
    cancellation: ProviderCancellation,
    runner: ProviderRunner,
) -> DenoExecution:
    """Create one execution owner for a synchronous provider operation."""
    return DenoExecution(
        project,
        cache_root=cache_root,
        cancellation=cancellation,
        runner=runner,
    )


def deno_binary() -> str:
    """Return the executable installed by the optional Python dependency."""
    module = import_module("deno")
    find = getattr(module, "find_deno_bin", None)
    if not callable(find):
        raise FileNotFoundError("The deno package has no find_deno_bin function")
    try:
        binary = find()
    except FileNotFoundError:
        binary = None
    if isinstance(binary, str) and Path(binary).is_file():
        return binary
    try:
        installed = distribution("deno")
    except PackageNotFoundError as error:
        raise FileNotFoundError("The deno package is unavailable") from error
    candidates: list[Path] = []
    for package_path in installed.files or ():
        if package_path.name not in {"deno", "deno.exe"}:
            continue
        located = Path(package_path.locate())
        if located.is_file():
            candidates.append(located)
    if len(candidates) != 1:
        raise FileNotFoundError("The deno package executable is unavailable")
    return str(candidates[0])


def deno_availability() -> ProviderAvailability:
    """Report whether the installed Deno executable can run."""
    try:
        binary = str(Path(deno_binary()).resolve())
        stat = Path(binary).stat()
    except (ModuleNotFoundError, FileNotFoundError):
        return ProviderAvailability(
            False,
            reason="python-package-missing",
            action=INSTALL_ACTION,
        )
    except OSError as error:
        return ProviderAvailability(
            False,
            reason=f"deno-executable-failed: {error}",
            action=INSTALL_ACTION,
        )
    return _cached_availability(
        binary,
        stat.st_mtime_ns,
        stat.st_ctime_ns,
        stat.st_size,
        stat.st_ino,
        DENO_MIN_VERSION,
    )


@lru_cache(maxsize=8)
def _cached_availability(
    binary: str,
    modified_ns: int,
    changed_ns: int,
    size: int,
    inode: int,
    minimum_version: str,
) -> ProviderAvailability:
    del modified_ns, changed_ns, size, inode
    supervisor = ProcessSupervisor()
    cancellation = current_provider_cancellation()
    unregister = (
        cancellation.register(supervisor.cancel) if cancellation is not None else None
    )
    try:
        completed = supervisor.run(
            [binary, "--version"],
            _AVAILABILITY_TIMEOUT,
            env=_filtered_environment(),
        )
    except ProcessCleanupError:
        raise
    except OSError as error:
        if cancellation is not None and cancellation.cancelled:
            raise DenoExecutionError("Deno availability check was cancelled") from error
        return ProviderAvailability(
            False,
            reason=f"deno-executable-failed: {error}",
            action=INSTALL_ACTION,
        )
    finally:
        if unregister is not None:
            unregister()
    if cancellation is not None and cancellation.cancelled:
        raise DenoExecutionError("Deno availability check was cancelled")
    if completed.timed_out:
        return ProviderAvailability(
            False,
            reason=(
                "Deno version check exceeded its "
                f"{_AVAILABILITY_TIMEOUT:g} second limit"
            ),
            action=INSTALL_ACTION,
        )
    stdout = completed.stdout.decode(errors="replace")
    first_line = stdout.splitlines()[0] if stdout else ""
    fields = first_line.removeprefix("deno ").split()
    version = fields[0] if fields else ""
    try:
        supported = Version(version) >= Version(minimum_version)
    except InvalidVersion:
        supported = False
    if completed.returncode != 0 or not supported:
        found = version or "unknown"
        return ProviderAvailability(
            False,
            version=found,
            reason=f"requires Deno >= {minimum_version}, found {found}",
            action=INSTALL_ACTION,
        )
    return ProviderAvailability(True, version=version)


def _filtered_environment(
    names: frozenset[str] = _SAFE_ENVIRONMENT,
) -> dict[str, str]:
    return {name: os.environ[name] for name in names if name in os.environ}


def _deno_environment(cache: Path, *, network: bool) -> dict[str, str]:
    names = _SAFE_ENVIRONMENT | (_NETWORK_ENVIRONMENT if network else frozenset())
    environment = _filtered_environment(names)
    environment.update(
        {
            "CI": "1",
            "DENO_DIR": str(cache.resolve()),
            "DENO_NO_PROMPT": "1",
            "DENO_NO_UPDATE_CHECK": "1",
            "NO_COLOR": "1",
            "TERM": "dumb",
        }
    )
    return environment
