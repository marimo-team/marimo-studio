"""Protect editor session lifetime ownership and settlement races."""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from types import SimpleNamespace
from typing import Any, cast

import pytest
from marimo._server.api.endpoints.ws.session_handler import SessionHandler
from marimo._server.api.endpoints.ws.ws_session_connector import ConnectionType
from starlette.datastructures import QueryParams
from starlette.websockets import WebSocketDisconnect

import marimo_studio._compat.server.editor_session_lifetimes as lifetime_module
import marimo_studio._compat.server.existing_session as existing_session_module
from marimo_studio._compat.server.existing_session import (
    PrivateExistingSessionAttachment,
)
from marimo_studio._delivery.urls import (
    SERVER_INSTANCE_QUERY_PARAM,
    STUDIO_CLIENT_QUERY_PARAM,
)
from marimo_studio._server.agent.clients import StudioClientRegistry
from marimo_studio._server.presentation.admission import (
    NATIVE_SESSION_ADMISSION_SCOPE_KEY,
    NativeSessionAdmission,
)
from marimo_studio._server.server_instance import server_instance_id

from .session_adapter_test_support import Manager as _Manager
from .session_adapter_test_support import ObservedRLock as _ObservedRLock
from .session_adapter_test_support import Session as _Session
from .session_adapter_test_support import context as _context
from .session_adapter_test_support import open_adapter as _open


def test_session_lifetime_cleanup_is_isolated_between_adapter_owners() -> None:
    async def exercise() -> None:
        original = SessionHandler._on_disconnect
        first_manager = _Manager()
        second_manager = _Manager()
        first_manager.ttl_seconds = None
        second_manager.ttl_seconds = None
        first_session = _Session()
        second_session = _Session()
        first_session.ttl_seconds = 60
        second_session.ttl_seconds = 60
        first_manager.sessions["s_first1"] = first_session
        second_manager.sessions["s_second"] = second_session
        first_adapter, first_handle = _open(first_manager)
        first_owner = first_adapter.claim_editor_lifetime(_context(first_manager))
        assert first_owner is not None
        patched = SessionHandler._on_disconnect
        second_adapter, second_handle = _open(second_manager)
        second_owner = second_adapter.claim_editor_lifetime(_context(second_manager))
        assert second_owner is not None
        lifetime_module._accept_studio_session(
            first_manager,
            "s_first1",
            first_session,
            lambda: None,
            first_owner,
        )
        lifetime_module._accept_studio_session(
            second_manager,
            "s_second",
            second_session,
            lambda: None,
            second_owner,
        )

        first_handle.close()
        assert first_manager.get_session("s_first1") is None
        assert second_manager.get_session("s_second") is second_session
        assert SessionHandler._on_disconnect is patched
        assert first_session not in lifetime_module._STUDIO_SESSION_LIFETIMES
        assert second_session in lifetime_module._STUDIO_SESSION_LIFETIMES

        second_handle.close()
        assert second_manager.get_session("s_second") is None
        assert SessionHandler._on_disconnect is original
        assert not lifetime_module._STUDIO_SESSION_LIFETIMES

    asyncio.run(exercise())


