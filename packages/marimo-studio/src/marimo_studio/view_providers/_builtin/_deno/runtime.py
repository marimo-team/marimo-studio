"""Run the installed Deno executable inside one view project boundary."""

from __future__ import annotations

import os
import re
from collections.abc import Iterable, Mapping
from importlib import import_module
from importlib.metadata import PackageNotFoundError, distribution
from importlib.metadata import version as distribution_version
from pathlib import Path, PurePosixPath

from marimo_studio.view_providers import (
    ProviderAvailability,
    ProviderCancellation,
    ProviderCommandError,
    ProviderCommandResult,
    ProviderRunner,
    ViewProject,
    probe_tool,
)
from marimo_studio.view_providers._builtin._deno.cache import ensure_cache_directory


def permission_paths(*paths: Path) -> str:
    """Encode filesystem allowlists using Deno's doubled-comma escaping."""
    return ",".join(str(path.resolve()).replace(",", ",,") for path in paths)


DENO_MIN_VERSION = "2.9.5"
INSTALL_ACTION = (
    "Install marimo-studio[deno] in the Python environment that runs Studio."
)
DOWNLOAD_FAILURE_HINT = (
    "Deno could not download a package. Check the network connection and any "
    "proxy or npm registry settings, then build the view again."
)
# Deno's messages for a failed npm tarball, npm registry metadata request,
# esbuild or TypeScript compiler tarball, and fetch, as Deno formats them.
_DOWNLOAD_FAILURE = re.compile(
    r"Failed caching npm package '"
    r"|Failed loading https?://\S+ for package \""
    r"|failed to download (?:esbuild package|the TypeScript compiler) tarball"
    r"|error sending request (?:for url \(|from \S+ for )"
)
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


def download_failed(output: str) -> bool:
    """Return whether Deno output reports a failed package download."""
    return _DOWNLOAD_FAILURE.search(output) is not None


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
        binary = deno_binary()
    except (ModuleNotFoundError, FileNotFoundError):
        return ProviderAvailability(
            False,
            reason="The deno Python package is not installed.",
            action=INSTALL_ACTION,
        )
    return probe_tool(
        (binary, "--version"),
        minimum=DENO_MIN_VERSION,
        install=INSTALL_ACTION,
        environment=_filtered_environment(),
    )


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
