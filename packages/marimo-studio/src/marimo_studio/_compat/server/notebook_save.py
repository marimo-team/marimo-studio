"""Install a source transform at Marimo's notebook persistence boundary."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from threading import RLock
from typing import Any, cast
from weakref import WeakKeyDictionary, ref

from marimo._schemas.serialization import NotebookSerializationV1
from marimo._server.session_manager import SessionManager
from marimo._session.events import SessionEventBus, SessionEventListener
from marimo._session.extensions.types import EventAwareExtension
from marimo._session.notebook.file_manager import AppFileManager
from marimo._session.session import Session, SessionImpl

from marimo_studio._compat.patch import CallbackCloseHandle
from marimo_studio._compat.server.gateway import location_handle
from marimo_studio._compat.server.session_state import session_matches_notebook
from marimo_studio._server.ports import (
    NotebookSourcePolicy,
    SourceTransformSession,
)
from marimo_studio._server.records import SaveCell, ServerLocation
from marimo_studio.errors._internal import CompatibilityError

_SaveFile = Callable[..., str]


def _cells(session: Session) -> tuple[SaveCell, ...]:
    return tuple(
        SaveCell(code=row.code, runtime_id=str(row.id))
        for row in session.document.cells
    )


class _SourceTransformExtension(EventAwareExtension):
    def __init__(self, transform: SourceTransformSession) -> None:
        super().__init__()
        self._transform = transform
        self._original_save_file: _SaveFile | None = None
        self._wrapped_save_file: _SaveFile | None = None

    def on_attach(self, session: Session, event_bus: SessionEventBus) -> None:
        super().on_attach(session, event_bus)
        manager = session.app_file_manager
        original_save_file = manager._save_file
        native_save_file = getattr(original_save_file, "__func__", original_save_file)
        if native_save_file is not AppFileManager._save_file:
            super().on_detach()
            raise CompatibilityError(
                "Another owner replaced Marimo's notebook persistence method."
            )
        try:

            def save_file(
                path: Path,
                *,
                notebook: NotebookSerializationV1,
                persist: bool,
                previous_path: Path | None = None,
            ) -> str:
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
                    result = self._transform.transform(
                        path,
                        source,
                        persist=persist,
                        cells=_cells(self.session),
                    )
                    if not persist:
                        return result.source
                    if manager.content_matches_last_save(result.source):
                        saved = cast(Any, manager)._last_saved_content or result.source
                    else:
                        manager.storage.write(path, result.source)
                        manager._mark_content_as_last_save(result.source)
                        saved = result.source
                    result.commit()
                    return saved

            self._original_save_file = original_save_file
            self._wrapped_save_file = save_file
            cast(Any, manager)._save_file = save_file
        except Exception:
            super().on_detach()
            raise

    def on_detach(self) -> None:
        session = self._session
        if session is None:
            self._transform.close()
            super().on_detach()
            return
        manager = session.app_file_manager
        with manager._save_lock:
            if (
                self._wrapped_save_file is not None
                and manager._save_file is not self._wrapped_save_file
            ):
                raise CompatibilityError(
                    "Another owner replaced Marimo's notebook persistence method "
                    "before Studio could restore it."
                )
            if self._wrapped_save_file is not None:
                cast(Any, manager)._save_file = self._original_save_file
            self._original_save_file = None
            self._wrapped_save_file = None
            self._transform.close()
            super().on_detach()


def _attach(session: Session, policy: NotebookSourcePolicy) -> None:
    implementation = cast(SessionImpl, session)
    if implementation.extensions.get(_SourceTransformExtension) is not None:
        return
    path = session.app_file_manager.path
    if path is None:
        return
    transform = policy.open(Path(path), _cells(session))
    if transform is None:
        return
    extension = _SourceTransformExtension(transform)
    implementation.extensions.add(extension)
    try:
        extension.on_attach(implementation, implementation._event_bus)
    except Exception:
        implementation.extensions.remove(extension)
        transform.close()
        raise


def _detach(session: Session) -> None:
    implementation = cast(SessionImpl, session)
    extension = implementation.extensions.get(_SourceTransformExtension)
    if extension is None:
        return
    extension.on_detach()
    implementation.extensions.remove(extension)


class _ManagerTransforms(SessionEventListener):
    def __init__(self, manager: SessionManager) -> None:
        self._manager = ref(manager)
        self._owners: dict[
            object,
            dict[tuple[str, Path], NotebookSourcePolicy],
        ] = {}
        self._lock = RLock()
        manager._event_bus.subscribe(self)

    def enable(
        self,
        owner: object,
        location: ServerLocation,
        policy: NotebookSourcePolicy,
    ) -> None:
        key = (location.file_key, location.notebook)
        with self._lock:
            policies = {
                type(registered[key])
                for registered in self._owners.values()
                if key in registered
            }
            if policies and type(policy) not in policies:
                raise CompatibilityError(
                    "Two source-transform policies claimed the same Marimo notebook."
                )
            self._owners.setdefault(owner, {})[key] = policy
            sessions = self._sessions()
        for session in sessions:
            selected = self._policy(session)
            if selected is not None:
                _attach(session, selected)

    def remove(self, owner: object) -> bool:
        with self._lock:
            self._owners.pop(owner, None)
            sessions = self._sessions()
            empty = not self._owners
        for session in sessions:
            if empty or self._policy(session) is None:
                _detach(session)
        if empty:
            manager = self._manager()
            if manager is not None:
                manager._event_bus.unsubscribe(self)
        return empty

    async def on_session_created(self, session: Session) -> None:
        policy = self._policy(session)
        if policy is not None:
            _attach(session, policy)

    def _policy(self, session: Session) -> NotebookSourcePolicy | None:
        with self._lock:
            registrations = tuple(
                (key, policy)
                for owned in self._owners.values()
                for key, policy in owned.items()
            )
        for (file_key, _notebook), policy in registrations:
            if session_matches_notebook(
                session,
                file_key=file_key,
            ):
                return policy
        return None

    def _sessions(self) -> tuple[Session, ...]:
        manager = self._manager()
        return tuple(manager.sessions.values()) if manager is not None else ()


_MANAGERS: WeakKeyDictionary[SessionManager, _ManagerTransforms] = WeakKeyDictionary()
_MANAGERS_LOCK = RLock()


class PrivateNotebookSaveTransform:
    """Own save-transform registrations for one Studio application."""

    def __init__(self, policy: NotebookSourcePolicy) -> None:
        self._policy = policy
        self._owner = object()
        self._managers: WeakKeyDictionary[SessionManager, None] = WeakKeyDictionary()

    def open(self) -> CallbackCloseHandle:
        return CallbackCloseHandle(self.close)

    def enable(self, location: ServerLocation) -> None:
        if location.mode != "edit":
            return
        manager = cast(SessionManager, location_handle(location).session_manager)
        with _MANAGERS_LOCK:
            transforms = _MANAGERS.get(manager)
            if transforms is None:
                transforms = _ManagerTransforms(manager)
                _MANAGERS[manager] = transforms
            self._managers[manager] = None
        transforms.enable(self._owner, location, self._policy)

    def close(self) -> None:
        with _MANAGERS_LOCK:
            for manager in tuple(self._managers):
                transforms = _MANAGERS.get(manager)
                if transforms is not None and transforms.remove(self._owner):
                    _MANAGERS.pop(manager, None)
            self._managers.clear()
