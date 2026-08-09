"""Synchronize control state between consumers in one Marimo session."""

from __future__ import annotations

from pathlib import Path
from threading import Lock
from typing import cast
from weakref import WeakKeyDictionary

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

from marimo_studio._compat.server.models import ServerLocation
from marimo_studio._compat.server.sessions import session_matches_notebook

_MANAGER_LISTENERS: WeakKeyDictionary[SessionManager, _SessionListener] = (
    WeakKeyDictionary()
)
_MANAGER_LOCK = Lock()


class _PeerControlSync(EventAwareExtension):
    """Relay received control writes to the other consumers in a room."""

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
            # Marimo drops updates to closed comms. Do the same before a peer
            # waits for a model that can no longer arrive.
            return
        for notification in _peer_notifications(request):
            # Marimo records the original command in SessionView. Relay the
            # notification directly so replay state stays sourced from it once.
            session.room.broadcast(
                serialize_kernel_message(notification),
                except_consumer=from_consumer_id,
            )


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
            _attach_to_session(session)


def enable_peer_control_sync(location: ServerLocation) -> None:
    """Enable peer control updates for a configured edit-mode notebook."""
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
            _attach_to_session(session)


def _attach_to_session(session: Session) -> None:
    implementation = cast(SessionImpl, session)
    if implementation.extensions.get(_PeerControlSync) is not None:
        return
    extension = _PeerControlSync()
    implementation.extensions.add(extension)
    extension.on_attach(implementation, implementation._event_bus)


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
