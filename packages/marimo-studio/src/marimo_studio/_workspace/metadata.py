"""Read and update marimo-studio configuration in PEP 723 metadata."""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Mapping, MutableMapping
from importlib.metadata import metadata
from pathlib import Path
from typing import Any

import tomlkit
from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import NormalizedName, canonicalize_name
from tomlkit import TOMLDocument

from marimo_studio._filesystem.io import atomic_write_text, read_text
from marimo_studio._notebook.records import CellRef
from marimo_studio._workspace.python_project import owning_project
from marimo_studio._workspace.python_requirement import (
    intersect_python_requirements,
)
from marimo_studio.errors import ConfigurationError, DependencyError

SCRIPT_START = "# /// script"
SCRIPT_END = "# ///"
_ENCODING_COOKIE = re.compile(r"^[ \t\f]*#.*?coding[:=][ \t]*[-_.a-zA-Z0-9]+")
_PACKAGE_NAME = canonicalize_name("marimo-studio")
_PROVIDER_DEPENDENCIES_FIELD = "provider_dependencies"


def _bounds(source: str, path: Path) -> tuple[int, int] | None:
    lines = source.splitlines(keepends=True)
    starts = [
        index for index, line in enumerate(lines) if line.rstrip("\r\n") == SCRIPT_START
    ]
    if len(starts) > 1:
        raise ConfigurationError(f"Notebook has multiple PEP 723 script blocks: {path}")
    if not starts:
        return None
    start = starts[0]
    end = next(
        (
            index
            for index, line in enumerate(lines[start + 1 :], start + 1)
            if line.rstrip("\r\n") == SCRIPT_END
        ),
        None,
    )
    if end is None:
        raise ConfigurationError(f"Notebook has an unterminated PEP 723 block: {path}")
    return start, end


def _document(source: str, path: Path) -> TOMLDocument | None:
    bounds = _bounds(source, path)
    if bounds is None:
        return None
    start, end = bounds
    lines = source.splitlines(keepends=True)
    content: list[str] = []
    for line in lines[start + 1 : end]:
        value = line.rstrip("\r\n")
        ending = line[len(value) :]
        if not value.startswith("#"):
            raise ConfigurationError(f"Notebook has invalid PEP 723 metadata: {path}")
        value = value[2:] if value.startswith("# ") else value[1:]
        content.append(value + ending)
    try:
        return tomlkit.parse("".join(content))
    except Exception as error:
        raise ConfigurationError(
            f"Notebook has invalid PEP 723 metadata: {error}"
        ) from error


def read_notebook_metadata(path: Path) -> TOMLDocument | None:
    """Return a notebook's PEP 723 document."""
    return _document(read_text(path), path)


def _notebook_config(
    document: Mapping[str, Any] | None,
    path: Path,
) -> Mapping[str, Any] | None:
    if document is None:
        return None
    tool = document.get("tool")
    config = tool.get("marimo-studio") if isinstance(tool, Mapping) else None
    if config is None:
        return None
    if not isinstance(config, Mapping):
        raise ConfigurationError(f"[tool.marimo-studio] must be a TOML table: {path}")
    return config


def notebook_config(path: Path) -> Mapping[str, Any] | None:
    """Return `[tool.marimo-studio]` from a notebook."""
    return _notebook_config(read_notebook_metadata(path), path)


def notebook_config_source(path: Path, source: str) -> Mapping[str, Any] | None:
    """Return `[tool.marimo-studio]` from captured notebook source."""
    return _notebook_config(_document(source, path), path)


def _render(document: TOMLDocument, newline: str) -> str:
    content = tomlkit.dumps(document).rstrip("\r\n")
    lines = content.splitlines() if content else []
    comments = ("#" if not line else f"# {line}" for line in lines)
    return newline.join((SCRIPT_START, *comments, SCRIPT_END))


def _replace_metadata(source: str, path: Path, document: TOMLDocument) -> str:
    newline = "\r\n" if "\r\n" in source else "\n"
    block = _render(document, newline)
    bounds = _bounds(source, path)
    if bounds is None:
        lines = source.splitlines(keepends=True)
        insertion = 0
        if lines and lines[0].startswith("#!"):
            insertion = 1
        if insertion < len(lines) and _ENCODING_COOKIE.match(
            lines[insertion].rstrip("\r\n")
        ):
            insertion += 1
        offset = sum(len(line) for line in lines[:insertion])
        prefix = source[:offset]
        suffix = source[offset:]
        separator = newline if prefix and not prefix.endswith(("\n", "\r")) else ""
        return prefix + separator + block + newline * 2 + suffix

    start, end = bounds
    lines = source.splitlines(keepends=True)
    start_offset = sum(len(line) for line in lines[:start])
    end_offset = sum(len(line) for line in lines[: end + 1])
    closing_line = lines[end]
    ending = closing_line[len(closing_line.rstrip("\r\n")) :]
    return source[:start_offset] + block + ending + source[end_offset:]


