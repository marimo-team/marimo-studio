"""Enforce Python package dependency direction from source imports."""

from __future__ import annotations

import ast
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

PACKAGE = Path("packages/marimo-studio/src/marimo_studio")
ROOT_FILES = frozenset({"__init__.py", "_composition.py", "_entrypoints.py", "asgi.py"})
PRIVATE_MARIMO_OWNERS = (
    "marimo_studio._compat",
    "marimo_studio._composition",
)
VIEW_PROVIDER_PACKAGE = "marimo_studio.view_providers"
VIEW_PROVIDER_PRIVATE_LAYERS = (
    "marimo_studio.view_providers._host",
    "marimo_studio.view_providers._builtin",
)
# The provider test kit drives the real host, so it may use the private layers.
PROVIDER_TEST_KIT = "marimo_studio.view_providers.testing"
BUILTIN_PROVIDERS = "marimo_studio.view_providers._builtin"
# Built-in providers import only the public provider SDK, their own package, and
# the shared libraries listed here, so each can move into its own distribution.
BUILTIN_SHARED_LIBRARIES = {
    "_deno": frozenset({"deno_obsnotebook", "deno_react", "deno_svelte"}),
}
# Core built-in providers ship with Studio and may also use these core modules.
CORE_BUILTIN_PROVIDERS = {
    "vanilla": (
        "marimo_studio._filesystem",
        "marimo_studio.errors",
        "marimo_studio.view_providers._css_resources",
        "marimo_studio.view_providers._document",
        "marimo_studio.view_providers._javascript",
    ),
}
PUBLIC_AUTHORING_FACADES = (
    "marimo_studio.agent",
    "marimo_studio.authoring",
)
FORBIDDEN_DEPENDENCIES = {
    "marimo_studio._workspace": (
        "marimo_studio._artifacts",
        "marimo_studio._projections",
        "marimo_studio.view_providers._host",
        "marimo_studio._views",
        "marimo_studio._server",
        "marimo_studio._cli",
        "marimo_studio.agent",
    ),
    "marimo_studio._artifacts": (
        "marimo_studio.view_providers._host.package_policy",
        "marimo_studio.view_providers._host.conformance",
        "marimo_studio.view_providers._host.registry",
        "marimo_studio._views",
    ),
    "marimo_studio.view_providers._host": (
        "marimo_studio._artifacts",
        "marimo_studio._views",
        "marimo_studio._workspace",
        "marimo_studio.view_providers._builtin",
    ),
    "marimo_studio.view_providers._builtin": ("marimo_studio.view_providers._host",),
    PROVIDER_TEST_KIT: (BUILTIN_PROVIDERS,),
    "marimo_studio._validation": ("marimo_studio.agent",),
    "marimo_studio._filesystem": (
        "marimo_studio._artifacts",
        "marimo_studio.view_providers._host",
        "marimo_studio._views",
        "marimo_studio._server",
        "marimo_studio._cli",
        "marimo_studio.agent",
    ),
    "marimo_studio._projections": (
        "marimo_studio._artifacts",
        "marimo_studio.view_providers._host",
        "marimo_studio._views",
        "marimo_studio._server",
        "marimo_studio._cli",
        "marimo_studio.agent",
    ),
}


