"""Build uv arguments with Marimo's notebook sandbox adapter."""

from __future__ import annotations

import atexit
import copy
import os
import tempfile
from collections.abc import Mapping, MutableMapping
from contextlib import suppress
from pathlib import Path

from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import canonicalize_name

from marimo_studio._workspace.environment_requirements import (
    MarkerEnvironment,
    dependency_constraint,
    effective_dependency_requirement,
    replace_studio_launch_requirement,
    studio_dependency_constraint,
    uses_dependency_source,
)
from marimo_studio._workspace.metadata import set_package_requirement
from marimo_studio.errors import ConfigurationError

_PACKAGE_NAME = canonicalize_name("marimo-studio")


def _replace_requirement(
    project: MutableMapping[str, object],
    name: str,
    value: str,
) -> None:
    dependencies = project.get("dependencies")
    if dependencies is None:
        dependencies = []
        project["dependencies"] = dependencies
    if not isinstance(dependencies, list):
        raise ConfigurationError("PEP 723 dependencies must be an array of strings")
    matches = []
    for index, dependency in enumerate(dependencies):
        try:
            dependency_name = Requirement(str(dependency)).name
        except InvalidRequirement:
            continue
        if canonicalize_name(dependency_name) == canonicalize_name(name):
            matches.append(index)
    if matches:
        dependencies[matches[0]] = value
        for index in reversed(matches[1:]):
            del dependencies[index]
        return
    dependencies.append(value)


def _remove_dependency_source(
    project: MutableMapping[str, object],
    name: str,
) -> None:
    tool = project.get("tool")
    uv = tool.get("uv") if isinstance(tool, MutableMapping) else None
    sources = uv.get("sources") if isinstance(uv, MutableMapping) else None
    if not isinstance(sources, MutableMapping):
        return
    normalized = canonicalize_name(name)
    for source_name in tuple(sources):
        if canonicalize_name(str(source_name)) == normalized:
            del sources[source_name]


def _resolved_launch_requirements(
    project: Mapping[str, object],
    launch_requirements: tuple[str, ...],
    marker_environment: MarkerEnvironment | None,
) -> tuple[str, ...]:
    resolved_launch = replace_studio_launch_requirement(
        launch_requirements,
        (studio_dependency_constraint(project),),
        marker_environment=marker_environment,
    )
    resolved = []
    for value in resolved_launch:
        requirement = Requirement(value)
        name = canonicalize_name(requirement.name)
        if name == _PACKAGE_NAME:
            resolved.append(value)
            continue
        resolved.append(
            effective_dependency_requirement(
                value,
                (dependency_constraint(project, name),),
                marker_environment=marker_environment,
            )
        )
    return tuple(resolved)


def inline_environment_flags(
    notebook: Path,
    launch_requirements: tuple[str, ...],
    *,
    compose_project: bool,
    marker_environment: MarkerEnvironment | None,
) -> list[str]:
    """Resolve complete PEP 723 sources and indexes through Marimo."""
    from marimo._cli.sandbox import construct_uv_flags
    from marimo._utils.inline_script_metadata import PyProjectReader

    reader = PyProjectReader.from_filename(str(notebook))
    project = copy.deepcopy(reader.project)
    resolved_requirements = _resolved_launch_requirements(
        project,
        launch_requirements,
        marker_environment,
    )
    for requirement in resolved_requirements:
        name = canonicalize_name(Requirement(requirement).name)
        constraint = dependency_constraint(project, name)
        source_active = uses_dependency_source(
            constraint,
            marker_environment=marker_environment,
        )
        if name == _PACKAGE_NAME:
            if source_active:
                _replace_requirement(project, name, requirement)
            else:
                set_package_requirement(project, requirement)
        else:
            if not source_active:
                _remove_dependency_source(project, name)
            _replace_requirement(project, name, requirement)
    reader = PyProjectReader(project, config_path=str(notebook))
    with tempfile.NamedTemporaryFile(
        mode="w",
        delete=False,
        suffix=".txt",
        encoding="utf-8",
    ) as temporary:
        flags = construct_uv_flags(
            reader,
            temporary,
            [],
            [],
        )
        temporary_name = temporary.name
    atexit.register(_unlink, temporary_name)
    if compose_project:
        flags = [flag for flag in flags if flag not in {"--isolated", "--no-project"}]
        if reader.python_version is None and "--python" in flags:
            index = flags.index("--python")
            del flags[index : index + 2]
    return flags


def _unlink(path: str) -> None:
    with suppress(FileNotFoundError):
        os.unlink(path)