def _dependency_name(value: object) -> NormalizedName | None:
    if not isinstance(value, str):
        return None
    try:
        return canonicalize_name(Requirement(value).name)
    except InvalidRequirement:
        return None


def _requirements_equivalent(first: str, second: str) -> bool:
    try:
        return Requirement(first) == Requirement(second)
    except InvalidRequirement:
        return False


def set_package_requirement(
    document: MutableMapping[str, Any],
    requirement: str | None,
) -> None:
    """Set the authoritative marimo-studio requirement in PEP 723 data."""
    dependencies = document.get("dependencies")
    if dependencies is None:
        if requirement is None:
            return
        dependencies = tomlkit.array()
        document["dependencies"] = dependencies
    if not isinstance(dependencies, list):
        raise ConfigurationError("PEP 723 dependencies must be an array of strings")

    matches = [
        index
        for index, dependency in enumerate(dependencies)
        if _dependency_name(dependency) == _PACKAGE_NAME
    ]
    if requirement is None:
        for index in reversed(matches):
            del dependencies[index]
    elif matches:
        dependencies[matches[0]] = requirement
        for index in reversed(matches[1:]):
            del dependencies[index]
    else:
        dependencies.append(requirement)

    tool = document.get("tool")
    uv = tool.get("uv") if isinstance(tool, MutableMapping) else None
    sources = uv.get("sources") if isinstance(uv, MutableMapping) else None
    if isinstance(sources, MutableMapping):
        for name in tuple(sources):
            if canonicalize_name(str(name)) == _PACKAGE_NAME:
                del sources[name]


def _merge_provider_requirements(requirements: Iterable[str]) -> tuple[str, ...]:
    merged: dict[str, Requirement] = {}
    for value in requirements:
        try:
            requirement = Requirement(value)
        except InvalidRequirement as error:
            raise ConfigurationError(
                f"Invalid provider Python requirement: {value!r}"
            ) from error
        name = canonicalize_name(requirement.name)
        current = merged.get(name)
        if current is None:
            merged[name] = requirement
            continue
        current_specifier = current.specifier
        candidate_specifier = requirement.specifier
        if (
            (
                str(current_specifier)
                and str(candidate_specifier)
                and current_specifier != candidate_specifier
            )
            or current.url != requirement.url
            or str(current.marker) != str(requirement.marker)
        ):
            raise ConfigurationError(
                f"Configured providers require incompatible {name!r} environments"
            )
        selected = current if str(current_specifier) else requirement
        extras = sorted(current.extras | requirement.extras)
        extra_text = f"[{','.join(extras)}]" if extras else ""
        if selected.url is not None:
            rendered = f"{name}{extra_text} @ {selected.url}"
        else:
            rendered = f"{name}{extra_text}{selected.specifier}"
        if selected.marker is not None:
            rendered = f"{rendered}; {selected.marker}"
        merged[name] = Requirement(rendered)
    return tuple(str(item) for item in merged.values())


def _set_provider_requirements(
    document: MutableMapping[str, Any],
    requirements: Iterable[str],
    *,
    provider_owned: frozenset[NormalizedName],
) -> None:
    values = _merge_provider_requirements(requirements)
    required = {
        canonicalize_name(Requirement(value).name): Requirement(value)
        for value in values
    }
    dependencies = document.get("dependencies")
    if dependencies is None:
        dependencies = tomlkit.array()
        document["dependencies"] = dependencies
    if not isinstance(dependencies, list):
        raise ConfigurationError("PEP 723 dependencies must be an array of strings")

    existing_extras: dict[NormalizedName, set[str]] = {}
    for dependency in dependencies:
        if not isinstance(dependency, str):
            continue
        try:
            parsed = Requirement(dependency)
        except InvalidRequirement:
            continue
        name = canonicalize_name(parsed.name)
        if name in required:
            existing_extras.setdefault(name, set()).update(parsed.extras)
    managed = provider_owned | {_PACKAGE_NAME}
    rendered_required = {
        name: _render_requirement(
            requirement,
            extras=set(requirement.extras) | existing_extras.get(name, set()),
        )
        for name, requirement in required.items()
    }
    updated: list[object] = []
    written: set[NormalizedName] = set()
    for dependency in dependencies:
        name = _dependency_name(dependency)
        if name is None or name not in required:
            updated.append(dependency)
            continue
        if name not in managed:
            updated.append(dependency)
            written.add(name)
            continue
        if name not in written:
            updated.append(rendered_required[name])
            written.add(name)
    updated.extend(
        requirement
        for name, requirement in rendered_required.items()
        if name not in written
    )
    for index in reversed(range(len(dependencies))):
        del dependencies[index]
    for dependency in updated:
        dependencies.append(dependency)


