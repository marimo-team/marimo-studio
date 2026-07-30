"""Build uv arguments with Marimo's notebook sandbox adapter."""

from __future__ import annotations

import atexit
import copy
import os
import tempfile
from collections.abc import Mapping
from contextlib import suppress
from pathlib import Path

from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import canonicalize_name

from marimo_studio._compat.server import assert_supported_version
from marimo_studio._workspace.metadata import set_package_requirement

_PACKAGE_NAME = canonicalize_name("marimo-studio")


def _has_package_requirement(project: dict[str, object]) -> bool:
    dependencies = project.get("dependencies")
    if not isinstance(dependencies, list):
        return False

    for dependency in dependencies:
        if not isinstance(dependency, str):
            continue
        try:
            name = Requirement(dependency).name
        except InvalidRequirement:
            continue
        if canonicalize_name(name) == _PACKAGE_NAME:
            return True
    return False


def _has_package_source(project: dict[str, object]) -> bool:
    tool = project.get("tool")
    uv = tool.get("uv") if isinstance(tool, Mapping) else None
    sources = uv.get("sources") if isinstance(uv, Mapping) else None
    return isinstance(sources, Mapping) and any(
        canonicalize_name(str(name)) == _PACKAGE_NAME for name in sources
    )


def inline_environment_flags(
    notebook: Path,
    package_requirement: str | None,
    *,
    compose_project: bool,
) -> list[str]:
    """Resolve complete PEP 723 sources and indexes through Marimo."""
    assert_supported_version()
    from marimo._cli.sandbox import construct_uv_flags
    from marimo._utils.inline_script_metadata import PyProjectReader

    reader = PyProjectReader.from_filename(str(notebook))
    has_package = _has_package_requirement(reader.project)
    replace_package = has_package and (
        package_requirement is None
        or _has_package_source(reader.project)
        or reader.dependencies.count(package_requirement) != 1
    )
    if replace_package:
        project = copy.deepcopy(reader.project)
        set_package_requirement(project, package_requirement)
        reader = PyProjectReader(
            project,
            config_path=str(notebook),
        )
    additional_dependencies = (
        [package_requirement]
        if package_requirement is not None and not has_package
        else []
    )
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
            additional_dependencies,
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
