"""Keep configured cell aliases aligned with live Marimo saves."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Any, cast
from weakref import WeakKeyDictionary

from marimo._schemas.serialization import NotebookSerializationV1
from marimo._server.session_manager import SessionManager
from marimo._session.events import SessionEventBus, SessionEventListener
from marimo._session.extensions.types import EventAwareExtension
from marimo._session.session import Session, SessionImpl

from marimo_studio._cell_refs import (
    cell_refs,
    safe_cell_ref_matches,
    safe_cell_ref_updates,
)
from marimo_studio._compat.server.models import ServerLocation
from marimo_studio._compat.server.sessions import session_matches_notebook
from marimo_studio._workspace import discover_studio
from marimo_studio._workspace.bindings import _write_cell_bindings
from marimo_studio._workspace.metadata import (
    set_cell_bindings,
    updated_notebook_config_source,
)
from marimo_studio._workspace.models import StudioWorkspace
from marimo_studio.errors import MarimoStudioError
from marimo_studio.types import CellRef

_SaveFile = Callable[..., str]


@dataclass(frozen=True)
class _TrackedAlias:
    ref: CellRef
    runtime_id: str


class _CellAliasSync(EventAwareExtension):
    """Refresh semantic aliases at Marimo's notebook persistence boundary."""

    def __init__(self) -> None:
        super().__init__()
        self._aliases: dict[str, _TrackedAlias] = {}
        self._saved_live: tuple[tuple[CellRef, str], ...] = ()
        self._original_save_file: _SaveFile | None = None
        self._wrapped_save_file: _SaveFile | None = None

    def on_attach(self, session: Session, event_bus: SessionEventBus) -> None:
        super().on_attach(session, event_bus)
        manager = session.app_file_manager
        original_save_file = manager._save_file
        try:
            workspace = self._workspace()
            if workspace is not None:
                self._saved_live = self._live_refs()
                self._refresh_aliases(workspace, self._saved_live)

            def save_file(
                path: Path,
                *,
                notebook: NotebookSerializationV1,
                persist: bool,
                previous_path: Path | None = None,
            ) -> str:
                # Marimo owns serialization and autosave generation. Studio
                # finalizes notebook-local metadata before the durable write.
                with manager._save_lock:
                    if previous_path is not None:
                        return original_save_file(
                            path,
                            notebook=notebook,
                            persist=persist,
                            previous_path=previous_path,
                        )
                    source = original_save_file(
                        path,
                        notebook=notebook,
                        persist=False,
                        previous_path=previous_path,
                    )
                    return self._save_source(path, source, persist=persist)

            self._original_save_file = original_save_file
            self._wrapped_save_file = save_file
            cast(Any, manager)._save_file = save_file
        except Exception:
            super().on_detach()
            raise

    def on_detach(self) -> None:
        session = self._session
        if session is None:
            super().on_detach()
            return
        manager = session.app_file_manager
        with manager._save_lock:
            if (
                self._original_save_file is not None
                and manager._save_file is self._wrapped_save_file
            ):
                cast(Any, manager)._save_file = self._original_save_file
            self._aliases.clear()
            self._saved_live = ()
            self._original_save_file = None
            self._wrapped_save_file = None
            super().on_detach()

    def _workspace(self) -> StudioWorkspace | None:
        path = self.session.app_file_manager.path
        if path is None:
            return None
        try:
            return discover_studio(Path(path))
        except MarimoStudioError:
            return None

    def _live_refs(self) -> tuple[tuple[CellRef, str], ...]:
        rows = tuple(self.session.document.cells)
        refs = cell_refs(row.code for row in rows)
        return tuple((ref, str(row.id)) for ref, row in zip(refs, rows, strict=True))

    def _refresh_aliases(
        self,
        workspace: StudioWorkspace,
        live: tuple[tuple[CellRef, str], ...],
    ) -> None:
        resolved: dict[str, _TrackedAlias] = {}
        pending: dict[str, CellRef] = {}
        for alias, ref in workspace.cells.items():
            tracked = self._aliases.get(alias)
            if tracked is not None and tracked.ref == ref:
                resolved[alias] = tracked
            else:
                pending[alias] = ref

        matched = safe_cell_ref_matches(pending, live)
        owners_by_id: dict[str, list[str]] = {}
        for alias, tracked in resolved.items():
            owners_by_id.setdefault(tracked.runtime_id, []).append(alias)
        for alias, runtime_id in matched.items():
            owners = owners_by_id.get(runtime_id, [])
            if any(workspace.cells[owner] != pending[alias] for owner in owners):
                continue
            resolved[alias] = _TrackedAlias(pending[alias], runtime_id)
            owners_by_id.setdefault(runtime_id, []).append(alias)
        self._aliases = resolved

    def _binding_update(
        self,
    ) -> tuple[
        StudioWorkspace | None,
        dict[str, CellRef],
        tuple[str, ...],
        bool,
        tuple[tuple[CellRef, str], ...],
    ]:
        workspace = self._workspace()
        if workspace is None:
            self._aliases.clear()
            return None, {}, (), False, ()
        live = self._live_refs()
        self._refresh_aliases(workspace, self._saved_live or live)
        refs_by_id = {runtime_id: ref for ref, runtime_id in live}
        removed = tuple(
            alias
            for alias, tracked in self._aliases.items()
            if alias in workspace.cells and tracked.runtime_id not in refs_by_id
        )
        bindings = {
            alias: current
            for alias, tracked in self._aliases.items()
            if workspace.cells.get(alias) == tracked.ref
            and (current := refs_by_id.get(tracked.runtime_id)) is not None
        }
        remaining = {
            alias: ref for alias, ref in workspace.cells.items() if alias not in removed
        }
        bindings = safe_cell_ref_updates(remaining, bindings)
        changed = bool(removed) or any(
            workspace.cells[alias] != ref for alias, ref in bindings.items()
        )
        return workspace, bindings, removed, changed, live

    def _save_source(self, path: Path, source: str, *, persist: bool) -> str:
        workspace, bindings, removed, changed, live = self._binding_update()
        updated = source
        if changed and workspace is not None and workspace.uses_notebook_config:
            updated = updated_notebook_config_source(
                workspace.notebook,
                source,
                lambda config: set_cell_bindings(
                    config,
                    bindings,
                    remove=removed,
                ),
            )
        if not persist:
            return updated

        manager = self.session.app_file_manager
        if manager.content_matches_last_save(updated):
            saved = cast(Any, manager)._last_saved_content or updated
        else:
            manager.storage.write(path, updated)
            manager._mark_content_as_last_save(updated)
            saved = updated

        if changed and workspace is not None and not workspace.uses_notebook_config:
            _write_cell_bindings(workspace, bindings, remove=removed)
        if changed:
            for alias in removed:
                self._aliases.pop(alias, None)
            self._aliases.update(
                {
                    alias: _TrackedAlias(ref, self._aliases[alias].runtime_id)
                    for alias, ref in bindings.items()
                }
            )
        self._saved_live = live
        return saved