def _render_requirement(
    requirement: Requirement,
    *,
    extras: set[str],
) -> str:
    extra_text = f"[{','.join(sorted(extras))}]" if extras else ""
    if requirement.url is not None:
        rendered = f"{requirement.name}{extra_text} @ {requirement.url}"
    else:
        rendered = f"{requirement.name}{extra_text}{requirement.specifier}"
    if requirement.marker is not None:
        rendered = f"{rendered}; {requirement.marker}"
    return rendered


def _provider_dependency_requirements(
    config: Mapping[str, Any],
) -> tuple[str, ...]:
    values = config.get(_PROVIDER_DEPENDENCIES_FIELD, ())
    if not isinstance(values, list | tuple) or not all(
        isinstance(value, str) for value in values
    ):
        raise ConfigurationError(
            "provider_dependencies must be an array of Python requirements"
        )
    return _merge_provider_requirements(values)


def _set_provider_dependency_ownership(
    document: MutableMapping[str, Any],
    config: MutableMapping[str, Any],
    requirements: Iterable[str],
) -> None:
    dependencies = document.get("dependencies", ())
    if not isinstance(dependencies, list | tuple):
        raise ConfigurationError("PEP 723 dependencies must be an array of strings")
    present: dict[NormalizedName, list[str]] = {}
    for dependency in dependencies:
        if not isinstance(dependency, str):
            continue
        try:
            requirement = Requirement(dependency)
        except InvalidRequirement:
            continue
        present.setdefault(canonicalize_name(requirement.name), []).append(
            str(requirement)
        )
    owned = {
        canonicalize_name(Requirement(value).name): value
        for value in _provider_dependency_requirements(config)
    }
    requested = {
        canonicalize_name(Requirement(value).name): value
        for value in _merge_provider_requirements(requirements)
    }
    for name, value in tuple(owned.items()):
        current = present.get(name, ())
        if (
            current
            and not all(_requirements_equivalent(item, value) for item in current)
        ) or (not current and name not in requested):
            del owned[name]
    for name, value in requested.items():
        if name == _PACKAGE_NAME:
            continue
        if name in owned or name not in present:
            owned[name] = value
    if not owned:
        config.pop(_PROVIDER_DEPENDENCIES_FIELD, None)
        return
    values = tomlkit.array()
    values.multiline(True)
    for name in sorted(owned):
        values.append(owned[name])
    config[_PROVIDER_DEPENDENCIES_FIELD] = values


def _remove_provider_dependencies(
    document: MutableMapping[str, Any],
    *,
    preserve: Iterable[str] = (),
) -> None:
    tool = document.get("tool")
    config = tool.get("marimo-studio") if isinstance(tool, Mapping) else None
    if not isinstance(config, Mapping):
        return
    owned = {
        canonicalize_name(requirement.name): str(requirement)
        for value in _provider_dependency_requirements(config)
        for requirement in (Requirement(value),)
    }
    preserved = {canonicalize_name(name) for name in preserve}
    dependencies = document.get("dependencies")
    if not isinstance(dependencies, list):
        return
    for index in reversed(range(len(dependencies))):
        dependency = dependencies[index]
        if not isinstance(dependency, str):
            continue
        try:
            requirement = Requirement(dependency)
        except InvalidRequirement:
            continue
        name = canonicalize_name(requirement.name)
        recorded = owned.get(name)
        if (
            name not in preserved
            and recorded is not None
            and _requirements_equivalent(recorded, str(requirement))
        ):
            del dependencies[index]


def browser_notebook_metadata_source(
    path: Path,
    source: str,
    *,
    imported_distributions: Iterable[str],
) -> str:
    """Return source with PEP 723 metadata for a browser runtime.

    Provider dependencies are removed when their normalized PEP 508
    requirements match `provider_dependencies`. Dependencies with different
    requirements or names claimed by `imported_distributions` remain. The
    Studio requirement, `[tool.marimo-studio]`, and `[tool.uv]` are removed.

    Raises:
        ConfigurationError: The PEP 723 metadata or provider ownership record
            is invalid.
    """
    document = _document(source, path)
    if document is None:
        return source
    set_package_requirement(document, None)
    _remove_provider_dependencies(
        document,
        preserve=imported_distributions,
    )
    tool = document.get("tool")
    if isinstance(tool, MutableMapping):
        tool.pop("marimo-studio", None)
        tool.pop("uv", None)
        if not tool:
            document.pop("tool", None)
    return _replace_metadata(source, path, document)


