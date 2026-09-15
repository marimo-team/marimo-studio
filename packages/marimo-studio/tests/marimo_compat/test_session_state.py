"""Protect Marimo session ownership and detached live-cell capture."""

import asyncio
import threading
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from marimo._messaging.notification import (
    QueryParamsSetNotification,
    ReloadNotification,
)
from marimo._messaging.serde import deserialize_kernel_message
from starlette.datastructures import QueryParams

import marimo_studio._compat.server.session_state as session_state_module
from marimo_studio._compat.server.session_state import (
    PrivateSessionState,
    session_creation_query_matches,
    session_matches_notebook,
)
from marimo_studio._server.ports import EditorSessionIdentity
from marimo_studio.errors._internal import RuntimeSyncError


def _live_capture() -> session_state_module._LiveCellCapture:
    return session_state_module._LiveCellCapture(
        session_owner=7,
        document_generation=1,
        cells=(("first", "value = 1", "value"), ("second", "value", "_")),
        executed_cells=(("first", "value = 1"), ("second", "value")),
        graph_parents=(("first", ()), ("second", ("first",))),
    )


def test_session_owner_uses_the_initialization_identity() -> None:
    class UnreadablePath:
        def __fspath__(self) -> str:
            raise AssertionError("established sessions must not resolve their path")

    session = SimpleNamespace(
        initialization_id="notebook.py",
        app_file_manager=SimpleNamespace(path=UnreadablePath()),
    )

    assert session_matches_notebook(
        cast(Any, session),
        file_key="notebook.py",
        notebook=Path("/workspace/notebook.py"),
    )


def test_session_owner_accepts_the_current_notebook_path(tmp_path: Path) -> None:
    notebook = tmp_path / "notebook.py"
    session = SimpleNamespace(
        initialization_id=str(tmp_path / "nested" / "notebook.py"),
        app_file_manager=SimpleNamespace(path=str(notebook)),
    )

    assert session_matches_notebook(
        cast(Any, session),
        file_key="notebook.py",
        notebook=notebook,
    )


def test_session_owner_rejects_another_notebook_path(tmp_path: Path) -> None:
    notebook = tmp_path / "notebook.py"
    session = SimpleNamespace(
        initialization_id="other.py",
        app_file_manager=SimpleNamespace(path=str(tmp_path / "other.py")),
    )

    assert not session_matches_notebook(
        cast(Any, session),
        file_key="notebook.py",
        notebook=notebook,
    )


def test_app_host_session_exposes_its_creation_query() -> None:
    session = SimpleNamespace(
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

    session = SimpleNamespace(
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
    session = SimpleNamespace(
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
