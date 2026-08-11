"""Read and update marimo-studio configuration in PEP 723 metadata."""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Mapping, MutableMapping
from importlib.metadata import metadata
from pathlib import Path
from typing import Any

import tomlkit
from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import canonicalize_name
from tomlkit import TOMLDocument

from marimo_studio._workspace.files import atomic_write_text, read_text
from marimo_studio._workspace.python_requirement import (
    intersect_python_requirements,
)
from marimo_studio.errors import ConfigurationError, DependencyError
from marimo_studio.types import CellRef

SCRIPT_START = "# /// script"
SCRIPT_END = "# ///"
_ENCODING_COOKIE = re.compile(r"^[ \t\f]*#.*?coding[:=][ \t]*[-_.a-zA-Z0-9]+")
_PACKAGE_NAME = canonicalize_name("marimo-studio")


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


def notebook_config(path: Path) -> Mapping[str, Any] | None:
    """Return `[tool.marimo-studio]` from a notebook."""
    document = read_notebook_metadata(path)
    if document is None:
        return None
    tool = document.get("tool")
    config = tool.get("marimo-studio") if isinstance(tool, Mapping) else None
    if config is None:
        return None
    if not isinstance(config, Mapping):
        raise ConfigurationError(f"[tool.marimo-studio] must be a TOML table: {path}")
    return config


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


def _dependency_name(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        return canonicalize_name(Requirement(value).name)
    except InvalidRequirement:
        return None


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


def _package_python_requirement() -> str:
    requirement = metadata("marimo-studio")["Requires-Python"]
    if requirement is None:
        raise DependencyError("marimo-studio package metadata has no Requires-Python")
    return requirement


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
    cell_bindings: Mapping[str, CellRef] | None = None,
) -> str:
    """Return notebook source with the package dependency and view configuration."""
    source = read_text(path)
    document = _document(source, path) or tomlkit.document()
    package_python = _package_python_requirement()
    current_python = document.get("requires-python")
    if current_python is None:
        document["requires-python"] = package_python
    elif not isinstance(current_python, str):
        raise ConfigurationError("PEP 723 requires-python must be a string")
    else:
        document["requires-python"] = intersect_python_requirements(
            current_python,
            package_python,
        )
    set_package_requirement(document, "marimo-studio")

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
    set_cell_bindings(config, cell_bindings or {})
    return _replace_metadata(source, path, document)


def update_notebook_config(
    path: Path,
    update: Callable[[MutableMapping[str, Any]], None],
) -> None:
    """Mutate the notebook-local marimo-studio table atomically."""
    source = read_text(path)
    updated = updated_notebook_config_source(path, source, update)
    atomic_write_text(path, updated)


def updated_notebook_config_source(
    path: Path,
    source: str,
    update: Callable[[MutableMapping[str, Any]], None],
) -> str:
    """Return notebook source with an updated marimo-studio table."""
    document = _document(source, path)
    if document is None:
        raise ConfigurationError(f"Notebook has no PEP 723 metadata: {path}")
    tool = document.get("tool")
    config = tool.get("marimo-studio") if isinstance(tool, Mapping) else None
    if not isinstance(config, MutableMapping):
        raise ConfigurationError(
            f"Notebook has no [tool.marimo-studio] configuration: {path}"
        )
    update(config)
    return _replace_metadata(source, path, document)
