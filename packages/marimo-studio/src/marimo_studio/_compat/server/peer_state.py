"""Relay authorized control commands between consumers in one Marimo session."""

from __future__ import annotations

from pathlib import Path
from threading import RLock
from typing import cast
from weakref import WeakKeyDictionary, ref

from marimo._messaging.notification import (
    ModelLifecycleNotification,
    ModelUpdate,
    NotificationMessage,
    UIElementMessageNotification,
)
from marimo._messaging.serde import serialize_kernel_message
from marimo._runtime.commands import (
    CommandMessage,
    ModelCommand,
    ModelUpdateMessage,
    UpdateUIElementCommand,
)
from marimo._server.session_manager import SessionManager
from marimo._session.events import SessionEventListener
from marimo._session.extensions.types import EventAwareExtension
from marimo._session.session import Session, SessionImpl
from marimo._types.ids import ConsumerId

from marimo_studio._capabilities import ServerLocation
from marimo_studio._compat.kernel_values.models import OUTPUT_OWNER_PREFIX
from marimo_studio._compat.patch import CallbackCloseHandle
from marimo_studio._compat.server.gateway import location_handle
from marimo_studio._compat.server.session_state import session_matches_notebook


class _PeerCommandRelayExtension(EventAwareExtension):
    """Relay authorized control commands before kernel application."""

    def on_received_command(
        self,
        session: Session,
        request: CommandMessage,
        from_consumer_id: ConsumerId | None,
    ) -> None:
        if from_consumer_id is None:
            return
        if (
            isinstance(request, ModelCommand)
            and isinstance(request.message, ModelUpdateMessage)
            and request.model_id not in session.session_view.model_states
        ):
            return
        for notification in _peer_notifications(request):
            session.room.broadcast(
                serialize_kernel_message(notification),
                except_consumer=from_consumer_id,
            )


def _attach(session: Session) -> None:
    implementation = cast(SessionImpl, session)
    if implementation.extensions.get(_PeerCommandRelayExtension) is not None:
        return
    extension = _PeerCommandRelayExtension()
    implementation.extensions.add(extension)
    try:
        extension.on_attach(implementation, implementation._event_bus)
    except Exception:
        implementation.extensions.remove(extension)
        raise


def _detach(session: Session) -> None:
    implementation = cast(SessionImpl, session)
    extension = implementation.extensions.get(_PeerCommandRelayExtension)
    if extension is None:
        return
    extension.on_detach()
    implementation.extensions.remove(extension)


class _ManagerRelay(SessionEventListener):
    def __init__(self, manager: SessionManager) -> None:
        self._manager = ref(manager)
        self._owners: dict[object, set[tuple[str, Path]]] = {}
        self._lock = RLock()
        manager._event_bus.subscribe(self)

    def enable(self, owner: object, location: ServerLocation) -> None:
        with self._lock:
            self._owners.setdefault(owner, set()).add(
                (location.file_key, location.notebook)
            )
            sessions = self._sessions()
        for session in sessions:
            if self.accepts(session):
                _attach(session)

    def remove(self, owner: object) -> bool:
        with self._lock:
            self._owners.pop(owner, None)
            sessions = self._sessions()
            empty = not self._owners
        for session in sessions:
            if empty or not self.accepts(session):
                _detach(session)
        if empty:
            manager = self._manager()
            if manager is not None:
                manager._event_bus.unsubscribe(self)
        return empty

    def accepts(self, session: Session) -> bool:
        with self._lock:
            notebooks = tuple(
                notebook
                for registered in self._owners.values()
                for notebook in registered
            )
        return any(
            session_matches_notebook(session, file_key=file_key, notebook=notebook)
            for file_key, notebook in notebooks
        )

    async def on_session_created(self, session: Session) -> None:
        if self.accepts(session):
            _attach(session)

    def _sessions(self) -> tuple[Session, ...]:
        manager = self._manager()
        return tuple(manager.sessions.values()) if manager is not None else ()


_MANAGERS: WeakKeyDictionary[SessionManager, _ManagerRelay] = WeakKeyDictionary()
_MANAGERS_LOCK = RLock()


class PrivatePeerCommandRelay:
    """Own manager subscriptions and peer relays for one application."""

    def __init__(self) -> None:
        self._owner = object()
        self._managers: WeakKeyDictionary[SessionManager, None] = WeakKeyDictionary()

    def open(self) -> CallbackCloseHandle:
        return CallbackCloseHandle(self.close)

    def enable(self, location: ServerLocation) -> None:
        if location.mode != "edit":
            return
        manager = cast(SessionManager, location_handle(location).session_manager)
        with _MANAGERS_LOCK:
            relay = _MANAGERS.get(manager)
            if relay is None:
                relay = _ManagerRelay(manager)
                _MANAGERS[manager] = relay
            self._managers[manager] = None
        relay.enable(self._owner, location)

    def close(self) -> None:
        with _MANAGERS_LOCK:
            for manager in tuple(self._managers):
                relay = _MANAGERS.get(manager)
                if relay is not None and relay.remove(self._owner):
                    _MANAGERS.pop(manager, None)
            self._managers.clear()


def _peer_notifications(request: CommandMessage) -> tuple[NotificationMessage, ...]:
    if isinstance(request, UpdateUIElementCommand):
        return tuple(
            UIElementMessageNotification(
                ui_element=object_id,
                message={
                    "type": "marimo-ui-value-update",
                    "value": value,
                },
            )
            for object_id, value in request.ids_and_values
            if not str(object_id).startswith(OUTPUT_OWNER_PREFIX)
        )
    if not isinstance(request, ModelCommand) or not isinstance(
        request.message, ModelUpdateMessage
    ):
        return ()

    state = {
        key: value
        for key, value in request.message.state.items()
        if key not in {"_esm", "_css"}
    }
    buffer_pairs = [
        (path, buffer)
        for path, buffer in zip(
            request.message.buffer_paths,
            request.buffers,
            strict=False,
        )
        if not path or path[0] not in {"_esm", "_css"}
    ]
    return (
        ModelLifecycleNotification(
            model_id=request.model_id,
            message=ModelUpdate(
                state=state,
                buffer_paths=[path for path, _buffer in buffer_pairs],
                buffers=[buffer for _path, buffer in buffer_pairs],
            ),
        ),
    )


__all__ = ["PrivatePeerCommandRelay"]