def test_shared_manager_lifetime_waits_for_its_final_adapter_owner() -> None:
    async def exercise() -> None:
        manager = _Manager()
        manager.ttl_seconds = None
        session = _Session()
        session.ttl_seconds = 60
        manager.sessions["s_target"] = session
        first_adapter, first_handle = _open(manager)
        second_adapter, second_handle = _open(manager)
        presentation_adapter, presentation_handle = _open(manager)
        first_owner = first_adapter.claim_editor_lifetime(_context(manager))
        assert first_owner is not None
        second_owner = second_adapter.claim_editor_lifetime(_context(manager))
        assert second_owner is not None
        assert presentation_adapter.attach(
            _context(manager),
            "s_view01",
            "s_target",
        )
        first_callbacks: list[object] = []
        second_callbacks: list[object] = []
        assert lifetime_module._accept_studio_session(
            manager,
            "s_target",
            session,
            (_first_callback := lambda: first_callbacks.append(session)),
            first_owner,
        )
        assert lifetime_module._accept_studio_session(
            manager,
            "s_target",
            session,
            (_second_callback := lambda: second_callbacks.append(session)),
            second_owner,
        )

        presentation_handle.close()
        assert manager.get_session("s_target") is session

        first_handle.close()
        assert manager.get_session("s_target") is session
        assert session in lifetime_module._STUDIO_SESSION_LIFETIMES
        assert first_callbacks == [session]
        assert second_callbacks == []

        second_handle.close()
        assert manager.get_session("s_target") is None
        assert session not in lifetime_module._STUDIO_SESSION_LIFETIMES
        assert second_callbacks == [session]

    asyncio.run(exercise())


@pytest.mark.parametrize("native_close", [False, True])
def test_shared_kernel_retains_each_consumers_close_callback(
    native_close: bool,
) -> None:
    class Manager(_Manager):
        def __init__(self) -> None:
            super().__init__()
            self.connected: set[str] = set()

        def get_session(self, session_id: object) -> _Session | None:
            if str(session_id) in self.connected:
                return self.sessions.get("s_kernel")
            return super().get_session(session_id)

    manager = Manager()
    session = _Session()
    manager.sessions["s_kernel"] = session
    manager.connected.update(("s_first1", "s_second"))
    adapter, handle = _open(manager)
    owner = adapter.claim_editor_lifetime(_context(manager))
    callbacks: list[str] = []
    admissions = {
        consumer_id: lambda consumer_id=consumer_id: callbacks.append(consumer_id)
        for consumer_id in ("s_first1", "s_second")
    }
    try:
        for consumer_id, callback in admissions.items():
            assert lifetime_module._accept_studio_session(
                manager,
                consumer_id,
                session,
                callback,
                owner,
            )
        manager.connected.remove("s_second")
        lifetime_module._notify_closed_studio_session(session)
        assert manager.get_session("s_first1") is session
        assert callbacks == []
        if native_close:
            manager.close_session("s_kernel")
            asyncio.run(manager._event_bus.emit_session_closed(cast(Any, session)))
            assert callbacks == ["s_first1", "s_second"]
    finally:
        handle.close()
    assert manager.get_session("s_kernel") is None
    assert callbacks == ["s_first1", "s_second"]


def test_resumed_kernel_closes_by_its_current_repository_identity() -> None:
    manager = _Manager()
    session = _Session()
    manager.sessions["s_first1"] = session
    adapter, handle = _open(manager)
    owner = adapter.claim_editor_lifetime(_context(manager))
    callbacks: list[object] = []

    def on_close() -> None:
        callbacks.append(session)

    try:
        assert lifetime_module._accept_studio_session(
            manager,
            "s_first1",
            session,
            on_close,
            owner,
        )
        manager.sessions["s_second"] = manager.sessions.pop("s_first1")
        replacement = _Session()
        manager.sessions["s_first1"] = replacement
        lifetime_module._notify_closed_studio_session(session)
        assert callbacks == []
        assert manager.get_session("s_second") is session
    finally:
        handle.close()
    assert manager.get_session("s_second") is None
    assert manager.get_session("s_first1") is replacement
    assert callbacks == [session]


def test_discarded_connection_releases_its_browser_while_kernel_is_retained() -> None:
    import gc
    from weakref import ref

    class Browser:
        def closed(self) -> None:
            return None

    manager = _Manager()
    session = _Session()
    manager.sessions["s_target"] = session
    adapter, handle = _open(manager)
    owner = adapter.claim_editor_lifetime(_context(manager))
    browser = Browser()
    retained = ref(browser)
    admission = NativeSessionAdmission(
        expected_claim=session,
        file_key="notebook.py",
        mode="current",
        notebook="notebook.py",
        runtime_session_id="s_target",
        on_close=browser.closed,
    )
    try:
        assert lifetime_module._accept_studio_session(
            manager,
            "s_target",
            session,
            admission.on_close,
            owner,
        )
        del browser
        assert retained() is not None
        del admission
        gc.collect()
        assert retained() is None
        assert manager.get_session("s_target") is session
    finally:
        handle.close()
    assert manager.get_session("s_target") is None


