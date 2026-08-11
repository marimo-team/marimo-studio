from __future__ import annotations

import asyncio
import gc
import weakref
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event, RLock
from typing import Any, cast

import pytest
from marimo._ast.cell import CellConfig
from marimo._messaging.notebook.document import NotebookCell
from marimo._server.models.models import SaveNotebookRequest
from marimo._session.events import SessionEventBus
from marimo._session.extensions.types import ExtensionRegistry
from marimo._session.notebook.file_manager import AppFileManager
from marimo._session.session import Session
from marimo._types.ids import CellId_t

import marimo_studio._server.cell_alias_policy as cell_alias_policy
from marimo_studio._capabilities import ServerHandle, ServerLocation
from marimo_studio._compat.server.gateway import _LocationHandle
from marimo_studio._compat.server.notebook_save import (
    PrivateNotebookSaveTransform,
    _SourceTransformExtension,
)
from marimo_studio._server.cell_alias_policy import CellAliasSourcePolicy
from marimo_studio._workspace import load_studio
from marimo_studio.errors import CompatibilityError
from marimo_studio.workspace import bind_cell, ensure_view, resolve_studio

from .helpers import empty_notebook_source

_DUPLICATE_CELL = """\
@app.cell
def _():
    1
    return
"""


class _Session:
    def __init__(self, manager: AppFileManager) -> None:
        self.initialization_id = str(manager.path)
        self.app_file_manager = manager
        self.extensions = ExtensionRegistry()
        self._event_bus = SessionEventBus()

    @property
    def document(self) -> Any:
        return self.app_file_manager.app.cell_manager.document

    def close(self) -> None:
        for extension in self.extensions:
            extension.on_detach()


class _Manager:
    def __init__(self, *sessions: _Session) -> None:
        self._event_bus = SessionEventBus()
        self.sessions = {
            f"session-{index}": session for index, session in enumerate(sessions)
        }


class _ObservedRLock:
    def __init__(self) -> None:
        self._lock = RLock()
        self.contended = Event()

    def __enter__(self) -> _ObservedRLock:
        if not self._lock.acquire(blocking=False):
            self.contended.set()
            self._lock.acquire()
        return self

    def __exit__(self, *_: object) -> None:
        self._lock.release()


def _location(notebook: Path, manager: _Manager) -> ServerLocation:
    return ServerLocation(
        notebook=notebook.resolve(),
        file_key=str(notebook),
        base_url="",
        mode="edit",
        routing_query=(),
        handle=ServerHandle(
            _LocationHandle(
                config_manager=object(),
                state=object(),
                session_manager=manager,
            )
        ),
    )


def _enable_sync(
    notebook: Path,
    session: _Session,
) -> PrivateNotebookSaveTransform:
    adapter = PrivateNotebookSaveTransform(CellAliasSourcePolicy())
    adapter.enable(_location(notebook, _Manager(session)))
    return adapter


def _append_cells(notebook: Path, cells: str) -> None:
    notebook.write_text(
        empty_notebook_source().replace(
            "\n\nif __name__", f"\n\n{cells}\n\nif __name__"
        ),
        encoding="utf-8",
    )


def _duplicate_notebook(notebook: Path, count: int) -> None:
    _append_cells(notebook, "\n\n\n".join([_DUPLICATE_CELL] * count))


def _cell_with_code(cell: NotebookCell, code: str) -> NotebookCell:
    return NotebookCell(
        id=cell.id,
        code=code,
        name=cell.name,
        config=cell.config,
    )


def _save_cells(
    manager: AppFileManager,
    cells: Sequence[NotebookCell],
    *,
    persist: bool = True,
) -> str:
    return manager.save(
        SaveNotebookRequest(
            cell_ids=[cell.id for cell in cells],
            codes=[cell.code for cell in cells],
            names=[cell.name for cell in cells],
            configs=[cell.config for cell in cells],
            filename=str(manager.path),
            persist=persist,
        )
    )


def _configure_project(notebook: Path) -> None:
    (notebook.parent / "pyproject.toml").write_text(
        f"""\
[tool.marimo-studio]
notebook = "{notebook.name}"
default = "main"
""",
        encoding="utf-8",
    )


