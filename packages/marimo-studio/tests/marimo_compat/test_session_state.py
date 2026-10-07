"""Protect Marimo session ownership and detached live-cell capture."""

import asyncio
import threading
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Literal, cast

import pytest
from marimo._messaging.notification import (
    CellNotification,
    CompletedRunNotification,
    QueryParamsSetNotification,
    ReloadNotification,
)
from marimo._messaging.serde import deserialize_kernel_message, serialize_kernel_message
from marimo._runtime.commands import (
    CreateNotebookCommand,
    ExecuteCellsCommand,
    ExecuteStaleCellsCommand,
    InstallPackagesCommand,
    ModelCommand,
    ModelCustomMessage,
    ModelUpdateMessage,
    UpdateCellConfigCommand,
    UpdateUIElementCommand,
)
from starlette.datastructures import QueryParams

import marimo_studio._compat.server.session_state as session_state_module
from marimo_studio._compat.execution_markers import (
    is_execution_command,
    make_marker,
    parse_marker,
)
from marimo_studio._compat.server.session_state import (
    PrivateSessionState,
    session_creation_query_matches,
    session_matches_notebook,
)
from marimo_studio._server.ports import EditorSessionIdentity
from marimo_studio.errors._internal import RuntimeKernelExitError, RuntimeSyncError


def _live_capture() -> session_state_module._LiveCellCapture:
    return session_state_module._LiveCellCapture(
        session_owner=7,
        document_generation=1,
        cells=(("first", "value = 1", "value"), ("second", "value", "_")),
        executed_cells=(("first", "value = 1"), ("second", "value")),
        graph_parents=(("first", ()), ("second", ("first",))),
    )


def _marker(
    name: str,
    phase: Literal["start", "done", "failed"],
    token: str,
) -> bytes:
    return serialize_kernel_message(
        CompletedRunNotification(
            run_id=make_marker(phase, name, token),
        )
    )


def test_session_owner_uses_the_initialization_identity_until_saved() -> None:
    session: Any = SimpleNamespace(
        initialization_id="notebook.py",
        app_file_manager=SimpleNamespace(path=None),
    )

    assert session_matches_notebook(
        session,
        file_key="notebook.py",
        notebook=Path("/workspace/notebook.py"),
    )
    session.app_file_manager.path = "/workspace/renamed.py"
    assert not session_matches_notebook(
        session,
        file_key="notebook.py",
        notebook=Path("/workspace/notebook.py"),
    )


def test_session_owner_accepts_the_current_notebook_path(tmp_path: Path) -> None:
    notebook = tmp_path / "notebook.py"
    session: Any = SimpleNamespace(
        initialization_id=str(tmp_path / "nested" / "notebook.py"),
        app_file_manager=SimpleNamespace(path=str(notebook)),
    )

    assert session_matches_notebook(
        session,
        file_key="notebook.py",
        notebook=notebook,
    )


def test_session_owner_rejects_another_notebook_path(tmp_path: Path) -> None:
    notebook = tmp_path / "notebook.py"
    session: Any = SimpleNamespace(
        initialization_id="other.py",
        app_file_manager=SimpleNamespace(path=str(tmp_path / "other.py")),
    )

    assert not session_matches_notebook(
        session,
        file_key="notebook.py",
        notebook=notebook,
    )


def test_app_host_session_exposes_its_creation_query() -> None:
    session: Any = SimpleNamespace(
        _kernel_manager=SimpleNamespace(
            _app_metadata=SimpleNamespace(
                query_params={"region": "emea", "session_id": "s_private"}
            )
        )
    )

    assert session_creation_query_matches(
        session,
        [("session_id", "s_other1"), ("region", "emea")],
    )
    assert not session_creation_query_matches(session, [("region", "apac")])


@pytest.mark.parametrize("file_key", [None, "__new__s_123456", "saved.py"])
def test_first_save_handoff_follows_the_saving_consumer_connection(
    monkeypatch: pytest.MonkeyPatch,
    file_key: str | None,
) -> None:
    notifications: list[object] = []
    peer_notifications: list[object] = []

    def notify(operation: object, from_consumer_id: object) -> None:
        assert from_consumer_id is None
        notifications.append(operation)
        peer_notifications.append(operation)

    consumer = SimpleNamespace(
        params=SimpleNamespace(file_key=file_key),
        notify=lambda message: notifications.append(
            deserialize_kernel_message(message)
        ),
    )
    consumers = {
        "s_123456": consumer,
        "s_peer01": SimpleNamespace(notify=peer_notifications.append),
    }

    session: Any = SimpleNamespace(
        initialization_id="__new__" if file_key is None else "__new__s_123456",
        notify=notify,
        room=SimpleNamespace(get_consumer=consumers.get),
    )
    monkeypatch.setattr(
        session_state_module,
        "current_session",
        lambda _context, _session_id: session,
    )
    reloaded = PrivateSessionState().request_studio_reload(
        cast(Any, object()),
        "s_123456",
        host_handoff="a" * 64,
    )
    if file_key == "saved.py":
        assert not reloaded
        assert notifications == []
        assert peer_notifications == []
        return
    assert reloaded

    first, second, third, fourth = notifications
    assert isinstance(first, QueryParamsSetNotification)
    assert (first.key, first.value) == ("session_id", "s_123456")
    assert isinstance(second, QueryParamsSetNotification)
    assert (second.key, second.value) == ("marimo_studio_handoff", "a" * 64)
    assert isinstance(third, QueryParamsSetNotification)
    assert (third.key, third.value) == ("marimo_studio_resume", "1")
    assert isinstance(fourth, ReloadNotification)
    assert peer_notifications == []