def test_owner_close_serializes_with_native_terminal_notification() -> None:
    manager = _Manager()
    manager.ttl_seconds = None
    session = _Session()
    session.ttl_seconds = 60
    manager.sessions["s_target"] = session
    first_adapter, first_handle = _open(manager)
    second_adapter, second_handle = _open(manager)
    first_owner = first_adapter.claim_editor_lifetime(_context(manager))
    second_owner = second_adapter.claim_editor_lifetime(_context(manager))
    assert first_owner is not None and second_owner is not None
    first_started = Event()
    release_first = Event()
    callbacks: list[str] = []

    def close_first() -> None:
        first_started.set()
        assert release_first.wait(timeout=2)
        callbacks.append("first")

    assert lifetime_module._accept_studio_session(
        manager,
        "s_target",
        session,
        close_first,
        first_owner,
    )
    assert lifetime_module._accept_studio_session(
        manager,
        "s_target",
        session,
        (_second_callback := lambda: callbacks.append("second")),
        second_owner,
    )

    with ThreadPoolExecutor(max_workers=2) as executor:
        closing = executor.submit(first_handle.close)
        assert first_started.wait(timeout=2)
        manager.sessions.pop("s_target")
        notifying = executor.submit(
            lifetime_module._notify_closed_studio_session,
            session,
        )
        release_first.set()
        closing.result(timeout=2)
        notifying.result(timeout=2)

    assert callbacks == ["first", "second"]
    assert session not in lifetime_module._STUDIO_SESSION_LIFETIMES
    second_handle.close()
    assert callbacks == ["first", "second"]


def test_detached_notification_cannot_close_a_reaccepted_session() -> None:
    manager = _Manager()
    manager.ttl_seconds = None
    session = _Session()
    session.ttl_seconds = 60
    manager.sessions["s_target"] = session
    adapter, handle = _open(manager)
    owner = adapter.claim_editor_lifetime(_context(manager))
    assert owner is not None
    callbacks: list[object] = []
    assert lifetime_module._accept_studio_session(
        manager,
        "s_target",
        session,
        (_on_close := lambda: callbacks.append(session)),
        owner,
    )
    lifetime = lifetime_module._STUDIO_SESSION_LIFETIMES[session]
    manager.sessions.pop("s_target")
    observed_lock = _ObservedRLock()
    lifetime.settlement_lock = cast(Any, observed_lock)
    with ThreadPoolExecutor(max_workers=1) as executor:
        with observed_lock:
            notifying = executor.submit(
                lifetime_module._notify_closed_studio_session,
                session,
            )
            assert observed_lock.contended.wait(timeout=2)
            manager.sessions["s_target"] = session
            assert lifetime_module._accept_studio_session(
                manager,
                "s_target",
                session,
                (_on_close := lambda: callbacks.append(session)),
                owner,
            )
        notifying.result(timeout=2)

    assert manager.get_session("s_target") is session
    assert callbacks == []
    handle.close()
    assert callbacks == [session]


