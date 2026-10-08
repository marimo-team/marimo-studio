"""List project files, copy build inputs, and check external tools for providers."""

from __future__ import annotations

import os
import re
import shutil
import threading
from collections.abc import Collection, Mapping, Sequence
from pathlib import Path, PurePosixPath

from packaging.version import InvalidVersion, Version

from marimo_studio._filesystem.budgets import BUILD_INPUT_BUDGET
from marimo_studio._filesystem.paths import validate_relative_path
from marimo_studio._filesystem.tree import bounded_regular_files
from marimo_studio._processes.cancellation import current_provider_cancellation
from marimo_studio._processes.supervisor import (
    ProcessCleanupError,
    ProcessResult,
    ProcessSupervisor,
)
from marimo_studio.errors import ConfigurationError
from marimo_studio.view_providers._records import (
    BuildRequest,
    ProviderAvailability,
    ProviderError,
    ViewProject,
)

STUDIO_FILES = frozenset(
    {
        PurePosixPath("view.toml"),
        PurePosixPath(".gitignore"),
        PurePosixPath("AGENTS.md"),
        PurePosixPath("DESIGN.md"),
    }
)
_VERSION = re.compile(r"\d+(?:\.\d+)+")


def project_path(value: object, *, field: str = "Project path") -> PurePosixPath:
    """Return ``value`` as a normalized project-relative POSIX path.

    Raises ``ValueError`` for absolute paths, ``..`` segments, backslashes,
    and names that are not portable across operating systems.
    """
    return validate_relative_path(value, field=field)


def project_files(
    project: ViewProject,
    *,
    roots: Collection[str] | None = None,
    exclude: Collection[str] = (),
) -> tuple[PurePosixPath, ...]:
    """Return the project's regular files that can affect a build, sorted.

    ``roots`` limits the listing to these top-level entries. ``exclude`` skips
    top-level directories by name. Hidden top-level entries such as ``.env``,
    ``view.toml``, ``AGENTS.md``, and ``DESIGN.md`` are always skipped. Raises
    ``ProviderError`` for a symlink or a project over Studio's input limits.
    """
    root = project.root
    names = {entry.name for entry in os.scandir(root)}
    skipped = {
        name
        for name in names
        if name.startswith(".")
        or name in exclude
        or (roots is not None and name not in roots)
    }
    cancellation = current_provider_cancellation()
    try:
        files = bounded_regular_files(
            root,
            max_files=BUILD_INPUT_BUDGET.max_files,
            label="View project",
            excluded_roots=skipped,
            cancelled=(lambda: cancellation.cancelled) if cancellation else None,
        )
    except ConfigurationError as error:
        if cancellation is not None:
            cancellation.raise_if_cancelled("Listing the view project")
        raise ProviderError(str(error), code="build-input-invalid") from error
    return tuple(
        sorted(
            (
                path
                for path in (
                    PurePosixPath(item.relative_to(root).as_posix()) for item in files
                )
                if path not in STUDIO_FILES
                and not path.parts[0].startswith(".")
                and (roots is None or path.parts[0] in roots)
            ),
            key=PurePosixPath.as_posix,
        )
    )


def copy_inputs(request: BuildRequest, destination: Path) -> None:
    """Copy the build's input files, except ``view.toml``, into ``destination``."""
    destination.mkdir(parents=True, exist_ok=True)
    for path in request.inputs:
        request.cancellation.raise_if_cancelled("Copying the build inputs")
        if path == PurePosixPath("view.toml"):
            continue
        source = request.project.root.joinpath(*path.parts)
        if source.is_symlink() or not source.is_file():
            raise ProviderError(f"Build input {path} is unavailable.")
        target = destination.joinpath(*path.parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)


def probe_tool(
    command: Sequence[str],
    *,
    minimum: str,
    install: str,
    environment: Mapping[str, str] | None = None,
) -> ProviderAvailability:
    """Run a tool's version command and report whether it is new enough.

    ``command[0]`` is found on ``PATH`` unless it is a path. The version is the
    first dotted number the command prints. This process remembers a reported
    version until the executable changes. ``install`` tells the user how to
    install or update the tool. Raises ``ProviderCommandError`` when the
    operation is cancelled.
    """
    name = Path(command[0]).name
    found = shutil.which(command[0])
    if found is None:
        return ProviderAvailability(
            False,
            reason=f"Studio cannot find the {name} command.",
            action=install,
        )
    binary = str(Path(found).resolve())
    try:
        state = os.stat(binary)
    except OSError as error:
        return ProviderAvailability(False, reason=f"{name}: {error}", action=install)
    key = (
        (binary, *command[1:]),
        (state.st_ino, state.st_size, state.st_mtime_ns, state.st_ctime_ns),
        tuple(sorted(environment.items())) if environment is not None else None,
    )
    with _PROBES_LOCK:
        version = _PROBES.get(key)
    if version is None:
        try:
            version, problem = _reported_version(name, key[0], environment)
        except ProcessCleanupError:
            raise
        except OSError as error:
            return ProviderAvailability(
                False, reason=f"{name}: {error}", action=install
            )
        if version is None:
            return ProviderAvailability(False, reason=problem, action=install)
        with _PROBES_LOCK:
            _PROBES[key] = version
    try:
        current = Version(version) >= Version(minimum)
    except InvalidVersion:
        current = False
    if not current:
        return ProviderAvailability(
            False,
            version=version,
            reason=f"{name} {version} is older than {minimum}.",
            action=install,
        )
    return ProviderAvailability(True, version=version)


# Versions reported by executables, keyed by command, file identity, and
# environment. Failed and cancelled checks stay out so the next check retries.
_PROBES: dict[object, str] = {}
_PROBES_LOCK = threading.Lock()
_PROBE_TIMEOUT = 30.0


def _reported_version(
    name: str,
    command: tuple[str, ...],
    environment: Mapping[str, str] | None,
) -> tuple[str | None, str]:
    """Return the version ``command`` prints, or ``None`` and the reason it has none."""
    supervisor = ProcessSupervisor()
    cancellation = current_provider_cancellation()
    unregister = cancellation.register(supervisor.cancel) if cancellation else None
    failure: OSError | None = None
    completed: ProcessResult | None = None
    try:
        completed = supervisor.run(
            list(command),
            _PROBE_TIMEOUT,
            env=dict(environment) if environment is not None else None,
        )
    except ProcessCleanupError:
        raise
    except OSError as error:
        failure = error
    finally:
        if unregister is not None:
            unregister()
    if cancellation is not None:
        cancellation.raise_if_cancelled(f"The {name} version check")
    if failure is not None:
        raise failure
    assert completed is not None
    shown = " ".join([name, *command[1:]])
    if completed.timed_out:
        return None, f"{shown} did not finish within {_PROBE_TIMEOUT:g} seconds."
    if completed.returncode != 0:
        return None, f"{shown} exited with status {completed.returncode}."
    match = _VERSION.search(completed.stdout.decode("utf-8", errors="replace"))
    if match is None:
        return None, f"{shown} did not report a version."
    return match.group(0), ""