class _SessionListener(SessionEventListener):
    def __init__(self) -> None:
        self._notebooks: set[tuple[str, Path]] = set()

    def add(self, location: ServerLocation) -> None:
        self._notebooks.add((location.file_key, location.notebook))

    def accepts(self, session: Session) -> bool:
        return any(
            session_matches_notebook(session, file_key=file_key, notebook=notebook)
            for file_key, notebook in self._notebooks
        )

    async def on_session_created(self, session: Session) -> None:
        if self.accepts(session):
            attach_cell_alias_sync(session)


_MANAGER_LISTENERS: WeakKeyDictionary[SessionManager, _SessionListener] = (
    WeakKeyDictionary()
)
_MANAGER_LOCK = Lock()


def enable_cell_alias_sync(location: ServerLocation) -> None:
    """Track configured aliases for live edit sessions at this location."""
    if location.mode != "edit":
        return
    manager = cast(SessionManager, location._session_manager)
    with _MANAGER_LOCK:
        listener = _MANAGER_LISTENERS.get(manager)
        if listener is None:
            listener = _SessionListener()
            manager._event_bus.subscribe(listener)
            _MANAGER_LISTENERS[manager] = listener
        listener.add(location)
        sessions = tuple(manager.sessions.values())
    for session in sessions:
        if listener.accepts(session):
            attach_cell_alias_sync(session)


def attach_cell_alias_sync(session: Session) -> None:
    """Attach alias synchronization to one Marimo session."""
    implementation = cast(SessionImpl, session)
    if implementation.extensions.get(_CellAliasSync) is not None:
        return
    extension = _CellAliasSync()
    implementation.extensions.add(extension)
    try:
        extension.on_attach(implementation, implementation._event_bus)
    except Exception:
        implementation.extensions.remove(extension)
        raise