def test_session_lifetime_close_retries_after_manager_failure() -> None:
    class Manager(_Manager):
        fail_close = True

        def close_session(self, session_id: object) -> None:
            if self.fail_close:
                raise RuntimeError("close failed")
            super().close_session(session_id)

    async def exercise() -> None:
        original = SessionHandler._on_disconnect
        manager = Manager()
        manager.ttl_seconds = None
        session = _Session()
        session.ttl_seconds = 60
        manager.sessions["s_target"] = session
        callbacks: list[object] = []
        adapter, handle = _open(manager)
        patched = SessionHandler._on_disconnect
        owner = adapter.claim_editor_lifetime(_context(manager))
        assert owner is not None
        lifetime_module._accept_studio_session(
            manager,
            "s_target",
            session,
            (_on_close := lambda: callbacks.append(session)),
            owner,
        )

        with pytest.raises(RuntimeError, match="close failed"):
            handle.close()
        assert manager.get_session("s_target") is session
        assert session in lifetime_module._STUDIO_SESSION_LIFETIMES
        assert callbacks == []
        assert SessionHandler._on_disconnect is patched

        manager.fail_close = False
        handle.close()
        assert manager.get_session("s_target") is None
        assert session not in lifetime_module._STUDIO_SESSION_LIFETIMES
        assert callbacks == [session]
        assert SessionHandler._on_disconnect is original

    asyncio.run(exercise())


def test_session_lifetime_close_rejects_late_acquisitions() -> None:
    class Manager(_Manager):
        close_started = Event()
        release_close = Event()

        def close_session(self, session_id: object) -> None:
            self.close_started.set()
            assert self.release_close.wait(timeout=2)
            super().close_session(session_id)

    manager = Manager()
    manager.ttl_seconds = None
    session = _Session()
    session.ttl_seconds = 60
    manager.sessions["s_target"] = session
    adapter, handle = _open(manager)
    owner = adapter.claim_editor_lifetime(_context(manager))
    assert owner is not None
    other_adapter, other_handle = _open(manager)
    lifetime_module._accept_studio_session(
        manager,
        "s_target",
        session,
        lambda: None,
        owner,
    )
    late_manager = _Manager()

    with ThreadPoolExecutor(max_workers=1) as executor:
        closing = executor.submit(handle.close)
        assert manager.close_started.wait(timeout=2)
        assert not adapter.attach(_context(manager), "s_view01", "s_target")
        adapter.claim_editor_lifetime(_context(late_manager))
        assert late_manager not in cast(Any, adapter)._managers
        assert other_adapter.claim_editor_lifetime(_context(manager)) is None
        assert not lifetime_module._accept_studio_session(
            manager,
            "s_target",
            session,
            lambda: None,
            owner,
        )
        manager.release_close.set()
        closing.result(timeout=2)

    assert manager.get_session("s_target") is None
    assert other_adapter.claim_editor_lifetime(_context(manager)) is not None
    other_handle.close()


def test_final_global_close_rejects_a_concurrent_adapter_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release_started = Event()
    continue_release = Event()
    native_release = lifetime_module._release_studio_session_lifetimes

    def blocking_release(owned: object) -> None:
        release_started.set()
        assert continue_release.wait(timeout=2)
        native_release(cast(Any, owned))

    monkeypatch.setattr(
        lifetime_module,
        "_release_studio_session_lifetimes",
        blocking_release,
    )
    _adapter, handle = _open(_Manager())

    with ThreadPoolExecutor(max_workers=1) as executor:
        closing = executor.submit(handle.close)
        assert release_started.wait(timeout=2)
        with pytest.raises(RuntimeError, match="cleanup is in progress"):
            PrivateExistingSessionAttachment().open()
        continue_release.set()
        closing.result(timeout=2)