def _package_python_requirement() -> str:
    requirement = metadata("marimo-studio")["Requires-Python"]
    if requirement is None:
        raise DependencyError("marimo-studio package metadata has no Requires-Python")
    return requirement


def _package_requirement() -> str:
    package_version = metadata("marimo-studio")["Version"]
    if package_version is None:
        raise DependencyError("marimo-studio package metadata has no version")
    return f"marimo-studio=={package_version}"


def set_cell_bindings(
    config: MutableMapping[str, Any],
    bindings: Mapping[str, CellRef],
    *,
    remove: Iterable[str] = (),
) -> None:
    """Set cell aliases in a mutable Studio configuration."""
    cells = config.setdefault("cells", tomlkit.table())
    if not isinstance(cells, MutableMapping):
        raise ConfigurationError("cells must be a TOML table")
    for alias in remove:
        cells.pop(alias, None)
    for alias, ref in bindings.items():
        value = tomlkit.inline_table()
        value["ref"] = str(ref)
        cells[alias] = value


def configured_notebook_source(
    path: Path,
    default_view: str,
    provider_requirements: Iterable[str] = (),
    cell_bindings: Mapping[str, CellRef] | None = None,
    *,
    source: str | None = None,
) -> str:
    """Return notebook source with the package dependency and view configuration."""
    source = read_text(path) if source is None else source
    provider_requirements = tuple(provider_requirements)
    document = _document(source, path) or tomlkit.document()
    package_python = _package_python_requirement()
    current_python = document.get("requires-python")
    if current_python is None:
        current_python = package_python
    elif not isinstance(current_python, str):
        raise ConfigurationError("PEP 723 requires-python must be a string")
    document["requires-python"] = intersect_python_requirements(
        current_python,
        package_python,
    )
    tool = document.get("tool")
    if tool is None:
        tool = tomlkit.table()
        document["tool"] = tool
    if not isinstance(tool, MutableMapping):
        raise ConfigurationError("[tool] in PEP 723 metadata must be a TOML table")
    config = tool.get("marimo-studio")
    if config is None:
        config = tomlkit.table()
        config["default"] = default_view
        config["cells"] = tomlkit.table()
        tool["marimo-studio"] = config
    elif not isinstance(config, MutableMapping):
        raise ConfigurationError("[tool.marimo-studio] must be a TOML table")
    else:
        config.setdefault("default", default_view)
        config.setdefault("cells", tomlkit.table())
    if "dependencies" in document or owning_project(path) is None:
        _set_provider_dependency_ownership(
            document,
            config,
            provider_requirements,
        )
        provider_owned = frozenset(
            canonicalize_name(Requirement(value).name)
            for value in _provider_dependency_requirements(config)
        )
        _set_provider_requirements(
            document,
            (_package_requirement(), *provider_requirements),
            provider_owned=provider_owned,
        )
    set_cell_bindings(config, cell_bindings or {})
    return _replace_metadata(source, path, document)


def update_notebook_config(
    path: Path,
    update: Callable[[MutableMapping[str, Any]], None],
) -> None:
    """Mutate the notebook-local marimo-studio table atomically."""
    source = read_text(path)
    updated = updated_notebook_config_source(path, source, update)
    atomic_write_text(path, updated, root=path.parent)


def _studio_config(
    document: Mapping[str, Any],
    path: Path,
) -> MutableMapping[str, Any]:
    tool = document.get("tool")
    config = tool.get("marimo-studio") if isinstance(tool, Mapping) else None
    if not isinstance(config, MutableMapping):
        raise ConfigurationError(
            f"Notebook has no [tool.marimo-studio] configuration: {path}"
        )
    return config


def updated_notebook_default_source(
    path: Path,
    source: str,
    *,
    default_view: str,
) -> str:
    """Return notebook source with a new default view."""
    document = _document(source, path)
    if document is None:
        raise ConfigurationError(f"Notebook has no PEP 723 metadata: {path}")
    config = _studio_config(document, path)
    config["default"] = default_view
    return _replace_metadata(source, path, document)


def updated_notebook_config_source(
    path: Path,
    source: str,
    update: Callable[[MutableMapping[str, Any]], None],
) -> str:
    """Return notebook source with an updated marimo-studio table."""
    document = _document(source, path)
    if document is None:
        raise ConfigurationError(f"Notebook has no PEP 723 metadata: {path}")
    update(_studio_config(document, path))
    return _replace_metadata(source, path, document)
