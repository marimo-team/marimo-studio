from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import AbstractContextManager, contextmanager
from pathlib import Path
from threading import Event

import pytest
from marimo._environments.script_metadata import notebook_file_lock

import marimo_studio._notebook.locking as locking_module
import marimo_studio.authoring as studio_authoring
from marimo_studio._workspace import load_studio
from marimo_studio.errors import WorkspaceGenerationConflictError

from ._workspace_lifecycle_support import _workspace_with_report


@pytest.mark.parametrize("project", [False, True], ids=["notebook", "pyproject"])
def test_make_default_serves_the_view_at_the_main_route(
    notebook_path: Path,
    project: bool,
) -> None:
    workspace = _workspace_with_report(notebook_path, project=project)
    before = load_studio(notebook_path)

    report = asyncio.run(workspace.view("report").make_default())

    after = load_studio(notebook_path)
    assert after.config_source == ("pyproject" if project else "notebook")
    assert after.default_view == "report"
    assert after.catalog_generation != before.catalog_generation
    assert after.view_generations == before.view_generations
    assert report.catalog_generation == after.catalog_generation
    assert report.generation == after.view_generations["report"]
    assert asyncio.run(report.inspect()).view == "report"


def test_make_default_on_the_current_default_leaves_the_configuration(
    notebook_path: Path,
) -> None:
    _workspace_with_report(notebook_path)
    before = load_studio(notebook_path)
    source = notebook_path.read_text(encoding="utf-8").replace(
        'default = "dashboard"',
        "default = 'dashboard'",
    )
    notebook_path.write_text(source, encoding="utf-8")
    workspace = studio_authoring.open_workspace(notebook_path)

    dashboard = asyncio.run(workspace.view("dashboard").make_default())

    assert notebook_path.read_text(encoding="utf-8") == source
    assert dashboard.generation == before.view_generations["dashboard"]


def test_make_default_rejects_handles_from_an_earlier_catalog(
    notebook_path: Path,
) -> None:
    workspace = _workspace_with_report(notebook_path)
    dashboard = workspace.view("dashboard")
    asyncio.run(workspace.view("report").make_default())

    with pytest.raises(WorkspaceGenerationConflictError):
        asyncio.run(dashboard.make_default())
    assert load_studio(notebook_path).default_view == "report"


def test_make_default_waits_for_a_marimo_notebook_save(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = _workspace_with_report(notebook_path)
    create_lock = locking_module.create_notebook_write_lock
    waiting = Event()

    def observed_lock() -> Callable[[Path], AbstractContextManager[None]]:
        lock = create_lock()

        @contextmanager
        def wait_then_hold(path: Path) -> Iterator[None]:
            waiting.set()
            with lock(path):
                yield

        return wait_then_hold

    monkeypatch.setattr(locking_module, "create_notebook_write_lock", observed_lock)

    with ThreadPoolExecutor(max_workers=1) as executor:
        with notebook_file_lock(str(notebook_path)):
            pending = executor.submit(
                asyncio.run, workspace.view("report").make_default()
            )
            if not waiting.wait(timeout=10):
                if pending.done():
                    pending.result()
                pytest.fail("make_default did not request the notebook write lock")
            assert load_studio(notebook_path).default_view == "dashboard"
        pending.result(timeout=10)

    assert load_studio(notebook_path).default_view == "report"
