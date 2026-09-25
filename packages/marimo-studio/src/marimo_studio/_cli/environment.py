"""Resolve and enter the uv environment selected by a CLI target."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable, Iterator
from contextlib import ExitStack, contextmanager, nullcontext
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, metadata, requires, version
from io import StringIO
from pathlib import Path
from threading import Event, Thread
from typing import Protocol, TextIO

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

from packaging.markers import default_environment
from packaging.requirements import InvalidRequirement, Requirement
from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.utils import canonicalize_name
from packaging.version import Version

from marimo_studio._composition import create_environment_flag_builder
from marimo_studio._workspace.config import (
    discover_studio_definition,
    discover_views,
)
from marimo_studio._workspace.environment_requirements import (
    MarkerEnvironment,
    allows_source_checkout,
    bootstrap_launch_requirements,
    dependency_constraint,
    studio_dependency_constraint,
    uses_dependency_source,
)
from marimo_studio._workspace.installation import invoking_studio
from marimo_studio._workspace.metadata import read_notebook_metadata
from marimo_studio._workspace.models import NotebookEnvironment, StudioWorkspace
from marimo_studio._workspace.python_project import (
    declares_project_environment as _declares_project_environment,
)
from marimo_studio._workspace.python_project import (
    has_project_environment,
)
from marimo_studio._workspace.python_project import (
    project_metadata as _project_metadata,
)
from marimo_studio.errors import ConfigurationError, DependencyError
from marimo_studio.view_providers._host.package_policy import (
    BUNDLED_PROVIDER_REQUIREMENTS,
)

SANDBOX_ENV = "MARIMO_STUDIO_SANDBOX_BOOTSTRAPPED"
_RESULT_CHANNEL_ENV = "MARIMO_STUDIO_RESULT_CHANNEL"
_DIAGNOSTIC_CHANNEL_ENV = "MARIMO_STUDIO_DIAGNOSTIC_CHANNEL"
_STUDIO_DISTRIBUTION = canonicalize_name("marimo-studio")


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


@dataclass(frozen=True)
class _BootstrapEnvironment:
    launch_requirements: tuple[str, ...]
    marker_environment: MarkerEnvironment | None
    uses_declared_source: bool


@dataclass(frozen=True)
class _ProviderEnvironmentTarget:
    root: Path
    notebook: Path
    provider_ids: tuple[str, ...]


def include_provider_ids(
    target: EnvironmentTarget,
    provider_ids: tuple[str, ...],
) -> EnvironmentTarget:
    """Include providers selected before they are saved to the workspace."""
    existing = (
        target.provider_ids if isinstance(target, _ProviderEnvironmentTarget) else ()
    )
    return _ProviderEnvironmentTarget(
        root=target.root,
        notebook=target.notebook,
        provider_ids=tuple(sorted({*existing, *provider_ids})),
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


def _read_target_notebook_metadata(path: Path) -> dict[str, object] | None:
    try:
        data = read_notebook_metadata(path)
    except FileNotFoundError as error:
        raise ConfigurationError(f"Target does not exist: {path}") from error
    except OSError as error:
        raise ConfigurationError(f"Could not read notebook: {path}") from error
    except UnicodeError as error:
        raise ConfigurationError(f"Notebook must be UTF-8 text: {path}") from error
    return dict(data) if data is not None else None


def parse_notebook_environment(path: Path) -> NotebookEnvironment:
    data = _read_target_notebook_metadata(path)
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


def _package_version() -> Version:
    try:
        package_version = metadata("marimo-studio")["Version"]
    except KeyError as error:
        raise DependencyError(
            "marimo-studio package metadata has no version"
        ) from error
    if package_version is None:
        raise DependencyError("marimo-studio package metadata has no version")
    return Version(package_version)


def _dependency_values(metadata: dict[str, object]) -> tuple[str, ...]:
    project = metadata.get("project")
    values = (
        project.get("dependencies", ())
        if isinstance(project, dict)
        else metadata.get("dependencies", ())
    )
    if not isinstance(values, list | tuple) or not all(
        isinstance(value, str) for value in values
    ):
        raise ConfigurationError("Python dependencies must be an array of strings")
    return tuple(values)


def _provider_distributions(provider_ids: tuple[str, ...]) -> frozenset[str]:
    names = {_STUDIO_DISTRIBUTION}
    for provider_id in provider_ids:
        distribution, separator, _registration = provider_id.partition("/")
        if not separator:
            raise ConfigurationError(f"Invalid view provider identity: {provider_id!r}")
        names.add(canonicalize_name(distribution))
    return frozenset(names)


def _target_marker_environment(
    notebook_metadata: dict[str, object],
    project_metadata: dict[str, object] | None,
    provider_ids: tuple[str, ...],
) -> MarkerEnvironment | None:
    distributions = _provider_distributions(provider_ids)
    documents = (
        (notebook_metadata,)
        if project_metadata is None
        else (
            notebook_metadata,
            project_metadata,
        )
    )
    has_markers = False
    for document in documents:
        for value in _dependency_values(document):
            try:
                requirement = Requirement(value)
            except InvalidRequirement:
                continue
            if (
                canonicalize_name(requirement.name) in distributions
                and requirement.marker is not None
            ):
                has_markers = True
                break
    if not has_markers:
        return None
    environment = default_environment()
    current = Version(environment["python_full_version"])
    requires_python = [notebook_metadata.get("requires-python")]
    if project_metadata is not None:
        project = project_metadata.get("project")
        if isinstance(project, dict):
            requires_python.append(project.get("requires-python"))
    for value in requires_python:
        if value is None:
            continue
        if not isinstance(value, str):
            raise ConfigurationError("requires-python must be a string")
        try:
            compatible = SpecifierSet(value).contains(current, prereleases=True)
        except InvalidSpecifier as error:
            raise ConfigurationError(
                f"Invalid requires-python constraint: {error}"
            ) from error
        if not compatible:
            raise ConfigurationError(
                "Cannot evaluate dependency markers because uv must select a "
                "different target Python"
            )
    return {key: str(value) for key, value in environment.items()}


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


def _bootstrap_requirements(
    target: EnvironmentTarget,
    *,
    project_metadata: dict[str, object] | None,
) -> _BootstrapEnvironment:
    notebook_metadata = _read_target_notebook_metadata(target.notebook) or {}
    provider_ids = _target_provider_ids(target)
    marker_environment = _target_marker_environment(
        notebook_metadata,
        project_metadata,
        provider_ids,
    )
    requirements = bootstrap_launch_requirements(
        studio_requirement=f"marimo-studio=={_package_version()}",
        provider_ids=provider_ids,
        bundled_requirements=BUNDLED_PROVIDER_REQUIREMENTS,
        notebook_metadata=notebook_metadata,
        project_metadata=project_metadata,
        marker_environment=marker_environment,
    )
    documents = (
        (notebook_metadata,)
        if project_metadata is None
        else (notebook_metadata, project_metadata)
    )
    uses_declared_source = any(
        uses_dependency_source(
            dependency_constraint(document, Requirement(value).name),
            marker_environment=marker_environment,
        )
        for value in requirements
        for document in documents
    )
    return _BootstrapEnvironment(
        requirements,
        marker_environment,
        uses_declared_source,
    )


def _installed_requirement_satisfies(value: str) -> bool:
    requirement = Requirement(value)
    if requirement.url is not None:
        return False
    try:
        installed = Version(version(requirement.name))
    except PackageNotFoundError:
        return False
    if requirement.specifier and not requirement.specifier.contains(
        installed,
        prereleases=True,
    ):
        return False
    if not requirement.extras:
        return True
    if canonicalize_name(
        requirement.name
    ) != _STUDIO_DISTRIBUTION or requirement.extras != {"deno"}:
        return False
    base_environment = {key: str(value) for key, value in default_environment().items()}
    base_environment["extra"] = ""
    extra_environment = {**base_environment, "extra": "deno"}
    optional = []
    for value in requires(requirement.name) or ():
        dependency = Requirement(value)
        marker = dependency.marker
        if marker is None or marker.evaluate(
            environment=base_environment,
            context="requirement",
        ):
            continue
        if marker.evaluate(
            environment=extra_environment,
            context="requirement",
        ):
            optional.append(dependency)
    if not optional:
        return False
    for dependency in optional:
        if dependency.url is not None:
            return False
        try:
            dependency_version = Version(version(dependency.name))
        except PackageNotFoundError:
            return False
        if dependency.specifier and not dependency.specifier.contains(
            dependency_version,
            prereleases=True,
        ):
            return False
    return True


def provider_bootstrap_required(target: EnvironmentTarget) -> bool:
    """Return whether configured providers require environment re-entry."""
    if os.environ.get(SANDBOX_ENV) == "1":
        return False
    root = environment_root(target)
    project_metadata = _project_metadata(root)
    selected_project = (
        project_metadata if _declares_project_environment(project_metadata) else None
    )
    bootstrap = _bootstrap_requirements(
        target,
        project_metadata=selected_project,
    )
    return bootstrap.uses_declared_source or any(
        not _installed_requirement_satisfies(value)
        for value in bootstrap.launch_requirements
    )


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


@contextmanager
def _live_diagnostics(path: Path, relay: Callable[[TextIO], None]) -> Iterator[None]:
    stopped = Event()
    failures: list[BaseException] = []

    def follow() -> None:
        try:
            with path.open(encoding="utf-8", errors="replace") as source:
                while True:
                    terminal = stopped.is_set()
                    batch = StringIO()
                    while batch.tell() < 64 * 1024:
                        position = source.tell()
                        line = source.readline()
                        if not line:
                            break
                        if not line.endswith("\n") and not terminal:
                            source.seek(position)
                            break
                        batch.write(line)
                    full_batch = batch.tell() >= 64 * 1024
                    if batch.tell():
                        batch.seek(0)
                        relay(batch)
                    if full_batch:
                        continue
                    if terminal:
                        return
                    stopped.wait(0.1)
        except BaseException as error:
            failures.append(error)

    worker = Thread(target=follow, name="studio-diagnostics")
    worker.start()
    try:
        yield
    finally:
        stopped.set()
        worker.join()
        if failures and sys.exc_info()[0] is None:
            raise failures[0]


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
        if diagnostic_stream is not None:
            live = _live_diagnostics(diagnostic_channel, diagnostic_stream)
        else:
            live = nullcontext()
        with live:
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
    project_metadata = _project_metadata(root)
    compose_project = _declares_project_environment(project_metadata)
    if compose_project:
        command.extend(["--project", str(root)])
        if (root / "uv.lock").is_file():
            command.append("--frozen")
    source_root = package_source_root()
    bootstrap = _bootstrap_requirements(
        target,
        project_metadata=project_metadata if compose_project else None,
    )
    launch_requirements = bootstrap.launch_requirements
    marker_environment = bootstrap.marker_environment
    notebook_constraint = studio_dependency_constraint(
        _read_target_notebook_metadata(target.notebook) or {}
    )
    constraints = (notebook_constraint,)
    if compose_project:
        assert project_metadata is not None
        constraints = (
            notebook_constraint,
            studio_dependency_constraint(project_metadata),
        )
    flags = create_environment_flag_builder()(
        target.notebook,
        launch_requirements,
        compose_project=compose_project,
        marker_environment=marker_environment,
    )
    if marker_environment is not None:
        while "--python" in flags:
            index = flags.index("--python")
            del flags[index : index + 2]
        flags = ["--python", sys.executable, *flags]
    if compose_project:
        assert project_metadata is not None
        for value in launch_requirements:
            distribution = canonicalize_name(Requirement(value).name)
            constraint = dependency_constraint(project_metadata, distribution)
            if constraint.source_owned and not uses_dependency_source(
                constraint,
                marker_environment=marker_environment,
            ):
                flags.extend(["--no-sources-package", distribution])
    command.extend(flags)
    local_source = _invoking_studio_source(source_root)
    if local_source and allows_source_checkout(
        _package_version(),
        constraints,
        marker_environment=marker_environment,
    ):
        command.extend(local_source)
    command.extend(["--", *args])
    return command


def _invoking_studio_source(source_root: Path | None) -> list[str]:
    """Return uv flags that install the direct source of the invoking Studio.

    An index install needs no flag because the launch requirements already pin
    its version.
    """
    if source_root is not None:
        return ["--with-editable", str(source_root)]
    studio = invoking_studio()
    if studio is None:
        return []
    if studio.editable is not None:
        return ["--with-editable", str(studio.editable)]
    if studio.url is not None:
        return ["--with", studio.requirement]
    return []


def _target_provider_ids(target: EnvironmentTarget) -> tuple[str, ...]:
    selected = (
        target.provider_ids if isinstance(target, _ProviderEnvironmentTarget) else ()
    )
    if isinstance(target, StudioWorkspace):
        configured = tuple(view.provider for view in target.views.values())
        return tuple(sorted({*configured, *selected}))
    definition = discover_studio_definition(target.notebook)
    if definition is None:
        return selected
    configured = tuple(
        view.provider for view in discover_views(definition.view_root).values()
    )
    return tuple(sorted({*configured, *selected}))


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
