"""Protect peer control synchronization."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import cast

from marimo._messaging.notification import (
    ModelClose,
    ModelLifecycleNotification,
    ModelOpen,
    ModelUpdate,
    UIElementMessageNotification,
)
from marimo._messaging.serde import deserialize_kernel_message
from marimo._messaging.types import KernelMessage
from marimo._runtime.commands import (
    CommandMessage,
    ModelCommand,
    ModelCustomMessage,
    ModelUpdateMessage,
    UpdateUIElementCommand,
)
from marimo._session.events import SessionEventBus
from marimo._session.extensions.types import ExtensionRegistry
from marimo._session.session import Session
from marimo._session.state.session_view import SessionView
from marimo._types.ids import ConsumerId, UIElementId, WidgetModelId

from marimo_studio._compat.kernel_values.models import OUTPUT_OWNER_PREFIX
from marimo_studio._compat.server.gateway import _LocationHandle
from marimo_studio._compat.server.peer_state import PrivatePeerCommandRelay
from marimo_studio._server.records import ServerHandle, ServerLocation, ServerMode


class _Room:
    def __init__(self) -> None:
        self.messages: list[tuple[KernelMessage, ConsumerId | None]] = []

    def broadcast(
        self,
        notification: KernelMessage,
        *,
        except_consumer: ConsumerId | None,
    ) -> None:
        self.messages.append((notification, except_consumer))


class _Session:
    def __init__(self, notebook: str = "analysis.py") -> None:
        self.extensions = ExtensionRegistry()
        self._event_bus = SessionEventBus()
        self.room = _Room()
        self.session_view = SessionView()
        self.initialization_id = notebook
        self.app_file_manager = type("AppFileManager", (), {"path": notebook})()

    def receive(
        self,
        request: CommandMessage,
        origin: str | None = "editor",
    ) -> None:
        self._event_bus.emit_received_command(
            cast(Session, self),
            request,
            ConsumerId(origin) if origin is not None else None,
        )


class _Manager:
    def __init__(self, session: _Session, *others: _Session) -> None:
        self._event_bus = SessionEventBus()
        self.sessions = {
            str(index): item for index, item in enumerate((session, *others))
        }


def _location(manager: _Manager, *, mode: str = "edit") -> ServerLocation:
    return ServerLocation(
        notebook=Path("analysis.py"),
        file_key="analysis.py",
        base_url="",
        mode=cast(ServerMode, mode),
        routing_query=(),
        handle=ServerHandle(
            _LocationHandle(
                config_manager=object(),
                state=object(),
                session_manager=manager,
            )
        ),
    )


def _enable(location: ServerLocation) -> PrivatePeerCommandRelay:
    relay = PrivatePeerCommandRelay()
    relay.enable(location)
    return relay


def _open_model(session: _Session, model_id: WidgetModelId) -> None:
    session.session_view.add_notification(
        ModelLifecycleNotification(
            model_id=model_id,
            message=ModelOpen(
                state={},
                buffer_paths=[],
                buffers=[],
            ),
        )
    )


def test_authorized_ui_control_commands_relay_once_from_consumers() -> None:
    session = _Session()
    location = _location(_Manager(session))
    relay = _enable(location)
    relay.enable(location)

    session.receive(
        UpdateUIElementCommand(
            object_ids=[UIElementId("slider"), UIElementId("dropdown")],
            values=[7, "Growth"],
        )
    )
    session.receive(
        UpdateUIElementCommand(
            object_ids=[UIElementId("slider")],
            values=[9],
        ),
        origin=None,
    )

    assert len(session.room.messages) == 2
    decoded = [
        deserialize_kernel_message(message)
        for message, origin in session.room.messages
        if origin == ConsumerId("editor")
    ]
    assert decoded == [
        UIElementMessageNotification(
            ui_element=UIElementId("slider"),
            message={"type": "marimo-ui-value-update", "value": 7},
        ),
        UIElementMessageNotification(
            ui_element=UIElementId("dropdown"),
            message={"type": "marimo-ui-value-update", "value": "Growth"},
        ),
    ]


def test_projected_control_updates_stay_with_the_owning_consumer() -> None:
    session = _Session()
    _enable(_location(_Manager(session)))

    session.receive(
        UpdateUIElementCommand(
            object_ids=[
                UIElementId(f"{OUTPUT_OWNER_PREFIX}preview-0"),
                UIElementId("notebook-control"),
            ],
            values=[4, 7],
        ),
        origin="preview-a",
    )

    assert len(session.room.messages) == 1
    message, origin = session.room.messages[0]
    assert origin == ConsumerId("preview-a")
    assert deserialize_kernel_message(message) == UIElementMessageNotification(
        ui_element=UIElementId("notebook-control"),
        message={"type": "marimo-ui-value-update", "value": 7},
    )


def test_peer_sync_attaches_only_to_the_selected_notebook() -> None:
    selected = _Session("analysis.py")
    other = _Session("other.py")

    _enable(_location(_Manager(selected, other)))

    command = UpdateUIElementCommand(
        object_ids=[UIElementId("slider")],
        values=[7],
    )
    selected.receive(command)
    other.receive(command)

    assert len(selected.room.messages) == 1
    assert other.room.messages == []


def test_anywidget_state_relays_only_while_its_model_is_live() -> None:
    session = _Session()
    _enable(_location(_Manager(session)))
    model_id = WidgetModelId("widget")
    _open_model(session, model_id)

    session.receive(
        ModelCommand(
            model_id=model_id,
            message=ModelUpdateMessage(
                state={
                    "count": 2,
                    "pixels": None,
                    "_esm": "untrusted module",
                    "_css": "untrusted style",
                },
                buffer_paths=[["pixels"], ["_css"]],
            ),
            buffers=[b"\x01\x02", b"ignored"],
        ),
        origin="preview-a",
    )
    session.receive(
        ModelCommand(
            model_id=model_id,
            message=ModelCustomMessage(content="clicked"),
            buffers=[],
        ),
        origin="preview-a",
    )

    assert len(session.room.messages) == 1
    message, origin = session.room.messages[0]
    assert origin == ConsumerId("preview-a")
    assert deserialize_kernel_message(message) == ModelLifecycleNotification(
        model_id=model_id,
        message=ModelUpdate(
            state={"count": 2, "pixels": None},
            buffer_paths=[["pixels"]],
            buffers=[b"\x01\x02"],
        ),
    )
    session.session_view.add_notification(
        ModelLifecycleNotification(
            model_id=model_id,
            message=ModelClose(),
        )
    )

    session.receive(
        ModelCommand(
            model_id=model_id,
            message=ModelUpdateMessage(state={"count": 3}, buffer_paths=[]),
            buffers=[],
        ),
        origin="preview-a",
    )

    assert len(session.room.messages) == 1


def test_partial_anywidget_buffers_preserve_valid_state() -> None:
    session = _Session()
    _enable(_location(_Manager(session)))
    model_id = WidgetModelId("widget")
    _open_model(session, model_id)

    session.receive(
        ModelCommand(
            model_id=model_id,
            message=ModelUpdateMessage(
                state={"count": 3, "pixels": None},
                buffer_paths=[["pixels"], ["orphan"]],
            ),
            buffers=[b"\x01\x02"],
        )
    )

    message, _origin = session.room.messages[0]
    assert deserialize_kernel_message(message) == ModelLifecycleNotification(
        model_id=model_id,
        message=ModelUpdate(
            state={"count": 3, "pixels": None},
            buffer_paths=[["pixels"]],
            buffers=[b"\x01\x02"],
        ),
    )


def test_new_edit_sessions_join_sync_while_run_sessions_stay_isolated() -> None:
    initial = _Session()
    manager = _Manager(initial)
    _enable(_location(manager))
    late = _Session()

    asyncio.run(manager._event_bus.emit_session_created(cast(Session, late)))
    late.receive(
        UpdateUIElementCommand(
            object_ids=[UIElementId("slider")],
            values=[4],
        )
    )

    isolated = _Session()
    _enable(_location(_Manager(isolated), mode="run"))
    isolated.receive(
        UpdateUIElementCommand(
            object_ids=[UIElementId("slider")],
            values=[9],
        )
    )

    assert len(late.room.messages) == 1
    assert isolated.room.messages == []
