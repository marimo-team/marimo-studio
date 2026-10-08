"""Check a view provider through the same paths Studio uses.

``check_provider`` creates a view from each of the provider's starters in a
temporary workspace, then inspects, builds, and publishes it. Any problem
raises ``ProviderCheckError`` with the message Studio would show.

```python
from marimo_studio.view_providers.testing import check_provider

for view in check_provider("acme-views/report"):
    assert "index.html" in {path.as_posix() for path in view.published}
```

Pass an installed provider key to run the provider the way Studio loads it,
in a separate process for installed packages. Pass a provider object to check
it in this process before it is packaged.
"""

from __future__ import annotations

import ast
import asyncio
import contextvars
import hashlib
import sys
import tempfile
from collections.abc import Coroutine, Iterable, Mapping
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from dataclasses import dataclass
from importlib.metadata import EntryPoint
from importlib.util import find_spec
from pathlib import Path, PurePosixPath
from typing import cast

import marimo_studio.view_providers._host as host
from marimo_studio._artifacts.retention import lease_published_artifact
from marimo_studio._authoring.view_api import View
from marimo_studio._authoring.workspace_api import open_workspace
from marimo_studio._views.records import (
    StudioDiagnostic,
    ViewInspection,
)
from marimo_studio._workspace.config import canonical_view_root
from marimo_studio._workspace.project_manifest import (
    encode_view_manifest,
    load_view_project,
)
from marimo_studio.errors import MarimoStudioError
from marimo_studio.view_providers import (
    JsonValue,
    ProjectDiagnostic,
    ViewProvider,
)
from marimo_studio.view_providers import __all__ as sdk
from marimo_studio.view_providers._host.registry import (
    ProviderCandidate,
    ProviderRegistry,
)

SAMPLE_NOTEBOOK = """import marimo

app = marimo.App()


@app.cell
def _():
    metric = 42
    report = {"total": 42, "rows": [{"name": "north", "total": 42}]}
    metric
    return metric, report


if __name__ == "__main__":
    app.run()
"""


class ProviderCheckError(AssertionError):
    """A provider check found a problem that Studio would report."""


@dataclass(frozen=True)
class CheckedView:
    """One starter that Studio created, inspected, built, and published."""

    starter: str
    documents: tuple[PurePosixPath, ...]
    published: Mapping[PurePosixPath, bytes]
    warnings: tuple[str, ...]


def _describe(item: StudioDiagnostic | ProjectDiagnostic) -> str:
    if isinstance(item, ProjectDiagnostic):
        source = item.source
        location = (
            f"{source.path.as_posix()}:{source.line}:{source.column}: "
            if source is not None
            else ""
        )
    else:
        location = (
            f"{item.path}:{item.line or 1}:{item.column or 1}: "
            if item.path is not None
            else ""
        )
    return f"{location}{item.message}" + (f" Hint: {item.hint}" if item.hint else "")


class _LoadedEntryPoint:
    def __init__(self, provider: ViewProvider) -> None:
        self._provider = provider
        self.module = type(provider).__module__
        self.value = f"{self.module}:provider"

    def load(self) -> ViewProvider:
        return self._provider


def _registry(provider: ViewProvider, key: str) -> ProviderRegistry:
    distribution, _, registration = key.partition("/")
    return ProviderRegistry(
        (
            ProviderCandidate(
                registration=registration,
                distribution=distribution,
                version="0",
                entry_point=cast(EntryPoint, cast(object, _LoadedEntryPoint(provider))),
            ),
        )
    )


def _provider_module(provider: ViewProvider | str) -> str:
    if not isinstance(provider, str):
        return type(provider).__module__
    module = host.provider_registry().entry_module(provider)
    if module is None:
        raise ProviderCheckError(f"{provider} is not installed.")
    return module


def _private_imports(module: str) -> tuple[str, ...]:
    """Return Studio imports outside the SDK in the package that defines ``module``."""
    package = module.partition(".")[0]
    if package == "marimo_studio":
        return ()
    if package == "__main__":
        origin = getattr(sys.modules.get("__main__"), "__file__", None)
        files: Iterable[Path] = (Path(origin),) if origin else ()
    else:
        spec = find_spec(package)
        if spec is None:
            return ()
        if spec.origin is not None:
            root = Path(spec.origin)
            files = root.parent.rglob("*.py") if root.name == "__init__.py" else (root,)
        else:
            # A namespace package has no __init__.py, only search locations.
            files = (
                path
                for location in spec.submodule_search_locations or ()
                for path in Path(location).rglob("*.py")
            )
    found: set[str] = set()
    for path in files:
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                found.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                if node.module == _SDK:
                    found.update(
                        f"{_SDK}.{alias.name}"
                        for alias in node.names
                        if alias.name != "*" and alias.name not in sdk
                    )
                elif node.module == "marimo_studio":
                    found.update(f"marimo_studio.{alias.name}" for alias in node.names)
                else:
                    found.add(node.module)
    return tuple(
        sorted(
            name
            for name in found
            if name.partition(".")[0] == "marimo_studio" and name not in _PUBLIC
        )
    )


