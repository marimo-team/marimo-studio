"""Compare Marimo Studio distribution metadata with its pyproject."""

from __future__ import annotations

from email.message import Message
from importlib.metadata import PackageMetadata
from pathlib import Path
from typing import Any

import tomlkit
from packaging.requirements import Requirement
from packaging.specifiers import SpecifierSet
from packaging.utils import canonicalize_name

PYPROJECT = (
    Path(__file__).resolve().parents[1] / "packages/marimo-studio/pyproject.toml"
)


def declared_project() -> dict[str, Any]:
    return tomlkit.parse(PYPROJECT.read_text(encoding="utf-8"))["project"].unwrap()


_PLATFORMS = (
    {"sys_platform": "linux", "platform_system": "Linux", "os_name": "posix"},
    {"sys_platform": "darwin", "platform_system": "Darwin", "os_name": "posix"},
    {"sys_platform": "win32", "platform_system": "Windows", "os_name": "nt"},
)


def _environments(project: dict[str, Any]) -> list[dict[str, str]]:
    # Build backends rewrite markers, for example python_version into
    # python_full_version, so markers are compared by evaluation over every
    # supported Python minor, platform, and extra.
    supported = SpecifierSet(project["requires-python"])
    pythons = [f"3.{minor}" for minor in range(100) if f"3.{minor}.0" in supported]
    extras = ["", *project.get("optional-dependencies", {})]
    return [
        {
            **platform,
            "python_version": python,
            "python_full_version": f"{python}.0",
            "extra": extra,
        }
        for python in pythons
        for platform in _PLATFORMS
        for extra in extras
    ]


def _selects(
    requirement: Requirement, environment: dict[str, str], extra: str | None = None
) -> bool:
    if extra is not None and environment["extra"] != extra:
        return False
    return requirement.marker is None or requirement.marker.evaluate(environment)


def verify_metadata(
    metadata: Message | PackageMetadata, project: dict[str, Any], source: object
) -> None:
    """Require license, Python, URL, and dependency metadata to match pyproject."""
    if metadata["License-Expression"] != project["license"]:
        raise AssertionError(f"Distribution has the wrong license expression: {source}")
    if set(metadata.get_all("License-File") or ()) != set(project["license-files"]):
        raise AssertionError(f"Distribution has the wrong license files: {source}")
    if SpecifierSet(metadata["Requires-Python"] or "") != SpecifierSet(
        project["requires-python"]
    ):
        raise AssertionError(f"Distribution has the wrong Python requirement: {source}")
    urls = dict(value.split(", ", 1) for value in metadata.get_all("Project-URL") or ())
    if urls != project["urls"]:
        raise AssertionError(f"Distribution has the wrong project URLs: {source}")

    environments = _environments(project)
    declared = [(Requirement(value), None) for value in project["dependencies"]] + [
        (Requirement(value), extra)
        for extra, values in project.get("optional-dependencies", {}).items()
        for value in values
    ]
    published = [
        Requirement(value) for value in metadata.get_all("Requires-Dist") or ()
    ]
    for requirement, extra in declared:
        match = next(
            (
                built
                for built in published
                if canonicalize_name(built.name) == canonicalize_name(requirement.name)
                and built.specifier == requirement.specifier
                and built.extras == requirement.extras
                and all(
                    _selects(built, environment)
                    == _selects(requirement, environment, extra)
                    for environment in environments
                )
            ),
            None,
        )
        if match is None:
            raise AssertionError(
                f"Distribution has the wrong {requirement.name} requirement: {source}"
            )
        published.remove(match)
    if published:
        raise AssertionError(
            f"Distribution has undeclared requirements {sorted(map(str, published))}: {source}"
        )
