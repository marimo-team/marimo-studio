from __future__ import annotations

import asyncio
import threading

import pytest

import marimo_studio._browser_client.transport as browser_transport


def test_cancelled_server_request_closes_its_exchange(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = threading.Event()
    released = threading.Event()
    cancelled = threading.Event()

    def send(*_args: object, **_kwargs: object) -> bytes:
        started.set()
        released.wait(timeout=2)
        raise OSError

    def cancel(_exchange: object) -> None:
        cancelled.set()
        released.set()

    monkeypatch.setattr(browser_transport._HttpExchange, "send", send)
    monkeypatch.setattr(browser_transport._HttpExchange, "cancel", cancel)

    async def exercise() -> None:
        task = asyncio.create_task(
            browser_transport.request_json(
                browser_transport.StudioServerConnection("http://localhost:2718"),
                "/_marimo-studio/analyze",
            )
        )
        assert await asyncio.to_thread(started.wait, 1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert await asyncio.to_thread(cancelled.wait, 1)

    asyncio.run(exercise())


def test_server_request_enforces_one_wall_clock_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reading = threading.Event()
    closed = threading.Event()

    class FakeResponse:
        status = 200

        def read(self, _limit: int) -> bytes:
            reading.set()
            closed.wait(timeout=2)
            raise OSError("closed")

    class FakeConnection:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        def connect(self) -> None:
            pass

        def close(self) -> None:
            closed.set()

        def request(self, *_args: object, **_kwargs: object) -> None:
            pass

        def getresponse(self) -> FakeResponse:
            return FakeResponse()

    monkeypatch.setattr(browser_transport.http.client, "HTTPConnection", FakeConnection)

    async def exercise() -> None:
        with pytest.raises(browser_transport.AgentRequestError) as raised:
            await browser_transport.request_json(
                browser_transport.StudioServerConnection("http://localhost:2718"),
                "/_marimo-studio/analyze",
                timeout=0.02,
            )
        assert raised.value.code == "request-timeout"
        assert reading.is_set()
        assert closed.is_set()

    asyncio.run(exercise())


def test_server_request_deadline_does_not_wait_for_worker_shutdown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = threading.Event()
    released = threading.Event()
    finished = threading.Event()

    def send(*_args: object, **_kwargs: object) -> bytes:
        started.set()
        try:
            released.wait(timeout=2)
            return b"{}"
        finally:
            finished.set()

    monkeypatch.setattr(browser_transport._HttpExchange, "send", send)
    try:
        with pytest.raises(browser_transport.AgentRequestError) as raised:
            asyncio.run(
                browser_transport.request_json(
                    browser_transport.StudioServerConnection("http://localhost:2718"),
                    "/_marimo-studio/analyze",
                    timeout=0.02,
                )
            )
        assert started.is_set()
        assert not finished.is_set()
        assert raised.value.code == "request-timeout"
    finally:
        released.set()

    assert finished.wait(timeout=1)


def test_server_request_workers_are_bounded_and_capacity_recovers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = threading.Event()
    released = threading.Event()
    lock = threading.Lock()
    active = 0
    peak = 0

    def send(*_args: object, **_kwargs: object) -> bytes:
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
            if active == 2:
                started.set()
        released.wait(timeout=2)
        with lock:
            active -= 1
        return b"{}"

    monkeypatch.setattr(
        browser_transport, "_HTTP_WORKER_SLOTS", threading.BoundedSemaphore(2)
    )
    monkeypatch.setattr(browser_transport._HttpExchange, "send", send)

    async def exercise() -> None:
        connection = browser_transport.StudioServerConnection("http://localhost:2718")
        requests = tuple(
            asyncio.create_task(
                browser_transport.request_json(
                    connection,
                    "/_marimo-studio/analyze",
                    timeout=1,
                )
            )
            for _ in range(2)
        )
        assert await asyncio.to_thread(started.wait, 1)
        with pytest.raises(browser_transport.AgentRequestError) as raised:
            await browser_transport.request_json(
                connection,
                "/_marimo-studio/analyze",
                timeout=1,
            )
        assert raised.value.code == "request-capacity-exhausted"
        assert raised.value.status_code == 503

        released.set()
        assert await asyncio.gather(*requests) == [{}, {}]
        assert (
            await browser_transport.request_json(
                connection,
                "/_marimo-studio/analyze",
                timeout=1,
            )
            == {}
        )

    asyncio.run(exercise())
    assert peak == 2


def test_transport_cancellation_does_not_block_the_event_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requesting = threading.Event()
    closed = threading.Event()
    release_worker = threading.Event()
    worker_finished = threading.Event()

    class FakeConnection:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        def connect(self) -> None:
            pass

        def close(self) -> None:
            closed.set()

        def request(self, *_args: object, **_kwargs: object) -> None:
            requesting.set()
            closed.wait(timeout=2)
            release_worker.wait(timeout=2)
            worker_finished.set()
            raise OSError("closed")

        def getresponse(self) -> object:
            raise AssertionError("A cancelled request reached the response boundary")

    monkeypatch.setattr(browser_transport.http.client, "HTTPConnection", FakeConnection)

    async def exercise() -> None:
        task = asyncio.create_task(
            browser_transport.request_json(
                browser_transport.StudioServerConnection("http://localhost:2718"),
                "/_marimo-studio/analyze",
            )
        )
        assert await asyncio.to_thread(requesting.wait, 1)
        heartbeat = asyncio.create_task(asyncio.sleep(0))
        task.cancel()
        await asyncio.wait_for(heartbeat, 0.1)
        assert requesting.is_set()
        assert not worker_finished.is_set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert closed.is_set()
        assert not worker_finished.is_set()
        release_worker.set()
        assert await asyncio.to_thread(worker_finished.wait, 1)

    asyncio.run(exercise())


def test_server_authentication_error_preserves_its_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeResponse:
        status = 401

        def read(self, _limit: int) -> bytes:
            return (
                b'{"error":"authentication-required",'
                b'"message":"Authenticate with Marimo before using this route."}'
            )

    class FakeConnection:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        def connect(self) -> None:
            pass

        def close(self) -> None:
            pass

        def request(self, *_args: object, **_kwargs: object) -> None:
            pass

        def getresponse(self) -> FakeResponse:
            return FakeResponse()

    monkeypatch.setattr(browser_transport.http.client, "HTTPConnection", FakeConnection)

    with pytest.raises(browser_transport.AgentRequestError) as raised:
        asyncio.run(
            browser_transport.request_json(
                browser_transport.StudioServerConnection("http://localhost:2718"),
                "/_marimo-studio/agent/connection",
            )
        )

    assert raised.value.code == "authentication-required"


def test_cancelled_exchange_does_not_start_a_late_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requested = False

    class FakeConnection:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        def close(self) -> None:
            pass

        def request(self, *_args: object, **_kwargs: object) -> None:
            nonlocal requested
            requested = True

    monkeypatch.setattr(browser_transport.http.client, "HTTPConnection", FakeConnection)
    exchange = browser_transport._HttpExchange()
    exchange.cancel()

    with pytest.raises(browser_transport.AgentRequestError) as raised:
        exchange.send("http://localhost:2718", "GET", {}, None, 1)

    assert raised.value.code == "request-cancelled"
    assert requested is False


def test_cancelled_request_does_not_send_after_connection_finishes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connecting = threading.Event()
    connected = threading.Event()
    release = threading.Event()
    finished = threading.Event()
    requested = False

    class FakeConnection:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        def connect(self) -> None:
            connecting.set()
            release.wait(timeout=2)
            connected.set()

        def close(self) -> None:
            if connected.is_set():
                finished.set()

        def request(self, *_args: object, **_kwargs: object) -> None:
            nonlocal requested
            requested = True

        def getresponse(self) -> object:
            raise AssertionError("A cancelled request reached the response boundary")

    monkeypatch.setattr(browser_transport.http.client, "HTTPConnection", FakeConnection)

    async def exercise() -> None:
        task = asyncio.create_task(
            browser_transport.request_json(
                browser_transport.StudioServerConnection("http://localhost:2718"),
                "/_marimo-studio/analyze",
                method="POST",
            )
        )
        assert await asyncio.to_thread(connecting.wait, 1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        release.set()
        assert await asyncio.to_thread(finished.wait, 1)

    asyncio.run(exercise())

    assert requested is False