def test_live_save_tracks_aliases_across_reorder_and_subsequent_edits(
    notebook_path: Path,
) -> None:
    ensure_view(notebook_path, "main")
    manager = AppFileManager(notebook_path)
    session = _Session(manager)
    _enable_sync(notebook_path, session)
    first, second = tuple(session.document.cells)
    inserted = NotebookCell(
        id=CellId_t("inserted"),
        code="inserted = 1",
        name="_",
        config=CellConfig(),
    )
    first_source = _save_cells(
        manager,
        (
            inserted,
            _cell_with_code(second, second.code.replace("x * 2", "x * 5")),
            _cell_with_code(first, first.code.replace("x = 2", "x = 10")),
        ),
    )

    first_resolved = resolve_studio(load_studio(notebook_path))
    assert first_source == notebook_path.read_text(encoding="utf-8")
    assert first_resolved.aliases["cell-1"].index == 2
    assert first_resolved.aliases["cell-2"].index == 1
    assert first_resolved.view().diagnostics == ()

    current = tuple(session.document.cells)
    _save_cells(
        manager,
        tuple(
            _cell_with_code(cell, cell.code.replace("x * 5", "x * 7"))
            for cell in current
        ),
    )

    second_resolved = resolve_studio(load_studio(notebook_path))
    assert second_resolved.aliases["cell-1"].index == 2
    assert second_resolved.aliases["cell-2"].index == 1
    assert second_resolved.view().diagnostics == ()


def test_live_save_tracks_alias_rebound_by_another_process(
    notebook_path: Path,
) -> None:
    ensure_view(notebook_path)
    manager = AppFileManager(notebook_path)
    session = _Session(manager)
    _enable_sync(notebook_path, session)
    first, second = tuple(session.document.cells)
    inserted = NotebookCell(
        id=CellId_t("inserted"),
        code="external = 1\nexternal",
        name="_",
        config=CellConfig(),
    )
    _save_cells(manager, (first, second, inserted))

    bind_cell(load_studio(notebook_path), "cell-2", 2, overwrite=True)
    current = tuple(session.document.cells)
    _save_cells(
        manager,
        tuple(
            _cell_with_code(cell, cell.code.replace("external = 1", "external = 2"))
            if cell.id == inserted.id
            else cell
            for cell in current
        ),
    )

    workspace = load_studio(notebook_path)
    resolved = resolve_studio(workspace)
    assert workspace.cells["cell-2"] == resolved.notebook.cells[2].ref
    assert resolved.aliases["cell-2"].index == 2
    assert resolved.view().diagnostics == ()


def test_code_mode_save_updates_aliases(
    notebook_path: Path,
) -> None:
    ensure_view(notebook_path)
    manager = AppFileManager(notebook_path)
    session = _Session(manager)
    _enable_sync(notebook_path, session)
    cells = tuple(session.document.cells)
    updated = [
        _cell_with_code(cell, cell.code.replace("x * 2", "x * 5")) for cell in cells
    ]

    source = manager.save_from_cells(updated)

    resolved = resolve_studio(load_studio(notebook_path))
    assert source == notebook_path.read_text(encoding="utf-8")
    assert resolved.aliases["cell-2"].index == 1
    assert resolved.view().diagnostics == ()


def test_non_persistent_save_returns_refreshed_source_without_writing(
    notebook_path: Path,
) -> None:
    ensure_view(notebook_path)
    before = notebook_path.read_text(encoding="utf-8")
    manager = AppFileManager(notebook_path)
    _enable_sync(notebook_path, _Session(manager))
    cells = tuple(manager.app.cell_manager.document.cells)
    updated = tuple(
        _cell_with_code(cell, cell.code.replace("x * 2", "x * 5")) for cell in cells
    )

    generated = _save_cells(manager, updated, persist=False)

    assert notebook_path.read_text(encoding="utf-8") == before
    assert "x * 5" in generated


def test_notebook_rename_keeps_native_save_available(notebook_path: Path) -> None:
    ensure_view(notebook_path)
    manager = AppFileManager(notebook_path)
    _enable_sync(notebook_path, _Session(manager))
    renamed = notebook_path.with_name("renamed.py")

    manager.rename(renamed)

    source = _save_cells(
        manager,
        tuple(
            _cell_with_code(cell, cell.code.replace("x * 2", "x * 5"))
            for cell in manager.app.cell_manager.document.cells
        ),
    )

    assert source == renamed.read_text(encoding="utf-8")
    assert "x * 5" in source


