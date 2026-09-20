"""Compare notebook dependency declarations with the inspecting interpreter."""

from __future__ import annotations

import ast
import importlib.metadata
import importlib.util
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import canonicalize_name

from marimo_studio._workspace.config import canonical_view_root, discover_views
from marimo_studio._workspace.metadata import read_notebook_metadata
from marimo_studio._workspace.python_project import owning_project, project_metadata
from marimo_studio.errors import ConfigurationError
from marimo_studio.view_providers._host import provider_registry


def _requirements(values: object) -> dict[str, list[Requirement]]:
    if not isinstance(values, list | tuple):
        raise ConfigurationError("Dependencies must be an array of requirements")
    result: dict[str, list[Requirement]] = {}
    for value in values:
        if not isinstance(value, str):
            raise ConfigurationError("Dependencies must be strings")
        try:
            requirement = Requirement(value)
        except InvalidRequirement as error:
            raise ConfigurationError(f"Invalid dependency: {value}") from error
        if requirement.marker is None or requirement.marker.evaluate():
            result.setdefault(canonicalize_name(requirement.name), []).append(
                requirement
            )
    return result


def diagnose_dependencies(notebook: Path) -> dict[str, Any]:
    """Inspect declarations and import resolution without executing notebook cells."""
    inline = read_notebook_metadata(notebook) or {}
    root = owning_project(notebook)
    metadata = project_metadata(root) if root is not None else None
    project = metadata.get("project", {}) if metadata else {}
    project_values = (
        project.get("dependencies", ()) if isinstance(project, Mapping) else ()
    )
    declarations = {
        "notebook": _requirements(inline.get("dependencies", ())),
        "project": _requirements(project_values),
    }
    issues: list[dict[str, str]] = []

    def issue(code: str, message: str) -> None:
        issues.append({"code": code, "message": message})

    if root is not None and "dependencies" in inline:
        for name in sorted(
            declarations["project"].keys() | declarations["notebook"].keys()
        ):
            sandbox = declarations["notebook"].get(name, [])
            owning = declarations["project"].get(name, [])
            if set(sandbox) != set(owning):
                issue(
                    "metadata-drift",
                    f"{name}: project and notebook requirements differ",
                )

    providers: list[str] = []
    registry = provider_registry()
    for view in discover_views(canonical_view_root(notebook)).values():
        try:
            requirement = registry.get(view.provider).requirement
        except Exception as error:
            issue("provider-unavailable", f"{view.provider}: {error}")
            continue
        if requirement not in providers:
            providers.append(requirement)
    declarations["providers"] = _requirements(providers)

    authored = (
        declarations["notebook"]
        if "dependencies" in inline
        else declarations["project"]
    )
    for name, requirements in declarations["providers"].items():
        extras = {
            extra
            for requirement in authored.get(name, [])
            for extra in requirement.extras
        }
        if name not in authored or any(
            not requirement.extras.issubset(extras) for requirement in requirements
        ):
            issue(
                "undeclared-provider",
                f"Declare {', '.join(map(str, requirements))} "
                "in the execution environment",
            )

    installed: dict[str, str | None] = {}
    for source, requirements in declarations.items():
        for name, constraints in requirements.items():
            try:
                actual_version = importlib.metadata.version(name)
                installed[name] = actual_version
            except importlib.metadata.PackageNotFoundError:
                installed[name] = None
                issue("missing-distribution", f"{source}: {name} is not installed")
                continue
            for requirement in constraints:
                if not requirement.specifier.contains(actual_version, prereleases=True):
                    issue(
                        "version-mismatch",
                        f"{source}: {requirement} excludes installed {installed[name]}",
                    )
                if requirement.url:
                    issue(
                        "unverified-source",
                        f"{source}: verify the installed source for {name}",
                    )
                for extra in requirement.extras:
                    for dependency in importlib.metadata.requires(name) or ():
                        selected = Requirement(dependency)
                        if selected.marker is not None and not selected.marker.evaluate(
                            {"extra": extra}
                        ):
                            continue
                        try:
                            actual = importlib.metadata.version(selected.name)
                        except importlib.metadata.PackageNotFoundError:
                            actual = None
                        if actual is None or not selected.specifier.contains(
                            actual, prereleases=True
                        ):
                            issue(
                                "missing-extra",
                                f"{source}: {name}[{extra}] requires {selected}",
                            )

    try:
        tree = ast.parse(notebook.read_text(encoding="utf-8"))
    except SyntaxError as error:
        raise ConfigurationError(f"Cannot inspect notebook imports: {error}") from error
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            modules.add(node.module.split(".")[0])
    distributions = importlib.metadata.packages_distributions()
    imports = []
    declared = set().union(*(set(items) for items in declarations.values()))
    for module in sorted(modules - sys.stdlib_module_names):
        local = (notebook.parent / f"{module}.py").is_file() or (
            notebook.parent / module
        ).is_dir()
        available = local or importlib.util.find_spec(module) is not None
        names = distributions.get(module, [])
        imports.append(
            {
                "module": module,
                "available": available,
                "distributions": names,
                "local": local,
            }
        )
        if not available:
            issue(
                "missing-import",
                f"Import {module!r} is unavailable in this interpreter",
            )
        elif not local and not any(
            canonicalize_name(name) in declared for name in names
        ):
            issue(
                "undeclared-import",
                f"Import {module!r} has no direct dependency declaration",
            )

    return {
        "schema": 1,
        "ok": not issues,
        "notebook": str(notebook),
        "project": str(root / "pyproject.toml") if root else None,
        "python": sys.executable,
        "declarations": {
            source: [
                str(requirement)
                for values in requirements.values()
                for requirement in values
            ]
            for source, requirements in declarations.items()
        },
        "installed": installed,
        "imports": imports,
        "issues": issues,
    }