def test_editor_identity_follows_the_native_consumer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    consumers = {
        key: SimpleNamespace(
            request=SimpleNamespace(
                query_params=QueryParams(
                    {
                        "marimo_studio_client": client,
                        "marimo_studio_editor": capability,
                    }
                )
            )
        )
        for key, client, capability in (
            ("s_first1", "first-client", "first-capability"),
            ("s_second", "second-client", "second-capability"),
        )
    }
    session: Any = SimpleNamespace(
        room=SimpleNamespace(get_consumer=consumers.get),
    )
    monkeypatch.setattr(
        session_state_module,
        "current_session",
        lambda _context, _session_id: session,
    )

    state = PrivateSessionState()
    context = cast(Any, object())
    assert state.editor_identity(context, "s_first1") == EditorSessionIdentity(
        "first-client", "first-capability"
    )
    assert state.editor_identity(context, "s_second") == EditorSessionIdentity(
        "second-client", "second-capability"
    )
    consumers["s_second"] = SimpleNamespace(
        request=SimpleNamespace(query_params=QueryParams())
    )
    assert state.editor_identity(context, "s_second") is None
    assert state.editor_identity(context, "s_first1") == EditorSessionIdentity(
        "first-client", "first-capability"
    )


def test_live_cell_capture_materializes_off_its_event_loop_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner_threads: list[int] = []
    worker_threads: list[int] = []
    capture = _live_capture()
    native_materialize = session_state_module._materialize_live_cells

    def capture_cells(*_args: object, **_kwargs: object):
        owner_threads.append(threading.get_ident())
        return capture

    def materialize(value: session_state_module._LiveCellCapture):
        worker_threads.append(threading.get_ident())
        return native_materialize(value)

    monkeypatch.setattr(session_state_module, "_capture_live_cells", capture_cells)
    monkeypatch.setattr(session_state_module, "_materialize_live_cells", materialize)

    async def exercise():
        owner = threading.get_ident()
        snapshot = await PrivateSessionState().live_cells(
            cast(Any, object()),
            "s_123456",
            include_dependency_closures=True,
        )
        return owner, snapshot

    owner, snapshot = asyncio.run(exercise())

    assert owner_threads == [owner, owner]
    assert len(worker_threads) == 1 and worker_threads[0] != owner
    assert snapshot is not None
    assert snapshot.owner == "session:7"
    assert len(snapshot.generation) == 64
    assert snapshot.dependency_closures == {
        "first": ("first",),
        "second": ("first", "second"),
    }


def test_live_cell_materialization_preserves_duplicate_cell_occurrences() -> None:
    capture = session_state_module._LiveCellCapture(
        session_owner=7,
        document_generation=1,
        cells=(
            ("first", "value = 1", "first"),
            ("second", "value = 1", "second"),
        ),
        executed_cells=(("second", "value = 1"),),
        graph_parents=None,
    )

    snapshot = session_state_module._materialize_live_cells(capture)
    refs = tuple(snapshot.ids)

    assert snapshot.current_refs == {"second": refs[1]}
    assert refs[1].occurrence == 1


@pytest.mark.parametrize(
    ("status", "expected"),
    [("queued", True), ("running", True), ("idle", False)],
)
def test_live_cell_capture_records_active_execution(
    monkeypatch: pytest.MonkeyPatch,
    status: str,
    expected: bool,
) -> None:
    session: Any = SimpleNamespace(
        document=SimpleNamespace(
            cells=(SimpleNamespace(id="first", code="value = 1", name="value"),),
            version=1,
        ),
        session_view=SimpleNamespace(
            last_executed_code={"first": "value = 1"},
            cell_notifications={"first": SimpleNamespace(status=status)},
        ),
    )
    monkeypatch.setattr(session_state_module, "current_session", lambda *_args: session)
    tracker = session_state_module._ExecutionTracker(session, attached=False)
    monkeypatch.setattr(
        session_state_module,
        "_ensure_execution_tracker",
        lambda _session: tracker,
    )
    if status != "idle":
        tracker.on_notification_sent(
            session,
            serialize_kernel_message(
                CellNotification(cast(Any, "first"), status=cast(Any, status))
            ),
        )

    capture = session_state_module._capture_live_cells(
        cast(Any, SimpleNamespace(mode="edit")),
        "s_123456",
        include_dependency_closures=False,
        session_owner=lambda _session: 7,
    )

    assert capture is not None
    assert capture.execution_pending is expected