def _module(path: Path) -> str:
    parts = list(path.relative_to(PACKAGE).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(("marimo_studio", *parts))


def _import_base(current: str, path: Path, node: ast.ImportFrom) -> str:
    if node.level == 0:
        return node.module or ""
    package = current.split(".")
    if path.name != "__init__.py":
        package.pop()
    package = package[: len(package) - (node.level - 1)]
    if node.module:
        package.extend(node.module.split("."))
    return ".".join(package)


def _canonical(name: str, modules: set[str]) -> str | None:
    while name and name not in modules:
        name = name.rpartition(".")[0]
    return name if name in modules else None


def _imports(
    path: Path,
    module: str,
    modules: set[str],
) -> tuple[set[str], set[str]]:
    internal: set[str] = set()
    private_marimo: set[str] = set()
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = tuple(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = _import_base(module, path, node)
            names = (base, *(f"{base}.{alias.name}" for alias in node.names))
        else:
            continue
        for name in names:
            if name.startswith("marimo._"):
                private_marimo.add(name)
            target = _canonical(name, modules)
            if target is None or target == module:
                continue
            internal.add(target)
            # Importing a submodule first runs every enclosing package.
            parts = target.split(".")
            for size in range(2, len(parts)):
                package = ".".join(parts[:size])
                if package in modules and not _under(module, package):
                    internal.add(package)
    return internal, private_marimo


def _components(graph: dict[str, set[str]]) -> tuple[tuple[str, ...], ...]:
    indices: dict[str, int] = {}
    lowlinks: dict[str, int] = {}
    stack: list[str] = []
    stacked: set[str] = set()
    found: list[tuple[str, ...]] = []

    def visit(module: str) -> None:
        indices[module] = lowlinks[module] = len(indices)
        stack.append(module)
        stacked.add(module)
        for dependency in graph[module]:
            if dependency not in indices:
                visit(dependency)
                lowlinks[module] = min(lowlinks[module], lowlinks[dependency])
            elif dependency in stacked:
                lowlinks[module] = min(lowlinks[module], indices[dependency])
        if lowlinks[module] != indices[module]:
            return
        component: list[str] = []
        while True:
            dependency = stack.pop()
            stacked.remove(dependency)
            component.append(dependency)
            if dependency == module:
                break
        found.append(tuple(sorted(component)))

    for module in sorted(graph):
        if module not in indices:
            visit(module)
    return tuple(found)


def _under(module: str, prefix: str) -> bool:
    return module == prefix or module.startswith(f"{prefix}.")


def violations() -> tuple[str, ...]:
    paths = tuple(sorted(PACKAGE.rglob("*.py")))
    path_by_module = {_module(path): path for path in paths}
    modules = set(path_by_module)
    graph: dict[str, set[str]] = {}
    private_imports: dict[str, set[str]] = {}
    for module, path in path_by_module.items():
        graph[module], private_imports[module] = _imports(path, module, modules)

    failures: list[str] = []
    unexpected_root_files = sorted(
        path.name for path in PACKAGE.glob("*.py") if path.name not in ROOT_FILES
    )
    if unexpected_root_files:
        failures.append(
            "public-looking root modules: " + ", ".join(unexpected_root_files)
        )
    for component in _components(graph):
        if len(component) > 1:
            failures.append("dependency cycle: " + " -> ".join(component))
    for owner, imports in sorted(private_imports.items()):
        if imports and not any(
            _under(owner, allowed) for allowed in PRIVATE_MARIMO_OWNERS
        ):
            failures.append(
                f"private Marimo import outside compatibility: {owner} imports "
                + ", ".join(sorted(imports))
            )
    for owner, forbidden in FORBIDDEN_DEPENDENCIES.items():
        for module in sorted(item for item in graph if _under(item, owner)):
            for dependency in sorted(graph[module]):
                if any(_under(dependency, prefix) for prefix in forbidden):
                    failures.append(f"forbidden dependency: {module} -> {dependency}")
    for module in sorted(
        item
        for item in graph
        if not any(_under(item, facade) for facade in PUBLIC_AUTHORING_FACADES)
    ):
        for dependency in sorted(graph[module]):
            if any(_under(dependency, facade) for facade in PUBLIC_AUTHORING_FACADES):
                failures.append(f"forbidden dependency: {module} -> {dependency}")
    contract_modules = sorted(
        module
        for module in graph
        if _under(module, VIEW_PROVIDER_PACKAGE)
        and module != PROVIDER_TEST_KIT
        and not any(_under(module, private) for private in VIEW_PROVIDER_PRIVATE_LAYERS)
    )
    for module in contract_modules:
        for dependency in sorted(graph[module]):
            if _under(dependency, "marimo_studio._projections") or any(
                _under(dependency, private) for private in VIEW_PROVIDER_PRIVATE_LAYERS
            ):
                failures.append(f"forbidden dependency: {module} -> {dependency}")
    for module in sorted(
        item for item in graph if not _under(item, VIEW_PROVIDER_PACKAGE)
    ):
        for dependency in sorted(graph[module]):
            if _under(dependency, BUILTIN_PROVIDERS):
                failures.append(f"forbidden dependency: {module} -> {dependency}")
    failures.extend(_builtin_provider_violations(graph, path_by_module))
    return tuple(failures)


def _sdk_names() -> frozenset[str]:
    tree = ast.parse((PACKAGE / "view_providers/__init__.py").read_text("utf-8"))
    for node in tree.body:
        if (
            isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id == "__all__"
                for target in node.targets
            )
            and isinstance(node.value, ast.List)
        ):
            return frozenset(
                item.value
                for item in node.value.elts
                if isinstance(item, ast.Constant) and isinstance(item.value, str)
            )
    raise RuntimeError("marimo_studio.view_providers declares no __all__")


def _builtin_provider_violations(
    graph: dict[str, set[str]],
    path_by_module: dict[str, Path],
) -> list[str]:
    """Keep each built-in provider on the public SDK and its declared libraries."""
    public = _sdk_names()
    failures: list[str] = []
    for module in sorted(item for item in graph if _under(item, BUILTIN_PROVIDERS)):
        if module == BUILTIN_PROVIDERS:
            continue
        owner = module.removeprefix(f"{BUILTIN_PROVIDERS}.").split(".")[0]
        allowed = (
            f"{BUILTIN_PROVIDERS}.{owner}",
            *(
                f"{BUILTIN_PROVIDERS}.{library}"
                for library, users in BUILTIN_SHARED_LIBRARIES.items()
                if owner in users
            ),
            *CORE_BUILTIN_PROVIDERS.get(owner, ()),
        )
        for dependency in sorted(graph[module]):
            if dependency in {VIEW_PROVIDER_PACKAGE, BUILTIN_PROVIDERS}:
                continue
            if not any(_under(dependency, prefix) for prefix in allowed):
                failures.append(
                    f"built-in provider dependency: {module} -> {dependency}"
                )
        tree = ast.parse(path_by_module[module].read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            # Attribute access on a module import would reach private SDK names.
            if isinstance(node, ast.Import) and any(
                alias.name == VIEW_PROVIDER_PACKAGE for alias in node.names
            ):
                failures.append(
                    f"built-in provider imports the SDK module instead of its "
                    f"public names: {module}"
                )
            if (
                isinstance(node, ast.ImportFrom)
                and node.module == VIEW_PROVIDER_PACKAGE
            ):
                for alias in node.names:
                    if alias.name not in public:
                        failures.append(
                            f"built-in provider uses a non-public SDK name: "
                            f"{module} -> {VIEW_PROVIDER_PACKAGE}.{alias.name}"
                        )
    return failures


def _fresh_import(module: str) -> str | None:
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            "import importlib, sys; importlib.import_module(sys.argv[1])",
            module,
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )
    if completed.returncode == 0:
        return None
    detail = (completed.stderr or completed.stdout).strip().splitlines()
    message = detail[-1] if detail else f"exit {completed.returncode}"
    return f"fresh import failed: {module}: {message}"


def fresh_import_violations() -> tuple[str, ...]:
    """Import every regular module in an independent package state."""
    modules = tuple(
        sorted(
            _module(path)
            for path in PACKAGE.rglob("*.py")
            if _module(path) != "marimo_studio.asgi"
        )
    )
    with ThreadPoolExecutor(max_workers=min(8, len(modules))) as executor:
        failures = tuple(executor.map(_fresh_import, modules))
    return tuple(failure for failure in failures if failure is not None)


def main() -> int:
    failures = violations()
    if not failures:
        failures = fresh_import_violations()
    if failures:
        sys.stderr.write("\n".join(failures) + "\n")
        return 1
    print("Python architecture check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