_SDK = "marimo_studio.view_providers"
_PUBLIC = frozenset({"marimo_studio", _SDK, f"{_SDK}.testing"})


def _tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if relative.parts[0] == ".artifacts" or not path.is_file():
            continue
        digest.update(relative.as_posix().encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


async def _check(
    key: str,
    notebook: Path,
    options: Mapping[str, JsonValue],
) -> tuple[CheckedView, ...]:
    workspace = open_workspace(notebook)
    starters = [item for item in await workspace.starters() if item.provider == key]
    if not starters:
        raise ProviderCheckError(f"{key} offers no starters.")
    checked: list[CheckedView] = []
    for index, starter in enumerate(starters):
        availability = starter.availability
        if not availability.available:
            action = f" {availability.action}" if availability.action else ""
            raise ProviderCheckError(
                f"{key} is unavailable: {availability.reason}{action}"
            )
        view = await workspace.create_view(f"check-{index}", starter=starter)
        root = canonical_view_root(notebook) / view.name
        if options:
            (root / "view.toml").write_text(
                encode_view_manifest(key, dict(options)), encoding="utf-8"
            )
        before = _tree_digest(root)
        first = await _inspection(view, starter.id)
        second = await _inspection(view, starter.id)
        if _tree_digest(root) != before:
            raise ProviderCheckError(f"{starter.id}: inspect() changed the project.")
        if second != first:
            raise ProviderCheckError(f"{starter.id}: inspect() is not repeatable.")
        documents = tuple(item.path for item in second.documents)
        build = await view.build()
        project = load_view_project(root)
        lease = lease_published_artifact(project, "development")
        if lease is None:
            raise ProviderCheckError(f"{starter.id}: the build published nothing.")
        with lease:
            published = {
                item.path: lease.read_bytes(item.path) for item in lease.artifact.files
            }
        checked.append(
            CheckedView(
                starter=starter.id,
                documents=documents,
                published=published,
                warnings=tuple(
                    _describe(item)
                    for item in build.issues
                    if item.severity == "warning"
                ),
            )
        )
    return tuple(checked)


async def _inspection(view: View, starter: str) -> ViewInspection:
    inspection = await view.inspect()
    errors = [item for item in inspection.diagnostics if item.severity == "error"]
    if errors:
        raise ProviderCheckError(
            f"{starter}: " + "\n".join(_describe(item) for item in errors)
        )
    return inspection


def _run(
    check: Coroutine[object, object, tuple[CheckedView, ...]],
) -> tuple[CheckedView, ...]:
    """Run ``check`` to completion and block until it finishes.

    A caller that already runs an event loop, such as an async test or a
    notebook cell, gets the check on a worker thread with the caller's context.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        running = False
    else:
        running = True
    # Outside the except block, so a failed check has no chained loop error.
    if not running:
        return asyncio.run(check)
    context = contextvars.copy_context()

    def run() -> tuple[CheckedView, ...]:
        return context.run(lambda: asyncio.run(check))

    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(run).result()


def check_provider(
    provider: ViewProvider | str,
    *,
    key: str = "local-provider/provider",
    notebook: str | Path | None = None,
    options: Mapping[str, JsonValue] | None = None,
) -> tuple[CheckedView, ...]:
    """Create, inspect, build, and publish every starter of ``provider``.

    ``provider`` is an installed provider key, or a provider object checked under
    ``key``. ``notebook`` defaults to a small notebook that defines ``metric`` and
    ``report``. ``options`` become the ``[options]`` table of each view's
    ``view.toml``. Raises ``ProviderCheckError`` for the first problem found.
    """
    private = _private_imports(_provider_module(provider))
    if private:
        raise ProviderCheckError(
            "The provider imports Studio outside marimo_studio.view_providers: "
            + ", ".join(private)
        )
    with tempfile.TemporaryDirectory(prefix="marimo-studio-check-") as directory:
        target = Path(directory, "notebook.py")
        source = Path(notebook).read_text("utf-8") if notebook else SAMPLE_NOTEBOOK
        target.write_text(source, encoding="utf-8")
        selected = (
            nullcontext()
            if isinstance(provider, str)
            else host.selected_registry(_registry(provider, key))
        )
        with selected:
            try:
                return _run(
                    _check(
                        provider if isinstance(provider, str) else key,
                        target,
                        options or {},
                    )
                )
            except MarimoStudioError as error:
                hint = f" Hint: {error.public_hint}" if error.public_hint else ""
                raise ProviderCheckError(f"{error}{hint}") from error


__all__ = ["CheckedView", "ProviderCheckError", "check_provider"]