def test_live_cell_capture_reports_a_stopped_kernel_before_pending_work(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Session:
        def kernel_exit_info(self) -> object:
            return SimpleNamespace(message="The kernel stopped unexpectedly.")

    session: Any = Session()
    tracker = session_state_module._ExecutionTracker(session, attached=True)
    tracker._marker_runs.add("active")
    tracker._marker_runs.add("stuck")
    monkeypatch.setattr(session_state_module, "current_session", lambda *_args: session)
    monkeypatch.setattr(
        session_state_module,
        "_ensure_execution_tracker",
        lambda _session: tracker,
    )

    with pytest.raises(RuntimeKernelExitError, match="stopped unexpectedly"):
        asyncio.run(
            PrivateSessionState().live_cells(
                cast(Any, object()),
                "s_123456",
                include_dependency_closures=False,
            )
        )


def test_execution_tracker_covers_command_admission_before_cell_notification() -> None:
    session: Any = SimpleNamespace(
        document=SimpleNamespace(cells=()),
        session_view=SimpleNamespace(cell_notifications={}),
    )
    tracker = session_state_module._ExecutionTracker(session, attached=False)
    tracker.on_received_command(
        session,
        ExecuteCellsCommand(cell_ids=cast(Any, ["first"]), codes=["value = 2"]),
        None,
    )

    assert tracker.pending(session)
    generation = tracker.generation
    tracker.on_notification_sent(
        session,
        _marker("ExecuteCellsCommand", "start", "execute-1"),
    )
    tracker.on_notification_sent(
        session,
        serialize_kernel_message(CellNotification(cast(Any, "first"), status="idle")),
    )

    assert tracker.pending(session)
    tracker.on_notification_sent(
        session,
        _marker("ExecuteCellsCommand", "done", "execute-1"),
    )
    assert not tracker.pending(session)
    tracker.on_notification_sent(
        session,
        _marker("UpdateCellConfigCommand", "start", "config-1"),
    )
    assert tracker.pending(session)
    tracker.on_notification_sent(
        session,
        _marker("UpdateCellConfigCommand", "done", "config-1"),
    )
    assert not tracker.pending(session)
    assert tracker.generation > generation


def test_execution_tracker_attaches_before_native_event_bus_delivery() -> None:
    from marimo._session.events import SessionEventBus

    class Session:
        def __init__(self) -> None:
            self._event_bus = SessionEventBus()

    session: Any = Session()
    tracker = session_state_module._ensure_execution_tracker(session)

    assert session._event_bus._listeners[0] is tracker
    session._event_bus.emit_received_command(
        session,
        ExecuteStaleCellsCommand(),
        None,
    )
    assert tracker.pending(session)
    session._event_bus.emit_notification_sent(
        session,
        _marker("ExecuteStaleCellsCommand", "start", "bus-1"),
    )
    session._event_bus.emit_notification_sent(
        session,
        _marker("ExecuteStaleCellsCommand", "done", "bus-1"),
    )
    assert not tracker.pending(session)


def test_kernel_markers_are_consumed_before_browser_broadcast() -> None:
    from marimo._session.events import SessionEventBus

    class Session:
        def __init__(self) -> None:
            self._event_bus = SessionEventBus()
            self.broadcasted: list[object] = []

        def notify(self, operation: object, from_consumer_id: object | None) -> None:
            del from_consumer_id
            self.broadcasted.append(operation)

    session: Any = Session()
    tracker = session_state_module._ensure_execution_tracker(session)
    session._event_bus.emit_received_command(
        session,
        UpdateUIElementCommand(object_ids=cast(Any, ["slider"]), values=[2]),
        None,
    )
    session.notify(_marker("UpdateUIElementCommand", "start", "hidden-1"), None)
    assert tracker.pending(session)
    assert session.broadcasted == []
    session.notify(_marker("UpdateUIElementCommand", "done", "hidden-1"), None)
    assert not tracker.pending(session)
    assert session.broadcasted == []


def test_execution_tracker_retires_a_collapsed_reactive_batch() -> None:
    session: Any = SimpleNamespace(
        document=SimpleNamespace(cells=()),
        session_view=SimpleNamespace(cell_notifications={}),
    )
    tracker = session_state_module._ExecutionTracker(session, attached=False)
    for value in (1, 2):
        tracker.on_received_command(
            session,
            UpdateUIElementCommand(
                object_ids=cast(Any, ["slider"]),
                values=[value],
            ),
            None,
        )
    assert tracker.pending(session)
    tracker.on_notification_sent(
        session,
        _marker("UpdateUIElementCommand", "start", "merged-1"),
    )
    tracker.on_notification_sent(
        session,
        _marker("UpdateUIElementCommand", "done", "merged-1"),
    )
    assert not tracker.pending(session)


def test_execution_tracker_coalesces_unmarked_batchable_ui_commands() -> None:
    session: Any = SimpleNamespace(
        document=SimpleNamespace(cells=()),
        session_view=SimpleNamespace(cell_notifications={}),
    )
    tracker = session_state_module._ExecutionTracker(session, attached=False)
    tracker.on_received_command(
        session,
        UpdateUIElementCommand(object_ids=cast(Any, ["slider"]), values=[2]),
        None,
    )

    tracker.on_received_command(
        session,
        UpdateUIElementCommand(object_ids=cast(Any, ["slider"]), values=[3]),
        None,
    )
    assert tracker.pending(session)
    tracker.on_notification_sent(
        session,
        serialize_kernel_message(CompletedRunNotification()),
    )
    assert not tracker.pending(session)


def test_live_cell_capture_waits_for_the_native_kernel_barrier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Session:
        room = object()

        def put_control_request(self, *_args: object, **_kwargs: object) -> None:
            return

    session: Any = Session()
    tracker = session_state_module._ExecutionTracker(session, attached=True)
    order: list[str] = []
    capture = _live_capture()
    monkeypatch.setattr(session_state_module, "current_session", lambda *_args: session)
    monkeypatch.setattr(
        session_state_module,
        "_ensure_execution_tracker",
        lambda _session: tracker,
    )

    async def barrier(*_args: object, **_kwargs: object) -> object:
        order.append("barrier")
        tracker._marker_runs.clear()
        return object()

    monkeypatch.setattr(session_state_module, "wait_for_session_barrier", barrier)
    monkeypatch.setattr(
        session_state_module,
        "_capture_live_cells",
        lambda *_args, **_kwargs: order.append("capture") or capture,
    )

    result = asyncio.run(
        PrivateSessionState().live_cells(
            cast(Any, object()),
            "s_123456",
            include_dependency_closures=False,
        )
    )

    assert isinstance(result, session_state_module.LiveCellSnapshot)
    assert order == ["barrier", "capture", "capture"]


def test_live_cell_capture_resolves_a_file_session_before_the_kernel_barrier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Session:
        room = object()

        def put_control_request(self, *_args: object, **_kwargs: object) -> None:
            return

    session: Any = Session()
    manager = SimpleNamespace(
        sessions={"s_123456": session},
        get_session_by_file_key=lambda _file_key: session,
    )
    context = SimpleNamespace(mode="edit", file_key="notebook.py")
    tracker = session_state_module._ExecutionTracker(session, attached=True)
    order: list[object] = []
    monkeypatch.setattr(
        session_state_module,
        "context_handle",
        lambda _context: SimpleNamespace(session_manager=manager),
    )
    monkeypatch.setattr(
        session_state_module,
        "_ensure_execution_tracker",
        lambda _session: tracker,
    )

    async def barrier(*_args: object, **kwargs: object) -> None:
        order.append(kwargs["consumer_id"])

    monkeypatch.setattr(session_state_module, "wait_for_session_barrier", barrier)
    monkeypatch.setattr(
        session_state_module,
        "_capture_live_cells",
        lambda *_args, **_kwargs: order.append("capture") or _live_capture(),
    )

    result = asyncio.run(
        PrivateSessionState().live_cells(
            cast(Any, context),
            None,
            include_dependency_closures=False,
        )
    )

    assert isinstance(result, session_state_module.LiveCellSnapshot)
    assert order == ["s_123456", "capture", "capture"]


def test_execution_tracker_finishes_noop_commands_on_completion_notification() -> None:
    session: Any = SimpleNamespace(
        document=SimpleNamespace(cells=()),
        session_view=SimpleNamespace(cell_notifications={}),
    )
    tracker = session_state_module._ExecutionTracker(session, attached=False)

    tracker.on_received_command(session, ExecuteStaleCellsCommand(), None)
    assert tracker.pending(session)

    tracker.on_notification_sent(
        session,
        _marker("ExecuteStaleCellsCommand", "start", "stale-1"),
    )
    assert tracker.pending(session)
    tracker.on_notification_sent(
        session,
        _marker("ExecuteStaleCellsCommand", "done", "stale-1"),
    )

    assert not tracker.pending(session)


def test_execution_tracker_keeps_overlapping_cell_runs_pending() -> None:
    session: Any = SimpleNamespace(
        document=SimpleNamespace(cells=()),
        session_view=SimpleNamespace(cell_notifications={}),
    )
    tracker = session_state_module._ExecutionTracker(session, attached=False)
    tracker.on_received_command(
        session,
        ExecuteCellsCommand(cell_ids=cast(Any, ["first"]), codes=["value = 1"]),
        None,
    )
    tracker.on_received_command(
        session,
        ExecuteCellsCommand(cell_ids=cast(Any, ["first"]), codes=["value = 2"]),
        None,
    )

    tracker.on_notification_sent(
        session,
        _marker("ExecuteCellsCommand", "start", "execute-1"),
    )
    tracker.on_notification_sent(
        session,
        _marker("ExecuteCellsCommand", "start", "execute-2"),
    )
    assert tracker.pending(session)
    tracker.on_notification_sent(
        session,
        _marker("ExecuteCellsCommand", "done", "execute-1"),
    )
    assert tracker.pending(session)
    tracker.on_notification_sent(
        session,
        _marker("ExecuteCellsCommand", "done", "execute-2"),
    )
    assert not tracker.pending(session)


def test_execution_tracker_uses_cell_notifications_for_ui_updates() -> None:
    session: Any = SimpleNamespace(
        document=SimpleNamespace(cells=()),
        session_view=SimpleNamespace(cell_notifications={}),
    )
    tracker = session_state_module._ExecutionTracker(session, attached=False)
    tracker.on_received_command(
        session,
        UpdateUIElementCommand(object_ids=cast(Any, ["slider"]), values=[2]),
        None,
    )
    assert tracker.pending(session)
    generation = tracker.generation
    tracker.on_notification_sent(
        session,
        _marker("UpdateUIElementCommand", "start", "ui-1"),
    )
    tracker.on_notification_sent(
        session,
        serialize_kernel_message(CellNotification(cast(Any, "first"), status="queued")),
    )
    assert tracker.pending(session)
    tracker.on_notification_sent(
        session,
        serialize_kernel_message(CellNotification(cast(Any, "first"), status="idle")),
    )
    tracker.on_notification_sent(
        session,
        _marker("UpdateUIElementCommand", "done", "ui-1"),
    )
    assert not tracker.pending(session)
    assert tracker.generation > generation


def test_execution_tracker_keeps_non_auto_create_pending_until_completion() -> None:
    session: Any = SimpleNamespace(
        document=SimpleNamespace(cells=()),
        session_view=SimpleNamespace(cell_notifications={}),
    )
    tracker = session_state_module._ExecutionTracker(session, attached=False)
    tracker.on_received_command(
        session,
        CreateNotebookCommand(
            execution_requests=(),
            cell_ids=(),
            set_ui_element_value_request=UpdateUIElementCommand(
                object_ids=[], values=[]
            ),
            auto_run=False,
        ),
        None,
    )
    assert tracker.pending(session)
    tracker.on_notification_sent(
        session,
        _marker("CreateNotebookCommand", "start", "create-1"),
    )
    tracker.on_notification_sent(
        session,
        _marker("CreateNotebookCommand", "done", "create-1"),
    )
    assert not tracker.pending(session)


def test_execution_tracker_ignores_a_late_create_terminal_after_retry_reset() -> None:
    session: Any = SimpleNamespace(
        document=SimpleNamespace(cells=()),
        session_view=SimpleNamespace(cell_notifications={}),
    )
    tracker = session_state_module._ExecutionTracker(session, attached=False)
    tracker.on_received_command(
        session,
        CreateNotebookCommand(
            execution_requests=(),
            cell_ids=(),
            set_ui_element_value_request=UpdateUIElementCommand(
                object_ids=[], values=[]
            ),
            auto_run=False,
        ),
        None,
    )
    tracker.on_notification_sent(
        session,
        _marker("CreateNotebookCommand", "start", "old-create"),
    )

    tracker.reset_startup()
    tracker.on_notification_sent(
        session,
        _marker("CreateNotebookCommand", "done", "old-create"),
    )

    assert not tracker.create_accepted
    assert not tracker.create_failed
    assert not tracker.pending(session)


def test_execution_tracker_ignores_a_late_unmarked_create_completion_after_retry() -> (
    None
):
    session: Any = SimpleNamespace(
        document=SimpleNamespace(cells=()),
        session_view=SimpleNamespace(cell_notifications={}),
    )
    tracker = session_state_module._ExecutionTracker(session, attached=False)
    create = CreateNotebookCommand(
        execution_requests=(),
        cell_ids=(),
        set_ui_element_value_request=UpdateUIElementCommand(object_ids=[], values=[]),
        auto_run=False,
    )
    tracker.on_received_command(session, create, None)
    tracker.reset_startup()
    tracker.on_received_command(session, create, None)
    tracker.on_notification_sent(
        session,
        serialize_kernel_message(CompletedRunNotification()),
    )

    assert tracker.pending(session)


def test_execution_tracker_ignores_a_delayed_create_start_after_retry_reset() -> None:
    session: Any = SimpleNamespace(
        document=SimpleNamespace(cells=()),
        session_view=SimpleNamespace(cell_notifications={}),
    )
    tracker = session_state_module._ExecutionTracker(session, attached=False)
    tracker.on_received_command(
        session,
        CreateNotebookCommand(
            execution_requests=(),
            cell_ids=(),
            set_ui_element_value_request=UpdateUIElementCommand(
                object_ids=[], values=[]
            ),
            auto_run=False,
        ),
        None,
    )
    tracker._marker_supported = True
    tracker.reset_startup()
    tracker.on_notification_sent(
        session,
        _marker("CreateNotebookCommand", "start", "delayed-create"),
    )
    tracker.on_notification_sent(
        session,
        _marker("CreateNotebookCommand", "done", "delayed-create"),
    )

    assert not tracker.create_accepted
    assert not tracker.create_failed
    assert not tracker.pending(session)


def test_execution_tracker_admits_a_retry_after_an_unmarked_create_failure() -> None:
    session: Any = SimpleNamespace(
        document=SimpleNamespace(cells=()),
        session_view=SimpleNamespace(cell_notifications={}),
    )
    tracker = session_state_module._ExecutionTracker(session, attached=False)
    create = CreateNotebookCommand(
        execution_requests=(),
        cell_ids=(),
        set_ui_element_value_request=UpdateUIElementCommand(object_ids=[], values=[]),
        auto_run=False,
    )

    tracker.on_received_command(session, create, None)
    tracker.reset_startup()
    tracker.on_received_command(session, create, None)
    tracker.on_notification_sent(
        session,
        _marker("CreateNotebookCommand", "start", "retry-create"),
    )
    tracker.on_notification_sent(
        session,
        _marker("CreateNotebookCommand", "failed", "retry-create"),
    )

    assert tracker.create_failed
    assert not tracker.create_accepted
    assert not tracker.pending(session)


def test_execution_tracker_admits_an_unmarked_create_when_later_markers_arrive() -> (
    None
):
    session: Any = SimpleNamespace(
        document=SimpleNamespace(cells=()),
        session_view=SimpleNamespace(cell_notifications={}),
    )
    tracker = session_state_module._ExecutionTracker(session, attached=False)
    tracker.on_received_command(
        session,
        CreateNotebookCommand(
            execution_requests=(),
            cell_ids=(),
            set_ui_element_value_request=UpdateUIElementCommand(
                object_ids=[], values=[]
            ),
            auto_run=False,
        ),
        None,
    )
    tracker.on_received_command(session, ExecuteStaleCellsCommand(), None)
    tracker.on_notification_sent(
        session,
        _marker("ExecuteStaleCellsCommand", "start", "after-create"),
    )
    tracker.on_notification_sent(
        session,
        _marker("ExecuteStaleCellsCommand", "done", "after-create"),
    )

    assert tracker.create_accepted
    assert not tracker.create_failed
    assert not tracker.pending(session)


def test_execution_tracker_accepts_a_retry_after_an_unmarked_create_failure() -> None:
    session: Any = SimpleNamespace(
        document=SimpleNamespace(cells=()),
        session_view=SimpleNamespace(cell_notifications={}),
    )
    tracker = session_state_module._ExecutionTracker(session, attached=False)
    create = CreateNotebookCommand(
        execution_requests=(),
        cell_ids=(),
        set_ui_element_value_request=UpdateUIElementCommand(object_ids=[], values=[]),
        auto_run=False,
    )

    tracker.on_received_command(session, create, None)
    tracker.reset_startup()
    tracker.on_received_command(session, create, None)
    tracker.on_notification_sent(
        session,
        _marker("CreateNotebookCommand", "start", "retry-create"),
    )
    tracker.on_notification_sent(
        session,
        _marker("CreateNotebookCommand", "done", "retry-create"),
    )

    assert tracker.create_accepted
    assert not tracker.create_failed
    assert not tracker.pending(session)


def test_execution_markers_exclude_scratchpad_completion_ids() -> None:
    assert not is_execution_command("ExecuteScratchpadCommand")
    assert (
        parse_marker(make_marker("done", "ExecuteScratchpadCommand", "scratchpad-1"))
        is None
    )


def test_execution_tracker_surfaces_a_failed_create_marker() -> None:
    session: Any = SimpleNamespace(
        document=SimpleNamespace(cells=()),
        session_view=SimpleNamespace(cell_notifications={}),
    )
    tracker = session_state_module._ExecutionTracker(session, attached=False)
    tracker.on_received_command(
        session,
        CreateNotebookCommand(
            execution_requests=(),
            cell_ids=(),
            set_ui_element_value_request=UpdateUIElementCommand(
                object_ids=[], values=[]
            ),
            auto_run=False,
        ),
        None,
    )
    tracker.on_notification_sent(
        session,
        _marker("CreateNotebookCommand", "start", "failed-create"),
    )
    tracker.on_notification_sent(
        session,
        _marker("CreateNotebookCommand", "failed", "failed-create"),
    )

    assert tracker.create_failed
    assert not tracker.create_accepted
    assert not tracker.pending(session)


def test_execution_tracker_waits_for_cell_config_completion() -> None:
    session: Any = SimpleNamespace(
        document=SimpleNamespace(cells=()),
        session_view=SimpleNamespace(cell_notifications={}),
    )
    tracker = session_state_module._ExecutionTracker(session, attached=False)
    tracker.on_received_command(
        session,
        UpdateCellConfigCommand(configs=cast(Any, {"first": {"hide_code": True}})),
        None,
    )
    assert not tracker.pending(session)
    tracker.on_notification_sent(
        session,
        _marker("UpdateCellConfigCommand", "start", "config-1"),
    )
    assert tracker.pending(session)
    tracker.on_notification_sent(
        session,
        _marker("UpdateCellConfigCommand", "done", "config-1"),
    )
    assert not tracker.pending(session)


def test_execution_tracker_waits_for_package_install_completion() -> None:
    session: Any = SimpleNamespace(
        document=SimpleNamespace(cells=()),
        session_view=SimpleNamespace(cell_notifications={}),
    )
    tracker = session_state_module._ExecutionTracker(session, attached=False)
    tracker.on_received_command(
        session,
        InstallPackagesCommand(manager="pip", versions={"polars": "1.0.0"}),
        None,
    )
    assert tracker.pending(session)
    tracker.on_notification_sent(
        session,
        _marker("InstallPackagesCommand", "start", "install-1"),
    )
    tracker.on_notification_sent(
        session,
        _marker("InstallPackagesCommand", "done", "install-1"),
    )
    assert not tracker.pending(session)


def test_execution_tracker_waits_for_model_update_completion() -> None:
    session: Any = SimpleNamespace(
        document=SimpleNamespace(cells=()),
        session_view=SimpleNamespace(
            cell_notifications={},
            model_states={"model": object()},
        ),
    )
    tracker = session_state_module._ExecutionTracker(session, attached=False)
    tracker.on_received_command(
        session,
        ModelCommand(
            model_id=cast(Any, "model"),
            message=ModelUpdateMessage(state={"value": 2}, buffer_paths=[]),
            buffers=[],
        ),
        None,
    )
    assert not tracker.pending(session)

    tracker.on_notification_sent(
        session,
        _marker("ModelCommand", "start", "model-1"),
    )
    assert tracker.pending(session)
    tracker.on_notification_sent(
        session,
        _marker("ModelCommand", "done", "model-1"),
    )
    assert not tracker.pending(session)


@pytest.mark.parametrize(
    "message",
    [ModelCustomMessage(content={}), ModelUpdateMessage(state={}, buffer_paths=[])],
)
def test_execution_tracker_does_not_wait_for_unmarked_model_messages(
    message: object,
) -> None:
    session: Any = SimpleNamespace(
        document=SimpleNamespace(cells=()),
        session_view=SimpleNamespace(cell_notifications={}),
    )
    tracker = session_state_module._ExecutionTracker(session, attached=False)
    tracker.on_received_command(
        session,
        ModelCommand(
            model_id=cast(Any, "model"),
            message=cast(Any, message),
            buffers=[],
        ),
        None,
    )
    assert not tracker.pending(session)


def test_execution_tracker_correlates_multiple_model_updates() -> None:
    session: Any = SimpleNamespace(
        document=SimpleNamespace(cells=()),
        session_view=SimpleNamespace(
            cell_notifications={},
            model_states={"first-model": object(), "second-model": object()},
        ),
    )
    tracker = session_state_module._ExecutionTracker(session, attached=False)
    for model_id in ("first-model", "second-model"):
        tracker.on_received_command(
            session,
            ModelCommand(
                model_id=cast(Any, model_id),
                message=ModelUpdateMessage(state={"value": 2}, buffer_paths=[]),
                buffers=[],
            ),
            None,
        )

    assert not tracker.pending(session)
    tracker.on_notification_sent(
        session,
        _marker("ModelCommand", "start", "model-1"),
    )
    tracker.on_notification_sent(
        session,
        _marker("ModelCommand", "start", "model-2"),
    )
    tracker.on_notification_sent(
        session,
        _marker("ModelCommand", "done", "model-2"),
    )
    assert tracker.pending(session)
    tracker.on_notification_sent(
        session,
        _marker("ModelCommand", "done", "model-1"),
    )
    assert not tracker.pending(session)


def test_execution_tracker_uses_cell_notifications_for_config_execution() -> None:
    session: Any = SimpleNamespace(
        document=SimpleNamespace(cells=()),
        session_view=SimpleNamespace(cell_notifications={}),
    )
    tracker = session_state_module._ExecutionTracker(session, attached=False)
    tracker.on_received_command(
        session,
        UpdateCellConfigCommand(configs=cast(Any, {"first": {"disabled": False}})),
        None,
    )
    assert not tracker.pending(session)
    tracker.on_notification_sent(
        session,
        _marker("UpdateCellConfigCommand", "start", "config-1"),
    )
    tracker.on_notification_sent(
        session,
        serialize_kernel_message(
            CellNotification(cast(Any, "first"), status="running")
        ),
    )
    assert tracker.pending(session)
    tracker.on_notification_sent(
        session,
        serialize_kernel_message(CellNotification(cast(Any, "first"), status="idle")),
    )
    tracker.on_notification_sent(
        session,
        _marker("UpdateCellConfigCommand", "done", "config-1"),
    )
    assert not tracker.pending(session)


def test_execution_tracker_correlates_create_and_stale_completions() -> None:
    session: Any = SimpleNamespace(
        document=SimpleNamespace(cells=()),
        session_view=SimpleNamespace(cell_notifications={}),
    )
    tracker = session_state_module._ExecutionTracker(session, attached=False)
    tracker.on_received_command(
        session,
        CreateNotebookCommand(
            execution_requests=(),
            cell_ids=(),
            set_ui_element_value_request=UpdateUIElementCommand(
                object_ids=[], values=[]
            ),
            auto_run=False,
        ),
        None,
    )
    tracker.on_received_command(session, ExecuteStaleCellsCommand(), None)
    tracker.on_notification_sent(
        session,
        _marker("CreateNotebookCommand", "start", "create-1"),
    )
    assert tracker.pending(session)
    tracker.on_notification_sent(
        session,
        _marker("CreateNotebookCommand", "done", "create-1"),
    )
    tracker.on_notification_sent(
        session,
        _marker("ExecuteStaleCellsCommand", "start", "stale-1"),
    )
    tracker.on_notification_sent(
        session,
        _marker("ExecuteStaleCellsCommand", "done", "stale-1"),
    )
    assert not tracker.pending(session)


def test_execution_tracker_waits_for_a_marked_unknown_model_update_completion() -> None:
    session: Any = SimpleNamespace(
        document=SimpleNamespace(cells=()),
        session_view=SimpleNamespace(cell_notifications={}, model_states={}),
    )
    tracker = session_state_module._ExecutionTracker(session, attached=False)
    tracker.on_received_command(
        session,
        ModelCommand(
            model_id=cast(Any, "missing"),
            message=ModelUpdateMessage(state={}, buffer_paths=[]),
            buffers=[],
        ),
        None,
    )
    assert not tracker.pending(session)
    tracker.on_notification_sent(
        session,
        _marker("ModelCommand", "start", "model-1"),
    )
    assert tracker.pending(session)
    tracker.on_notification_sent(
        session,
        _marker("ModelCommand", "done", "model-1"),
    )
    assert not tracker.pending(session)


@pytest.mark.parametrize(
    ("change", "replacement"),
    (
        (
            "edit",
            replace(
                _live_capture(),
                document_generation=2,
                cells=(
                    ("first", "value = 2", "value"),
                    ("second", "value", "_"),
                ),
            ),
        ),
        (
            "reorder",
            replace(
                _live_capture(),
                document_generation=2,
                cells=tuple(reversed(_live_capture().cells)),
            ),
        ),
        (
            "save",
            replace(
                _live_capture(),
                session_owner=8,
                document_generation=0,
            ),
        ),
        (
            "evidence",
            replace(
                _live_capture(),
                executed_cells=(("first", "value = 2"),),
                graph_parents=(("first", ()), ("second", ())),
            ),
        ),
    ),
)
def test_live_cell_capture_rejects_a_concurrent_generation_change(
    monkeypatch: pytest.MonkeyPatch,
    change: str,
    replacement: session_state_module._LiveCellCapture,
) -> None:
    capture = _live_capture()
    captures = iter((capture, replacement))
    materializing = threading.Event()
    release = threading.Event()
    native_materialize = session_state_module._materialize_live_cells

    monkeypatch.setattr(
        session_state_module,
        "_capture_live_cells",
        lambda *_args, **_kwargs: next(captures),
    )

    def materialize(value: session_state_module._LiveCellCapture):
        materializing.set()
        assert release.wait(timeout=2), change
        return native_materialize(value)

    monkeypatch.setattr(session_state_module, "_materialize_live_cells", materialize)

    async def exercise() -> None:
        task = asyncio.create_task(
            PrivateSessionState().live_cells(
                cast(Any, object()),
                "s_123456",
                include_dependency_closures=True,
            )
        )
        assert await asyncio.to_thread(materializing.wait, 1), change
        release.set()
        with pytest.raises(RuntimeSyncError, match="changed while Studio captured"):
            await task

    try:
        asyncio.run(exercise())
    finally:
        release.set()


def test_live_cell_materialization_keeps_the_running_and_latest_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base = _live_capture()
    captures_by_generation = {
        generation: replace(base, document_generation=generation)
        for generation in range(1, 5)
    }
    captures = iter(
        (
            captures_by_generation[1],
            captures_by_generation[2],
            captures_by_generation[3],
            captures_by_generation[4],
            captures_by_generation[4],
        )
    )
    materialized: list[int] = []
    started = threading.Event()
    release = threading.Event()
    native_materialize = session_state_module._materialize_live_cells

    monkeypatch.setattr(
        session_state_module,
        "_capture_live_cells",
        lambda *_args, **_kwargs: next(captures),
    )

    def materialize(capture: session_state_module._LiveCellCapture):
        materialized.append(capture.document_generation)
        if len(materialized) == 1:
            started.set()
            assert release.wait(timeout=2)
        return native_materialize(capture)

    monkeypatch.setattr(session_state_module, "_materialize_live_cells", materialize)
    state = PrivateSessionState()

    async def capture() -> object:
        return await state.live_cells(
            cast(Any, object()),
            "s_123456",
            include_dependency_closures=True,
        )

    async def exercise() -> list[object]:
        tasks = [asyncio.create_task(capture())]
        assert await asyncio.to_thread(started.wait, 1)
        for _generation in range(2, 5):
            tasks.append(asyncio.create_task(capture()))
            await asyncio.sleep(0)
        release.set()
        return await asyncio.gather(*tasks, return_exceptions=True)

    try:
        results = asyncio.run(exercise())
    finally:
        release.set()

    assert materialized == [1, 4]
    assert all(isinstance(result, RuntimeSyncError) for result in results[:-1])
    assert isinstance(results[-1], session_state_module.LiveCellSnapshot)


def test_runtime_config_and_evidence_capture_in_separate_owner_lanes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_capture = replace(_live_capture(), graph_parents=None)
    evidence_capture = _live_capture()
    materialized: list[bool] = []
    started = threading.Event()
    release = threading.Event()
    native_materialize = session_state_module._materialize_live_cells

    def capture_cells(
        *_args: object,
        include_dependency_closures: bool,
        **_kwargs: object,
    ) -> session_state_module._LiveCellCapture:
        return evidence_capture if include_dependency_closures else config_capture

    def materialize(capture: session_state_module._LiveCellCapture):
        materialized.append(capture.graph_parents is not None)
        if len(materialized) == 1:
            started.set()
            assert release.wait(timeout=2)
        return native_materialize(capture)

    monkeypatch.setattr(session_state_module, "_capture_live_cells", capture_cells)
    monkeypatch.setattr(session_state_module, "_materialize_live_cells", materialize)
    state = PrivateSessionState()

    async def exercise() -> tuple[object, object]:
        config = asyncio.create_task(
            state.live_cells(
                cast(Any, object()),
                "s_123456",
                include_dependency_closures=False,
            )
        )
        assert await asyncio.to_thread(started.wait, 1)
        evidence = asyncio.create_task(
            state.live_cells(
                cast(Any, object()),
                "s_123456",
                include_dependency_closures=True,
            )
        )
        await asyncio.sleep(0)
        release.set()
        return await config, await evidence

    try:
        config, evidence = asyncio.run(exercise())
    finally:
        release.set()

    assert materialized == [False, True]
    assert isinstance(config, session_state_module.LiveCellSnapshot)
    assert isinstance(evidence, session_state_module.LiveCellSnapshot)


def test_session_close_drains_live_cell_materialization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    capture = _live_capture()
    started = threading.Event()
    release = threading.Event()
    native_materialize = session_state_module._materialize_live_cells
    monkeypatch.setattr(
        session_state_module,
        "_capture_live_cells",
        lambda *_args, **_kwargs: capture,
    )

    def materialize(value: session_state_module._LiveCellCapture):
        started.set()
        assert release.wait(timeout=2)
        return native_materialize(value)

    monkeypatch.setattr(session_state_module, "_materialize_live_cells", materialize)
    state = PrivateSessionState()

    async def exercise() -> None:
        capturing = asyncio.create_task(
            state.live_cells(
                cast(Any, object()),
                "s_123456",
                include_dependency_closures=True,
            )
        )
        assert await asyncio.to_thread(started.wait, 1)
        closing = asyncio.create_task(state.close())
        await asyncio.sleep(0)
        assert not closing.done()
        release.set()
        await closing
        result = await asyncio.gather(capturing, return_exceptions=True)
        assert isinstance(result[0], RuntimeSyncError)
        with pytest.raises(RuntimeSyncError, match="shutting down"):
            await state.live_cells(
                cast(Any, object()),
                "s_123456",
                include_dependency_closures=False,
            )

    try:
        asyncio.run(exercise())
    finally:
        release.set()


def test_session_close_cancellation_drains_startup_ownership() -> None:
    class Session:
        pass

    async def exercise() -> None:
        state = PrivateSessionState()
        session = cast(Any, Session())
        cleanup_started = asyncio.Event()
        release = asyncio.Event()

        async def startup() -> None:
            try:
                await asyncio.Future()
            except asyncio.CancelledError:
                cleanup_started.set()
                await release.wait()
                raise

        startup_task = asyncio.create_task(startup())
        state._starting[session] = startup_task
        closing = asyncio.create_task(state.close())
        await cleanup_started.wait()
        closing.cancel()
        closing.cancel()
        await asyncio.sleep(0)
        assert not closing.done()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await closing
        assert not state._starting
        assert startup_task.done()

    asyncio.run(exercise())


@pytest.mark.parametrize("replacement", [None, "consumer", "canonical"])
def test_control_bindings_resolve_a_shared_consumers_canonical_session(
    monkeypatch: pytest.MonkeyPatch,
    replacement: str | None,
) -> None:
    from contextlib import contextmanager

    from marimo_export import sessions as export_sessions
    from marimo_export.index import ControlBinding

    session = SimpleNamespace(room=SimpleNamespace(main_consumer=None))
    manager = SimpleNamespace(sessions={"s_kernel": session})
    consumers = {"s_view01": session}
    context = SimpleNamespace(
        internal_url="http://localhost:4321",
        server_token="token",
        access_token="access-token",
    )
    monkeypatch.setattr(
        session_state_module,
        "context_handle",
        lambda _context: SimpleNamespace(session_manager=manager),
    )
    monkeypatch.setattr(
        session_state_module,
        "current_session",
        lambda _context, session_id: consumers.get(session_id),
    )

    def observe_inputs() -> object:
        if replacement == "consumer":
            consumers["s_view01"] = SimpleNamespace()
        elif replacement == "canonical":
            manager.sessions["s_kernel"] = SimpleNamespace()
        return SimpleNamespace(
            control_bindings={
                "scale-control": ControlBinding("scale", ()),
            }
        )

    def exported_session(session_id: str) -> object:
        assert session_id == "s_kernel"
        return SimpleNamespace(observe_inputs=observe_inputs)

    @contextmanager
    def connect(server: str, *, access_token: str, server_token: str):
        assert (server, access_token, server_token) == (
            "http://localhost:4321",
            "access-token",
            "token",
        )
        yield SimpleNamespace(session=exported_session)

    monkeypatch.setattr(export_sessions, "connect", connect)

    async def exercise() -> None:
        adapter = PrivateSessionState()
        try:
            if replacement is not None:
                with pytest.raises(RuntimeSyncError, match="notebook changed"):
                    await adapter.control_bindings(cast(Any, context), "s_view01")
            else:
                assert await adapter.control_bindings(
                    cast(Any, context), "s_view01"
                ) == {
                    "scale-control": {"input": "scale", "path": []},
                }
        finally:
            await adapter.close()

    asyncio.run(exercise())