def test_project_config_tracks_edits_and_deletions(notebook_path: Path) -> None:
    _configure_project(notebook_path)
    ensure_view(notebook_path)
    manager = AppFileManager(notebook_path)
    session = _Session(manager)
    _enable_sync(notebook_path, session)
    cells = tuple(session.document.cells)

    _save_cells(
        manager,
        tuple(
            _cell_with_code(cell, cell.code.replace("x * 2", "x * 5")) for cell in cells
        ),
    )

    updated = load_studio(notebook_path)
    resolved = resolve_studio(updated)
    assert "x * 5" in notebook_path.read_text(encoding="utf-8")
    assert updated.cells["cell-2"] == resolved.notebook.cells[1].ref
    assert resolved.view().diagnostics == ()

    _first, second = tuple(session.document.cells)
    _save_cells(manager, (second,))

    deleted = load_studio(notebook_path)
    resolved = resolve_studio(deleted)
    assert set(deleted.cells) == {"cell-2"}
    assert resolved.aliases["cell-2"].index == 0
    assert {(item.target, item.code) for item in resolved.view().diagnostics} == {
        ("cell-1", "cell-not-found")
    }


def test_project_alias_write_failure_is_visible(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_project(notebook_path)
    ensure_view(notebook_path)
    manager = AppFileManager(notebook_path)
    _enable_sync(notebook_path, _Session(manager))
    cells = tuple(manager.app.cell_manager.document.cells)

    def fail_write(*_: object, **__: object) -> None:
        raise OSError("configuration is read-only")

    monkeypatch.setattr(cell_alias_policy, "_write_cell_bindings", fail_write)

    with pytest.raises(OSError, match="configuration is read-only"):
        _save_cells(
            manager,
            tuple(
                _cell_with_code(cell, cell.code.replace("x * 2", "x * 5"))
                for cell in cells
            ),
        )

    assert "x * 5" in notebook_path.read_text(encoding="utf-8")


def test_live_edit_of_duplicate_cells_keeps_distinct_aliases(
    notebook_path: Path,
) -> None:
    _duplicate_notebook(notebook_path, 2)
    ensure_view(notebook_path)
    manager = AppFileManager(notebook_path)
    _enable_sync(notebook_path, _Session(manager))
    first, second = tuple(manager.app.cell_manager.document.cells)

    _save_cells(
        manager,
        (_cell_with_code(first, first.code.replace("1", "2")), second),
    )

    resolved = resolve_studio(load_studio(notebook_path))
    assert resolved.aliases["cell-1"].index == 0
    assert resolved.aliases["cell-2"].index == 1
    assert resolved.view().diagnostics == ()


def test_live_deletion_renumbers_every_surviving_duplicate_alias(
    notebook_path: Path,
) -> None:
    _duplicate_notebook(notebook_path, 3)
    ensure_view(notebook_path)
    manager = AppFileManager(notebook_path)
    _enable_sync(notebook_path, _Session(manager))
    _first, second, third = tuple(manager.app.cell_manager.document.cells)

    _save_cells(manager, (second, third))

    workspace = load_studio(notebook_path)
    resolved = resolve_studio(workspace)
    assert set(workspace.cells) == {"cell-2", "cell-3"}
    assert resolved.aliases["cell-2"].index == 0
    assert resolved.aliases["cell-3"].index == 1
    assert {(item.target, item.code) for item in resolved.view().diagnostics} == {
        ("cell-1", "cell-not-found")
    }


def test_offline_duplicate_edit_does_not_collapse_distinct_aliases(
    notebook_path: Path,
) -> None:
    _duplicate_notebook(notebook_path, 2)
    ensure_view(notebook_path)
    manager = AppFileManager(notebook_path)
    first, second = tuple(manager.app.cell_manager.document.cells)
    _save_cells(
        manager,
        (_cell_with_code(first, first.code.replace("1", "2")), second),
    )

    resolved = resolve_studio(load_studio(notebook_path))

    assert resolved.aliases == {}
    assert {(item.target, item.code) for item in resolved.view().diagnostics} == {
        ("cell-1", "cell-binding-ambiguous"),
        ("cell-2", "cell-binding-ambiguous"),
    }


def test_live_save_does_not_guess_after_offline_reorder(
    notebook_path: Path,
) -> None:
    ensure_view(notebook_path)
    manager = AppFileManager(notebook_path)
    first, second = tuple(manager.app.cell_manager.document.cells)
    _save_cells(
        manager,
        (
            _cell_with_code(second, second.code.replace("x * 2", "x * 5")),
            _cell_with_code(first, first.code.replace("x = 2", "x = 10")),
        ),
    )
    restarted = AppFileManager(notebook_path)

    _enable_sync(notebook_path, _Session(restarted))
    _save_cells(restarted, tuple(restarted.app.cell_manager.document.cells))

    unresolved = resolve_studio(load_studio(notebook_path))
    assert {(item.target, item.code) for item in unresolved.view().diagnostics} == {
        ("cell-1", "cell-binding-stale"),
        ("cell-2", "cell-binding-stale"),
    }


def test_session_close_restores_save_method_and_releases_state(
    notebook_path: Path,
) -> None:
    ensure_view(notebook_path)
    manager = AppFileManager(notebook_path)
    original_save_file = manager._save_file
    session = _Session(manager)
    _enable_sync(notebook_path, session)
    extension = session.extensions.get(_SourceTransformExtension)
    assert extension is not None
    assert manager._save_file is not original_save_file
    manager_ref = weakref.ref(manager)
    session_ref = weakref.ref(session)

    session.close()

    assert manager._save_file == original_save_file
    del extension, original_save_file, session, manager
    gc.collect()
    assert session_ref() is None
    assert manager_ref() is None


def test_session_detach_retries_after_save_method_owner_unwinds(
    notebook_path: Path,
) -> None:
    ensure_view(notebook_path)
    manager = AppFileManager(notebook_path)
    original_save_file = manager._save_file
    session = _Session(manager)
    _enable_sync(notebook_path, session)
    extension = session.extensions.get(_SourceTransformExtension)
    assert extension is not None
    studio_save_file = manager._save_file

    def foreign_save_file(
        path: Path,
        *,
        notebook: object,
        persist: bool,
        previous_path: Path | None = None,
    ) -> str:
        del path, notebook, persist, previous_path
        return "foreign"

    cast(Any, manager)._save_file = foreign_save_file
    with pytest.raises(CompatibilityError, match="before Studio could restore"):
        extension.on_detach()

    assert extension.session is session
    cast(Any, manager)._save_file = studio_save_file
    extension.on_detach()

    assert manager._save_file == original_save_file
    with pytest.raises(RuntimeError, match="not attached"):
        _ = extension.session


def test_session_detach_waits_for_in_flight_save(notebook_path: Path) -> None:
    ensure_view(notebook_path)
    manager = AppFileManager(notebook_path)
    session = _Session(manager)
    _enable_sync(notebook_path, session)
    extension = session.extensions.get(_SourceTransformExtension)
    assert extension is not None
    observed_lock = _ObservedRLock()
    cast(Any, manager)._save_lock = observed_lock
    write_started = Event()
    continue_write = Event()
    original_write = manager.storage.write

    def blocking_write(path: Path, source: str) -> None:
        write_started.set()
        assert continue_write.wait(timeout=2)
        original_write(path, source)

    cast(Any, manager.storage).write = blocking_write

    updated = tuple(
        _cell_with_code(cell, cell.code.replace("x * 2", "x * 5"))
        for cell in manager.app.cell_manager.document.cells
    )

    with ThreadPoolExecutor(max_workers=2) as executor:
        save = executor.submit(_save_cells, manager, updated)
        assert write_started.wait(timeout=2)
        detach = executor.submit(extension.on_detach)
        try:
            assert observed_lock.contended.wait(timeout=2)
        finally:
            continue_write.set()
        source = save.result(timeout=2)
        detach.result(timeout=2)

    assert source == notebook_path.read_text(encoding="utf-8")
    assert resolve_studio(load_studio(notebook_path)).view().diagnostics == ()


def test_listener_attaches_sessions_created_after_enable(notebook_path: Path) -> None:
    ensure_view(notebook_path)
    manager = _Manager()
    adapter = PrivateNotebookSaveTransform(CellAliasSourcePolicy())
    adapter.enable(_location(notebook_path, manager))
    session = _Session(AppFileManager(notebook_path))

    asyncio.run(manager._event_bus.emit_session_created(cast(Session, session)))

    assert session.extensions.get(_SourceTransformExtension) is not None