@pytest.mark.parametrize("created", [True, False])
def test_native_connector_rejects_a_lost_lifetime_owner(created: bool) -> None:
    class Manager(_Manager):
        ttl_seconds = None

    async def exercise() -> None:
        manager = Manager()

        class Session(_Session):
            def disconnect_consumer(self, consumer: Any) -> None:
                self.room.consumers.pop(consumer.consumer_id, None)

        session = Session()
        peer = SimpleNamespace(consumer_id="s_peer")
        consumer = SimpleNamespace(consumer_id="s_target")
        if not created:
            manager.sessions["s_kernel"] = session
            session.room.consumers["s_peer"] = peer
        clients = StudioClientRegistry()
        lease = await clients.bind_session("s_target", "browser-client-1234")
        assert lease is not None

        def reject_binding() -> None:
            clients.reject_session_binding(lease)

        admission = NativeSessionAdmission(
            expected_claim=None,
            file_key="notebook.py",
            mode="fresh",
            notebook="notebook.py",
            runtime_session_id="s_target",
            binding_current=lambda: lease.phase == "active",
            on_reject=reject_binding,
            on_close=lambda: None,
            lifetime_owner=object(),
        )
        connector = cast(
            Any,
            SimpleNamespace(
                manager=manager,
                handler=consumer,
                params=SimpleNamespace(
                    session_id="s_target",
                    file_key="notebook.py",
                    kiosk=False,
                ),
                connection=SimpleNamespace(
                    query_params=QueryParams(
                        {
                            STUDIO_CLIENT_QUERY_PARAM: "browser-client-1234",
                            SERVER_INSTANCE_QUERY_PARAM: server_instance_id("token"),
                        }
                    ),
                    scope={NATIVE_SESSION_ADMISSION_SCOPE_KEY: admission},
                ),
            ),
        )

        def connect(_connector: object) -> tuple[object, object]:
            if created:
                manager.sessions["s_target"] = session
            session.room.consumers["s_target"] = consumer
            return session, ConnectionType.NEW if created else ConnectionType.KIOSK

        guarded = existing_session_module._session_connect_replacement(connect)

        with pytest.raises(WebSocketDisconnect):
            guarded(connector)

        assert manager.get_session("s_target") is None
        if not created:
            assert manager.get_session("s_kernel") is session
            assert session.room.consumers == {"s_peer": peer}
        assert await clients.binding_for_client("browser-client-1234") is None
        assert admission.rejected
        await clients.close()

    asyncio.run(exercise())


def test_native_close_releases_a_live_binding_across_a_transport_gap() -> None:
    import gc
    from weakref import ref

    from marimo._session.events import SessionEventBus

    from ..server.test_editor_binding import (
        _CLIENT_ID,
        _LIFETIME_OWNER,
        _SESSION_ID,
        _bind,
        _request,
        _Sessions,
    )

    class Claim:
        pass

    class Manager:
        def __init__(self, claim: Claim) -> None:
            self.sessions = {_SESSION_ID: claim}
            self._event_bus = SessionEventBus()

        def close_session(self, session_id: str) -> None:
            self.sessions.pop(session_id, None)

    async def exercise() -> None:
        clients = StudioClientRegistry()
        sessions = _Sessions()
        claim = Claim()
        manager = Manager(claim)
        assert lifetime_module._open_studio_session_lifetimes()
        assert lifetime_module._track_manager_session_lifetimes(
            manager, _LIFETIME_OWNER
        )
        try:
            assert await clients.connect_stream(_CLIENT_ID, 1) is not None
            admission = await _bind(clients, sessions, _request())
            assert admission.on_accept is not None
            admission.on_accept(claim)
            assert admission.on_close is not None
            callback = ref(admission.on_close)
            assert lifetime_module._accept_studio_session(
                manager,
                _SESSION_ID,
                claim,
                admission.on_close,
                _LIFETIME_OWNER,
            )
            del admission
            gc.collect()
            assert callback() is not None
            assert await clients.session_for_client(_CLIENT_ID) == _SESSION_ID

            closed = asyncio.Event()
            unsubscribe = clients.subscribe(closed.set)
            manager.close_session(_SESSION_ID)
            await manager._event_bus.emit_session_closed(cast(Any, claim))
            await asyncio.wait_for(closed.wait(), timeout=1)
            unsubscribe()
            assert await clients.binding_for_client(_CLIENT_ID) is None
            gc.collect()
            assert callback() is None
        finally:
            await clients.close()
            lifetime_module._close_manager_session_lifetimes(manager, _LIFETIME_OWNER)
            lifetime_module._close_studio_session_lifetimes()

    asyncio.run(exercise())
