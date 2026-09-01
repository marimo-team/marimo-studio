from __future__ import annotations

import shutil
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest

import marimo_studio._workspace.bindings as workspace_bindings
from marimo_studio._notebook.inspection import inspect_notebook
from marimo_studio._notebook.records import CellRef, NotebookSpec
from marimo_studio._views.api import bind_cell, prepare_view
from marimo_studio._workspace import load_studio
from marimo_studio.errors import (
    BindingError,
    ConfigurationError,
    WorkspaceGenerationConflictError,
)

from ._workspace_lifecycle_support import (
    _project_configuration,
    _write_before_transaction,
)


def test_bind_cell_rejects_a_concurrent_notebook_save(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepare_view(notebook_path)
    studio = load_studio(notebook_path)
    transaction = workspace_bindings.write_file_transaction
    changed = notebook_path.read_text(encoding="utf-8") + "# concurrent save\n"

    monkeypatch.setattr(
        workspace_bindings,
        "write_file_transaction",
        _write_before_transaction(transaction, notebook_path, changed),
    )

    with pytest.raises(ConfigurationError, match="changed"):
        bind_cell(studio, "result", 1)

    assert notebook_path.read_text(encoding="utf-8") == changed
    assert "result" not in load_studio(notebook_path).cells


def test_bind_cell_rejects_a_concurrent_project_configuration_edit(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pyproject = _project_configuration(notebook_path)
    prepare_view(notebook_path)
    studio = load_studio(pyproject)
    transaction = workspace_bindings.write_file_transaction
    changed = pyproject.read_text(encoding="utf-8") + "# concurrent edit\n"

    monkeypatch.setattr(
        workspace_bindings,
        "write_file_transaction",
        _write_before_transaction(transaction, pyproject, changed),
    )

    with pytest.raises(ConfigurationError, match="changed"):
        bind_cell(studio, "result", 1)

    assert pyproject.read_text(encoding="utf-8") == changed
    assert "result" not in load_studio(pyproject).cells


def test_bind_cell_rejects_a_concurrent_project_notebook_save(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pyproject = _project_configuration(notebook_path)
    prepare_view(notebook_path)
    studio = load_studio(pyproject)
    transaction = workspace_bindings.write_file_transaction
    changed = notebook_path.read_text(encoding="utf-8") + "# concurrent save\n"

    monkeypatch.setattr(
        workspace_bindings,
        "write_file_transaction",
        _write_before_transaction(transaction, notebook_path, changed),
    )

    with pytest.raises(ConfigurationError, match="changed"):
        bind_cell(studio, "result", 1)

    assert notebook_path.read_text(encoding="utf-8") == changed
    assert "result" not in load_studio(pyproject).cells


def test_bind_cell_inspects_the_captured_notebook_source(
    notebook_path: Path,
) -> None:
    prepare_view(notebook_path)
    studio = load_studio(notebook_path)
    original = notebook_path.read_text(encoding="utf-8")
    inspected_paths: list[Path] = []

    def inspect_with_live_aba(
        path: str | Path,
        *,
        include_code: bool = False,
    ) -> NotebookSpec:
        inspected_paths.append(Path(path))
        notebook_path.write_text(
            original.replace("doubled = x * 2", "doubled = x * 3"),
            encoding="utf-8",
        )
        try:
            return inspect_notebook(path, include_code=include_code)
        finally:
            notebook_path.write_text(original, encoding="utf-8")

    result = workspace_bindings.bind_cell(
        studio,
        "captured-result",
        1,
        inspect_notebook=inspect_with_live_aba,
    )

    assert inspected_paths[0] != notebook_path
    assert result.cell.ref == inspect_notebook(notebook_path).cells[1].ref
    assert load_studio(notebook_path).cells["captured-result"] == result.cell.ref


def test_stale_workspace_cannot_bind_into_a_replacement_catalog(
    notebook_path: Path,
) -> None:
    prepare_view(notebook_path)
    observed = load_studio(notebook_path)
    retired = observed.view_root.with_name("retired-studio")
    observed.view_root.rename(retired)
    shutil.copytree(retired, observed.view_root)

    with pytest.raises(WorkspaceGenerationConflictError):
        bind_cell(observed, "result", 1)

    assert "result" not in load_studio(notebook_path).cells


def test_live_alias_update_rejects_a_replacement_catalog(
    notebook_path: Path,
) -> None:
    prepare_view(notebook_path)
    observed = load_studio(notebook_path)
    retired = observed.view_root.with_name("retired-studio")
    observed.view_root.rename(retired)
    shutil.copytree(retired, observed.view_root)

    with pytest.raises(WorkspaceGenerationConflictError):
        workspace_bindings._write_cell_bindings(
            observed,
            {"result": CellRef("a" * 64, "b" * 64)},
        )

    assert "result" not in load_studio(notebook_path).cells


def test_concurrent_distinct_bindings_allow_one_catalog_owner(
    notebook_path: Path,
) -> None:
    prepare_view(notebook_path)
    studio = load_studio(notebook_path)
    start = Barrier(2)

    def bind(alias: str, cell: int) -> str:
        start.wait()
        try:
            bind_cell(studio, alias, cell)
        except WorkspaceGenerationConflictError:
            return "conflict"
        return "bound"

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = tuple(
            future.result()
            for future in (
                executor.submit(bind, "first-result", 0),
                executor.submit(bind, "second-result", 1),
            )
        )

    assert sorted(results) == ["bound", "conflict"]
    assert (
        len({"first-result", "second-result"} & set(load_studio(notebook_path).cells))
        == 1
    )


def test_concurrent_same_alias_bindings_allow_one_writer(
    notebook_path: Path,
) -> None:
    prepare_view(notebook_path)
    studio = load_studio(notebook_path)
    start = Barrier(2)

    def bind(cell: int) -> str:
        start.wait()
        try:
            bind_cell(studio, "shared-result", cell)
        except (BindingError, WorkspaceGenerationConflictError):
            return "conflict"
        return "bound"

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = tuple(
            future.result()
            for future in (
                executor.submit(bind, 0),
                executor.submit(bind, 1),
            )
        )

    assert sorted(results) == ["bound", "conflict"]
    assert "shared-result" in load_studio(notebook_path).cells


def test_live_alias_update_rejects_an_intervening_same_alias_edit(
    notebook_path: Path,
) -> None:
    pyproject = _project_configuration(notebook_path)
    prepare_view(notebook_path)
    studio = load_studio(pyproject)
    observed = studio.cells["cell-2"]
    external = CellRef("a" * 64, "b" * 64)
    desired = CellRef("c" * 64, "d" * 64)
    pyproject.write_text(
        pyproject.read_text(encoding="utf-8").replace(str(observed), str(external)),
        encoding="utf-8",
    )

    with pytest.raises(WorkspaceGenerationConflictError):
        workspace_bindings._write_cell_bindings(
            studio,
            {"cell-2": desired},
        )

    assert load_studio(pyproject).cells["cell-2"] == external


def test_live_alias_update_requires_its_observed_catalog(
    notebook_path: Path,
) -> None:
    pyproject = _project_configuration(notebook_path)
    prepare_view(notebook_path)
    studio = load_studio(pyproject)
    observed = studio.cells["cell-2"]
    desired = CellRef("a" * 64, "b" * 64)
    pyproject.write_text(
        pyproject.read_text(encoding="utf-8").replace(str(observed), str(desired)),
        encoding="utf-8",
    )

    with pytest.raises(WorkspaceGenerationConflictError):
        workspace_bindings._write_cell_bindings(
            studio,
            {"cell-2": desired},
        )

    assert load_studio(pyproject).cells["cell-2"] == desired
