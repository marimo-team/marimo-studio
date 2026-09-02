from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

import marimo_studio._compat.browser_runtime as browser_runtime
from marimo_studio._compat.browser_runtime import PrivateBrowserRuntimeProjector
from marimo_studio._delivery.browser_ports import BrowserRuntimeCell


def test_browser_projection_cache_reuses_one_immutable_source_build(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    builds = 0
    lock = threading.Lock()

    def execution_cells(
        _notebook: Path,
        code: str,
    ) -> tuple[tuple[BrowserRuntimeCell, ...], str]:
        nonlocal builds
        with lock:
            builds += 1
        return (BrowserRuntimeCell("bootstrap", code),), "bootstrap"

    monkeypatch.setattr(browser_runtime, "browser_notebook_source", lambda _p, s: s)
    monkeypatch.setattr(browser_runtime, "_execution_cells", execution_cells)
    projector = PrivateBrowserRuntimeProjector(version="1.2.3", commit="release")
    notebook = tmp_path / "notebook.py"

    first = projector.project(notebook, "value = 1\n")
    assert projector.project(notebook, "value = 1\n") is first
    assert builds == 1

    projector.commit = "next-release"
    next_release = projector.project(notebook, "value = 1\n")
    assert next_release is not first
    assert next_release.commit == "next-release"
    assert builds == 2

    with ThreadPoolExecutor(max_workers=8) as executor:
        concurrent = tuple(
            executor.map(
                lambda _index: projector.project(notebook, "value = 2\n"),
                range(16),
            )
        )

    assert builds == 3
    assert all(projection is concurrent[0] for projection in concurrent)
    assert concurrent[0] is not first


def test_distinct_browser_projection_keys_build_outside_the_cache_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entered = threading.Barrier(2)

    def execution_cells(
        _notebook: Path,
        code: str,
    ) -> tuple[tuple[BrowserRuntimeCell, ...], str]:
        entered.wait(timeout=2)
        return (BrowserRuntimeCell("bootstrap", code),), "bootstrap"

    monkeypatch.setattr(browser_runtime, "browser_notebook_source", lambda _p, s: s)
    monkeypatch.setattr(browser_runtime, "_execution_cells", execution_cells)
    projector = PrivateBrowserRuntimeProjector(version="1.2.3", commit="release")

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(
            projector.project,
            tmp_path / "first.py",
            "value = 1\n",
        )
        second = executor.submit(
            projector.project,
            tmp_path / "second.py",
            "value = 2\n",
        )

    assert first.result().code == "value = 1\n"
    assert second.result().code == "value = 2\n"


def test_browser_projection_failure_is_shared_and_retryable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    builds = 0
    entered = threading.Event()
    release = threading.Event()

    def execution_cells(
        _notebook: Path,
        code: str,
    ) -> tuple[tuple[BrowserRuntimeCell, ...], str]:
        nonlocal builds
        builds += 1
        if builds == 1:
            entered.set()
            assert release.wait(timeout=2)
            raise RuntimeError("compile failed")
        return (BrowserRuntimeCell("bootstrap", code),), "bootstrap"

    monkeypatch.setattr(browser_runtime, "browser_notebook_source", lambda _p, s: s)
    monkeypatch.setattr(browser_runtime, "_execution_cells", execution_cells)
    projector = PrivateBrowserRuntimeProjector(version="1.2.3", commit="release")
    notebook = tmp_path / "notebook.py"

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(projector.project, notebook, "value = 1\n")
        assert entered.wait(timeout=1)
        second = executor.submit(projector.project, notebook, "value = 1\n")
        release.set()
        with pytest.raises(RuntimeError, match="compile failed"):
            first.result()
        with pytest.raises(RuntimeError, match="compile failed"):
            second.result()

    projection = projector.project(notebook, "value = 1\n")

    assert projection.code == "value = 1\n"
    assert builds == 2


def test_browser_projection_key_includes_the_notebook_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    notebooks: list[Path] = []

    def browser_source(notebook: Path, source: str) -> str:
        notebooks.append(notebook)
        return source

    monkeypatch.setattr(browser_runtime, "browser_notebook_source", browser_source)
    monkeypatch.setattr(
        browser_runtime,
        "_execution_cells",
        lambda _notebook, code: (
            (BrowserRuntimeCell("bootstrap", code),),
            "bootstrap",
        ),
    )
    projector = PrivateBrowserRuntimeProjector(version="1.2.3", commit="release")

    projector.project(tmp_path / "first.py", "value = 1\n")
    projector.project(tmp_path / "second.py", "value = 1\n")

    assert notebooks == [tmp_path / "first.py", tmp_path / "second.py"]
