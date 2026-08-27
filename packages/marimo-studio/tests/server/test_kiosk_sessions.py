"""Protect run-mode session isolation."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event
from types import SimpleNamespace
from typing import Any, cast

import pytest
from marimo._server.api.endpoints.ws.ws_session_connector import (
    ConnectionType,
    SessionConnector,
)
from marimo._server.api.endpoints.ws_endpoint import WebSocketHandler
from starlette.datastructures import QueryParams
from starlette.websockets import WebSocketDisconnect

import marimo_studio._compat.server.existing_session as existing_session_module
from marimo_studio._compat.server.existing_session import (
    _PREVIEW_CONNECT_GRACE,
    PrivateExistingSessionAttachment,
)
from marimo_studio._delivery.urls import (
    DOCUMENT_LIFECYCLE_QUERY_PARAM,
    STUDIO_CLIENT_QUERY_PARAM,
)
from marimo_studio._server.presentation.admission import (
    NATIVE_SESSION_ADMISSION_SCOPE_KEY,
    NativeSessionAdmission,
)
from marimo_studio._server.server_instance import server_instance_id

from ..marimo_compat.session_adapter_test_support import (
    Manager as _Manager,
)
from ..marimo_compat.session_adapter_test_support import (
    ObservedRLock as _ObservedRLock,
)
from ..marimo_compat.session_adapter_test_support import (
    Session as _Session,
)
from ..marimo_compat.session_adapter_test_support import connect as _connect
from ..marimo_compat.session_adapter_test_support import context as _context
from ..marimo_compat.session_adapter_test_support import open_adapter as _open


def _connect_preview(
    manager: _Manager,
    consumer_id: str,
    query: dict[str, str],
    *,
    studio_owned: bool = False,
    client_owned: bool = True,
) -> tuple[object, ConnectionType]:
    connected: list[object] = []
    created = (object(), ConnectionType.NEW)
    connector = SessionConnector(
        manager=cast(Any, manager),
        handler=cast(
            Any,
            SimpleNamespace(_connect_kiosk=lambda session: connected.append(session)),
        ),
        params=cast(
            Any,
            SimpleNamespace(
                session_id=consumer_id,
                file_key="notebook.py",
                kiosk=True,
            ),
        ),
        connection=cast(
            Any,
            SimpleNamespace(
                query_params=QueryParams(
                    {
                        **(
                            {STUDIO_CLIENT_QUERY_PARAM: "client-1234"}
                            if client_owned
                            else {}
                        ),
                        **(
                            {DOCUMENT_LIFECYCLE_QUERY_PARAM: "7"}
                            if studio_owned
                            else {}
                        ),
                        **query,
                    }
                )
            ),
        ),
    )
    cast(Any, connector)._create_new_session = lambda: created
    result = connector._connect_kiosk()
    if result is created:
        assert connected == []
    else:
        assert connected == [result[0]]
    return result


def test_each_studio_editor_creates_its_own_session() -> None:
    manager = _Manager()
    manager.fallback = _Session()
    created = (object(), ConnectionType.NEW)
    connector = SessionConnector(
        manager=cast(Any, manager),
        handler=cast(Any, SimpleNamespace()),
        params=cast(
            Any,
            SimpleNamespace(
                session_id="s_editor2",
                file_key="notebook.py",
                kiosk=False,
            ),
        ),
        connection=cast(
            Any,
            SimpleNamespace(
                query_params=QueryParams(
                    {
                        STUDIO_CLIENT_QUERY_PARAM: "client-1234",
                        "marimo_studio_server": server_instance_id("token"),
                    }
                )
            ),
        ),
    )
    cast(Any, connector)._create_new_session = lambda: created
    _adapter, handle = _open(manager)
    try:
        assert connector.connect() is created
    finally:
        handle.close()


@pytest.mark.parametrize("claimed_file", ("notebook.py", "foreign.py"))
def test_fresh_admission_rejects_a_connector_time_preclaim(
    claimed_file: str,
) -> None:
    manager = _Manager()
    runtime_session_id = "s_native"
    admission = NativeSessionAdmission(
        expected_claim=None,
        file_key="notebook.py",
        mode="fresh",
        notebook=str(Path("notebook.py").resolve()),
        runtime_session_id=runtime_session_id,
    )
    connector = SessionConnector(
        manager=cast(Any, manager),
        handler=cast(Any, SimpleNamespace()),
        params=cast(
            Any,
            SimpleNamespace(
                session_id=runtime_session_id,
                file_key="notebook.py",
                kiosk=False,
            ),
        ),
        connection=cast(
            Any,
            SimpleNamespace(
                query_params=QueryParams(),
                scope={NATIVE_SESSION_ADMISSION_SCOPE_KEY: admission},
            ),
        ),
    )
    barrier = Event()

    def claim() -> None:
        barrier.wait()
        manager.sessions[runtime_session_id] = _Session(claimed_file)

    _adapter, handle = _open(manager)
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            claimed = pool.submit(claim)
            barrier.set()
            claimed.result()
            with pytest.raises(WebSocketDisconnect):
                connector.connect()
    finally:
        handle.close()

    assert admission.rejected


def test_replay_admission_requires_the_exact_preauthorized_session() -> None:
    manager = _Manager()
    runtime_session_id = "s_replay"
    expected_claim = _Session("notebook.py")
    manager.sessions[runtime_session_id] = expected_claim
    admission = NativeSessionAdmission(
        expected_claim=expected_claim,
        file_key="notebook.py",
        mode="current",
        notebook=str(Path("notebook.py").resolve()),
        runtime_session_id=runtime_session_id,
    )
    connector = SessionConnector(
        manager=cast(Any, manager),
        handler=cast(Any, SimpleNamespace()),
        params=cast(
            Any,
            SimpleNamespace(
                session_id=runtime_session_id,
                file_key="notebook.py",
                kiosk=False,
            ),
        ),
        connection=cast(
            Any,
            SimpleNamespace(
                query_params=QueryParams(),
                scope={NATIVE_SESSION_ADMISSION_SCOPE_KEY: admission},
            ),
        ),
    )

    existing_session_module._verify_native_admission(connector)
    barrier = Event()

    def replace() -> None:
        barrier.wait()
        manager.sessions[runtime_session_id] = _Session("notebook.py")

    with ThreadPoolExecutor(max_workers=1) as pool:
        replaced = pool.submit(replace)
        barrier.set()
        replaced.result()
    with pytest.raises(WebSocketDisconnect):
        existing_session_module._verify_native_admission(connector)

    assert admission.rejected


@pytest.mark.parametrize(
    ("replay_on_reconnect", "expected_replay"),
    ((True, True), (False, False)),
    ids=("studio-editor", "native-default"),
)
def test_current_admission_selects_the_reconnect_snapshot_contract(
    replay_on_reconnect: bool,
    expected_replay: bool,
) -> None:
    class Session(_Session):
        def __init__(self) -> None:
            super().__init__()
            self.disconnects = 0

        def disconnect_main_consumer(self) -> None:
            self.disconnects += 1

    manager = _Manager()
    runtime_session_id = "s_replay"
    session = Session()
    manager.sessions[runtime_session_id] = session
    replays: list[bool] = []
    admission = NativeSessionAdmission(
        expected_claim=session,
        file_key="notebook.py",
        mode="current",
        notebook=str(Path("notebook.py").resolve()),
        runtime_session_id=runtime_session_id,
        replay_on_reconnect=replay_on_reconnect,
    )
    connector = SessionConnector(
        manager=cast(Any, manager),
        handler=cast(
            Any,
            SimpleNamespace(
                _reconnect_session=lambda _session, replay: replays.append(replay)
            ),
        ),
        params=cast(
            Any,
            SimpleNamespace(
                session_id=runtime_session_id,
                file_key="notebook.py",
                kiosk=False,
            ),
        ),
        connection=cast(
            Any,
            SimpleNamespace(
                query_params=QueryParams(),
                scope={NATIVE_SESSION_ADMISSION_SCOPE_KEY: admission},
            ),
        ),
    )

    def native_connect(active: SessionConnector) -> tuple[object, ConnectionType]:
        return active._reconnect_session(cast(Any, session))

    assert existing_session_module._session_connect_replacement(native_connect)(
        connector
    ) == (session, ConnectionType.RECONNECT)
    assert session.disconnects == 1
    assert replays == [expected_replay]


def test_preview_consumers_attach_to_the_exact_editor_session() -> None:
    manager = _Manager()
    first = _Session()
    second = _Session()
    manager.sessions = {"s_first1": first, "s_second": second}
    adapter, handle = _open(manager)
    try:
        assert adapter.attach(_context(manager), "s_view01", "s_first1")
        assert adapter.attach(_context(manager), "s_view02", "s_second")

        assert _connect(manager, "s_view01") == (first, ConnectionType.KIOSK)
        assert _connect(manager, "s_view02") == (second, ConnectionType.KIOSK)
        assert manager.get_session("s_view01") is None
    finally:
        handle.close()


def test_popout_reuses_the_editor_session_for_its_creation_query() -> None:
    manager = _Manager()
    target = _Session(query={"region": "emea"})
    manager.sessions = {"s_target": target}
    adapter, handle = _open(manager)
    try:
        assert adapter.attach(_context(manager), "s_view01", "s_target")

        assert _connect_preview(
            manager,
            "s_view01",
            {
                "region": "emea",
                "file": "forged.py",
                "access_token": "secret",
            },
        ) == (target, ConnectionType.KIOSK)
    finally:
        handle.close()


def test_popout_creates_a_query_correct_session_when_public_query_changes() -> None:
    manager = _Manager()
    target = _Session(query={"region": "emea"})
    manager.sessions = {"s_target": target}
    adapter, handle = _open(manager)
    try:
        assert adapter.attach(_context(manager), "s_view01", "s_target")

        session, connection = _connect_preview(
            manager,
            "s_view01",
            {"region": "apac"},
        )

        assert session is not target
        assert connection is ConnectionType.NEW
    finally:
        handle.close()


def test_reloaded_popout_without_client_marker_keeps_query_correctness() -> None:
    manager = _Manager()
    target = _Session(query={"region": "emea"})
    manager.sessions = {"s_target": target}
    manager.fallback = target
    _adapter, handle = _open(manager)
    try:
        session, connection = _connect_preview(
            manager,
            "s_view01",
            {"region": "apac"},
            client_owned=False,
        )

        assert session is not target
        assert connection is ConnectionType.NEW
    finally:
        handle.close()


def test_studio_owned_preview_keeps_the_editor_query_lane() -> None:
    manager = _Manager()
    target = _Session(query={"region": "emea"})
    manager.sessions = {"s_target": target}
    adapter, handle = _open(manager)
    try:
        assert adapter.attach(_context(manager), "s_view01", "s_target")

        assert _connect_preview(
            manager,
            "s_view01",
            {"region": "apac"},
            studio_owned=True,
        ) == (target, ConnectionType.KIOSK)
    finally:
        handle.close()


def test_studio_lifecycle_cannot_claim_an_unregistered_native_session() -> None:
    manager = _Manager()
    manager.sessions = {"s_native": _Session(query={"region": "emea"})}
    _adapter, handle = _open(manager)
    try:
        with pytest.raises(WebSocketDisconnect):
            _connect_preview(
                manager,
                "s_native",
                {"region": "apac"},
                studio_owned=True,
            )
    finally:
        handle.close()


def test_studio_preview_never_falls_back_to_a_file_session() -> None:
    manager = _Manager()
    target = _Session()
    manager.sessions["s_target"] = target
    manager.fallback = _Session()
    adapter, handle = _open(manager)
    try:
        assert adapter.attach(_context(manager), "s_view01", "s_target")
        manager.sessions.clear()

        with pytest.raises(WebSocketDisconnect):
            _connect(manager, "s_view01")

        assert manager.fallback_calls == 0
    finally:
        handle.close()


def test_native_consumer_id_collision_is_rejected() -> None:
    manager = _Manager()
    target = _Session()
    native = _Session()
    manager.sessions = {"s_target": target, "s_view01": native}
    adapter, handle = _open(manager)
    try:
        assert not adapter.attach(_context(manager), "s_view01", "s_target")
        assert manager.get_session("s_view01") is native
    finally:
        handle.close()


def test_fresh_unclaimed_routes_hold_capacity() -> None:
    manager = _Manager()
    target = _Session()
    manager.sessions["s_target"] = target
    adapter, handle = _open(manager)
    try:
        for index in range(100):
            assert adapter.attach(
                _context(manager),
                f"s_view{index:03d}",
                "s_target",
            )
        assert not adapter.attach(_context(manager), "s_overflow", "s_target")
    finally:
        handle.close()


def test_expired_unclaimed_routes_release_capacity() -> None:
    now = 0.0
    manager = _Manager()
    target = _Session()
    manager.sessions["s_target"] = target
    adapter, handle = _open(manager, clock=lambda: now)
    try:
        for index in range(100):
            assert adapter.attach(
                _context(manager),
                f"s_view{index:03d}",
                "s_target",
            )
        now = _PREVIEW_CONNECT_GRACE + 1
        assert adapter.attach(_context(manager), "s_overflow", "s_target")
        with pytest.raises(WebSocketDisconnect):
            _connect(manager, "s_view000")
        assert _connect(manager, "s_overflow") == (target, ConnectionType.KIOSK)
    finally:
        handle.close()


def test_final_lifecycle_close_restores_private_patches() -> None:
    original_session_connect = SessionConnector.connect
    original_connector = SessionConnector._connect_kiosk
    original_start = WebSocketHandler.start
    original_safe_close = WebSocketHandler._safe_close
    first = PrivateExistingSessionAttachment()
    second = PrivateExistingSessionAttachment()
    first_handle = first.open()
    replacement_session_connect = SessionConnector.connect
    replacement_connector = SessionConnector._connect_kiosk
    replacement_start = WebSocketHandler.start
    replacement_safe_close = WebSocketHandler._safe_close
    second_handle = second.open()

    first_handle.close()
    assert SessionConnector.connect is replacement_session_connect
    assert SessionConnector._connect_kiosk is replacement_connector
    assert WebSocketHandler.start is replacement_start
    assert WebSocketHandler._safe_close is replacement_safe_close

    second_handle.close()
    assert SessionConnector.connect is original_session_connect
    assert SessionConnector._connect_kiosk is original_connector
    assert WebSocketHandler.start is original_start
    assert WebSocketHandler._safe_close is original_safe_close


def test_lifecycle_close_removes_owned_routes() -> None:
    manager = _Manager()
    target = _Session()
    manager.sessions["s_target"] = target
    adapter, handle = _open(manager)
    assert adapter.attach(_context(manager), "s_view01", "s_target")

    handle.close()
    verifier = PrivateExistingSessionAttachment()
    verifier_handle = verifier.open()
    try:
        with pytest.raises(WebSocketDisconnect):
            _connect(manager, "s_view01")
    finally:
        verifier_handle.close()


def test_lifecycle_close_serializes_with_route_registration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = _Manager()
    target = _Session()
    manager.sessions["s_target"] = target
    observed_lock = _ObservedRLock()
    monkeypatch.setattr(existing_session_module, "_ROUTERS_LOCK", observed_lock)
    entered_registration = Event()
    continue_registration = Event()
    native_register = existing_session_module._SessionRouter.register

    def blocking_register(
        router: Any,
        owner: object,
        consumer_id: str,
        session: object,
    ) -> bool:
        entered_registration.set()
        assert continue_registration.wait(timeout=2)
        return native_register(router, owner, consumer_id, session)

    monkeypatch.setattr(
        existing_session_module._SessionRouter,
        "register",
        blocking_register,
    )
    adapter, handle = _open(manager)

    with ThreadPoolExecutor(max_workers=2) as executor:
        attaching = executor.submit(
            adapter.attach,
            _context(manager),
            "s_view01",
            "s_target",
        )
        assert entered_registration.wait(timeout=2)
        closing = executor.submit(handle.close)
        try:
            assert observed_lock.contended.wait(timeout=2)
        finally:
            continue_registration.set()
        assert attaching.result(timeout=2)
        closing.result(timeout=2)

    assert not adapter.attach(_context(manager), "s_view02", "s_target")
    verifier = PrivateExistingSessionAttachment()
    verifier_handle = verifier.open()
    try:
        with pytest.raises(WebSocketDisconnect):
            _connect(manager, "s_view01")
    finally:
        verifier_handle.close()
