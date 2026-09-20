"""Compare declared Python environments with installed distributions and imports."""

from __future__ import annotations

import ast
import importlib.metadata
import importlib.util
import sys
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from pathlib import Path

from packaging.markers import UndefinedEnvironmentName
from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import canonicalize_name

from marimo_studio._workspace.config import (
    canonical_view_root,
    discover_studio_definition,
    discover_views,
)
from marimo_studio._workspace.metadata import read_notebook_metadata
from marimo_studio._workspace.python_project import owning_project, project_metadata
from marimo_studio.errors import ConfigurationError, MarimoStudioError
from marimo_studio.view_providers._host import provider_registry


@dataclass(frozen=True)
class DependencyIssue:
    code: str
    message: str


@dataclass(frozen=True)
class ImportResolution:
    module: str
    available: bool
    distributions: tuple[str, ...]
    local: bool


@dataclass(frozen=True)
class DependencyReport:
    notebook: Path
    project: Path | None
    python: str
    declarations: Mapping[str, tuple[str, ...]]
    installed: Mapping[str, str | None]
    imports: tuple[ImportResolution, ...]
    issues: tuple[DependencyIssue, ...]

    @property
    def ok(self) -> bool:
        return not self.issues

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": 1,
            "ok": self.ok,
            "notebook": str(self.notebook),
            "project": str(self.project) if self.project else None,
            "python": self.python,
            "declarations": {
                key: list(value) for key, value in self.declarations.items()
            },
            "installed": dict(self.installed),
            "imports": [asdict(item) for item in self.imports],
            "issues": [asdict(item) for item in self.issues],
        }


def _requirements(values: object) -> tuple[Requirement, ...]:
    if not isinstance(values, list | tuple):
        raise ConfigurationError("Dependencies must be an array of requirements")
    result = []
    for value in values:
        if not isinstance(value, str):
            raise ConfigurationError("Dependencies must be strings")
        try:
            requirement = Requirement(value)
            active = requirement.marker is None or requirement.marker.evaluate()
        except (InvalidRequirement, UndefinedEnvironmentName) as error:
            raise ConfigurationError(f"Invalid dependency: {value}") from error
        if active:
            result.append(requirement)
    return tuple(result)


def _by_name(requirements: Iterable[Requirement]) -> dict[str, set[Requirement]]:
    result: dict[str, set[Requirement]] = {}
    for requirement in requirements:
        result.setdefault(canonicalize_name(requirement.name), set()).add(requirement)
    return result


def _installed_requirements(
    requirements: Iterable[Requirement],
    issues: list[DependencyIssue],
    installed: dict[str, str | None],
) -> dict[str, set[str]]:
    """Resolve installed dependency and extra closure without importing packages."""
    pending = list(requirements)
    visited: set[Requirement] = set()
    enabled: dict[str, set[str]] = {}
    while pending:
        requirement = pending.pop()
        if requirement in visited:
            continue
        visited.add(requirement)
        name = canonicalize_name(requirement.name)
        extras = {canonicalize_name(extra) for extra in requirement.extras}
        enabled.setdefault(name, set()).update(extras)
        try:
            distribution = importlib.metadata.distribution(name)
        except importlib.metadata.PackageNotFoundError:
            installed[name] = None
            issues.append(
                DependencyIssue("missing-distribution", f"{name} is not installed")
            )
            continue
        installed[name] = distribution.version
        if not requirement.specifier.contains(distribution.version, prereleases=True):
            issues.append(
                DependencyIssue(
                    "version-mismatch",
                    f"{requirement} excludes installed {distribution.version}",
                )
            )
        if requirement.url:
            issues.append(
                DependencyIssue(
                    "unverified-source", f"Verify the installed source for {name}"
                )
            )
        provided = {
            canonicalize_name(extra)
            for extra in distribution.metadata.get_all("Provides-Extra", [])
        }
        for extra in sorted(extras - provided):
            issues.append(
                DependencyIssue(
                    "unknown-extra", f"{name} does not provide extra {extra!r}"
                )
            )
        for dependency in distribution.requires or ():
            try:
                selected = Requirement(dependency)
                active = selected.marker is None or any(
                    selected.marker.evaluate({"extra": extra})
                    for extra in {"", *extras}
                )
            except (InvalidRequirement, UndefinedEnvironmentName):
                issues.append(
                    DependencyIssue(
                        "invalid-dependency",
                        f"{name} declares an invalid dependency: {dependency}",
                    )
                )
                continue
            if active:
                pending.append(selected)
    return enabled


def _import_resolutions(
    notebook: Path,
    project: Path | None,
    declared: set[str],
    issues: list[DependencyIssue],
) -> tuple[ImportResolution, ...]:
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
    for module in sorted(modules - sys.stdlib_module_names):
        local = (notebook.parent / f"{module}.py").is_file() or (
            notebook.parent / module
        ).is_dir()
        spec = importlib.util.find_spec(module)
        names = tuple(distributions.get(module, []))
        if project is not None and spec is not None and not names:
            locations = (
                (spec.origin,)
                if spec.origin is not None
                else tuple(spec.submodule_search_locations or ())
            )
            source_roots = (project, project / "src")
            local = local or any(
                Path(location).resolve() == (root / f"{module}.py").resolve()
                or Path(location).resolve().is_relative_to((root / module).resolve())
                for root in source_roots
                for location in locations
            )
        available = local or sys.modules.get(module) is not None or spec is not None
        imports.append(ImportResolution(module, available, names, local))
        if not available:
            issues.append(
                DependencyIssue(
                    "missing-import",
                    f"Import {module!r} is unavailable in this interpreter",
                )
            )
        elif not local and not any(
            canonicalize_name(name) in declared for name in names
        ):
            issues.append(
                DependencyIssue(
                    "undeclared-import",
                    f"Import {module!r} is outside the declared dependency environment",
                )
            )
    return tuple(imports)


def diagnose_dependencies(notebook: Path) -> DependencyReport:
    """Inspect project and notebook dependencies without executing notebook cells."""
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
    issues: list[DependencyIssue] = []
    if root is not None and "dependencies" in inline:
        sandbox, owning = (
            _by_name(declarations[key]) for key in ("notebook", "project")
        )
        for name in sorted(sandbox.keys() | owning.keys()):
            if sandbox.get(name, set()) != owning.get(name, set()):
                issues.append(
                    DependencyIssue(
                        "metadata-drift",
                        f"{name}: project and notebook requirements differ",
                    )
                )
    providers: list[str] = []
    registry = provider_registry()
    definition = discover_studio_definition(notebook)
    view_root = (
        definition.view_root
        if definition is not None
        else canonical_view_root(notebook)
    )
    for view in discover_views(view_root).values():
        try:
            requirement = registry.get(view.provider).requirement
        except MarimoStudioError as error:
            issues.append(
                DependencyIssue("provider-unavailable", f"{view.provider}: {error}")
            )
            continue
        if requirement not in providers:
            providers.append(requirement)
    declarations["providers"] = _requirements(providers)
    installed: dict[str, str | None] = {}
    authored = _installed_requirements(
        (*declarations["project"], *declarations["notebook"]), issues, installed
    )
    for requirement in declarations["providers"]:
        name = canonicalize_name(requirement.name)
        extras = {canonicalize_name(extra) for extra in requirement.extras}
        if name not in authored or not extras.issubset(authored[name]):
            issues.append(
                DependencyIssue(
                    "undeclared-provider",
                    f"Declare {requirement} in the notebook or project environment",
                )
            )
    environment = _installed_requirements(declarations["providers"], issues, installed)
    declared = set(authored) | set(environment)
    if isinstance(project, Mapping) and isinstance(project.get("name"), str):
        declared.add(canonicalize_name(project["name"]))
    imports = _import_resolutions(notebook, root, declared, issues)
    return DependencyReport(
        notebook=notebook,
        project=root / "pyproject.toml" if root else None,
        python=sys.executable,
        declarations={
            source: tuple(map(str, values)) for source, values in declarations.items()
        },
        installed=installed,
        imports=imports,
        issues=tuple(dict.fromkeys(issues)),
    )
