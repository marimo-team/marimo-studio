from __future__ import annotations

import asyncio
import threading
import time
from dataclasses import replace
from typing import cast

import pytest
from marimo._code_mode.screenshot_meta import (
    SCREENSHOT_AUTH_TOKEN_KEY,
    SCREENSHOT_SERVER_URL_KEY,
)
from marimo._messaging.context import http_request_context
from marimo._runtime.commands import HTTPRequest

import marimo_studio._agent_client as agent_client
import marimo_studio._agent_transport as agent_transport
from marimo_studio._agent_client import studio_server_connection
from marimo_studio._compat.code_mode import (
    STUDIO_SESSION_ID_KEY,
    attach_code_mode_session,
    code_mode_connection,
)
from marimo_studio.activation import ViewActivationRequest
from marimo_studio.agent_models import AnalysisReport, BrowserObservation
from marimo_studio.analysis import AnalysisRequest
from marimo_studio.errors import CapabilityInputError, ProtocolError

from .helpers import ready_runtime_status


def test_http_errors_preserve_structured_details() -> None:
    with pytest.raises(agent_transport.AgentRequestError) as raised:
        agent_transport._raise_response_error(
            404,
            b'{"error":"view-not-found","message":"missing",'
            b'"view":"missing","available_views":["dashboard"]}',
        )

    assert raised.value.diagnostic_details() == {
        "view": "missing",
        "available_views": ["dashboard"],
    }


def test_analysis_transport_budget_covers_runtime_and_browser_deadlines(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    notebook = tmp_path / "analysis.py"
    notebook.write_text("", encoding="utf-8")
    report = AnalysisReport(
        notebook=notebook,
        views=("dashboard",),
        runtime="server",
        revisions={"dashboard": "revision-1"},
        static_checks=(),
        runtime_checks=(),
        runtime_skipped=None,
        browser_observations=(),
        browser_required=False,
        actions=(),
    )
    captured: dict[str, object] = {}

    async def request(*_args, **kwargs):
        captured.update(kwargs)
        return report.to_dict()

    monkeypatch.setattr(agent_client, "request_json", request)

    asyncio.run(
        agent_client.request_analysis(
            agent_transport.StudioServerConnection(
                "http://localhost:2718",
                server_token="server-token",
            ),
            notebook,
            AnalysisRequest(
                view="dashboard",
                browser_timeout=20,
                runtime_timeout=75,
                require_browser=False,
            ),
        )
    )

    assert captured["timeout"] == 105.0
    body = captured["body"]
    assert isinstance(body, dict)
    assert cast(dict[str, object], body)["schema"] == 1
    assert cast(dict[str, object], body)["runtime_timeout"] == 75


def test_analysis_rejects_a_browser_policy_downgrade(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    notebook = (tmp_path / "analysis.py").resolve()
    report = AnalysisReport(
        notebook=notebook,
        views=("dashboard",),
        runtime="server",
        revisions={"dashboard": "revision-1"},
        static_checks=(),
        runtime_checks=(),
        runtime_skipped=None,
        browser_observations=(),
        browser_required=False,
        actions=(),
    )

    async def request(*_args: object, **_kwargs: object) -> dict[str, object]:
        return report.to_dict()

    monkeypatch.setattr(agent_client, "request_json", request)

    with pytest.raises(ProtocolError, match="analysis response"):
        asyncio.run(
            agent_client.request_analysis(
                agent_transport.StudioServerConnection(
                    "http://localhost:2718",
                    server_token="server-token",
                ),
                notebook,
                AnalysisRequest(view="dashboard", require_browser=True),
            )
        )


def test_observation_rejects_evidence_from_another_selected_browser(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    notebook = (tmp_path / "analysis.py").resolve()
    observation = BrowserObservation(
        view="dashboard",
        state="ready",
        runtime="server",
        revision="revision-1",
        client_id="other-browser",
        runtime_instance="runtime-instance",
        session_id="s_123456",
        request_id="request-dashboard",
        sequence=1,
        runtime_status=ready_runtime_status("dashboard", "revision-1"),
    )

    async def request(*_args: object, **_kwargs: object) -> dict[str, object]:
        return {
            "schema": 1,
            "notebook": str(notebook),
            "observations": [observation.to_dict()],
        }

    monkeypatch.setattr(agent_client, "request_json", request)

    with pytest.raises(ProtocolError, match="another browser"):
        asyncio.run(
            agent_client.observe_browser_views(
                agent_transport.StudioServerConnection(
                    "http://localhost:2718",
                    server_token="server-token",
                    browser_client="selected-browser",
                ),
                notebook,
                ("dashboard",),
                revisions={"dashboard": "revision-1"},
            )
        )


@pytest.mark.parametrize(
    ("observed_revision", "observed_runtime"),
    [
        ("wrong-revision", "server"),
        ("revision-1", "wasm"),
    ],
)
def test_observation_rejects_evidence_for_another_revision_or_runtime(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    observed_revision: str,
    observed_runtime: str,
) -> None:
    notebook = (tmp_path / "analysis.py").resolve()
    runtime_status = replace(
        ready_runtime_status("dashboard", observed_revision),
        runtime=observed_runtime,
    )
    observation = BrowserObservation(
        view="dashboard",
        state="ready",
        runtime=observed_runtime,
        revision=observed_revision,
        client_id="browser-client-1234",
        runtime_instance="runtime-instance",
        session_id="s_123456",
        request_id="request-dashboard",
        sequence=1,
        runtime_status=runtime_status,
    )

    async def request(*_args: object, **_kwargs: object) -> dict[str, object]:
        return {
            "schema": 1,
            "notebook": str(notebook),
            "observations": [observation.to_dict()],
        }

    monkeypatch.setattr(agent_client, "request_json", request)

    with pytest.raises(ProtocolError, match=r"another (revision|runtime)"):
        asyncio.run(
            agent_client.observe_browser_views(
                agent_transport.StudioServerConnection(
                    "http://localhost:2718",
                    server_token="server-token",
                    browser_client="browser-client-1234",
                ),
                notebook,
                ("dashboard",),
                revisions={"dashboard": "revision-1"},
                runtime="server",
            )
        )


def test_analysis_rejects_evidence_from_another_selected_browser(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    notebook = (tmp_path / "analysis.py").resolve()
    report = AnalysisReport(
        notebook=notebook,
        views=("dashboard",),
        runtime="server",
        revisions={"dashboard": "revision-1"},
        static_checks=(),
        runtime_checks=(),
        runtime_skipped=None,
        browser_observations=(
            BrowserObservation(
                view="dashboard",
                state="ready",
                runtime="server",
                revision="revision-1",
                client_id="other-browser",
                runtime_instance="runtime-instance",
                session_id="s_123456",
                request_id="request-dashboard",
                sequence=1,
                runtime_status=ready_runtime_status("dashboard", "revision-1"),
            ),
        ),
        browser_required=True,
        actions=(),
    )

    async def request(*_args: object, **_kwargs: object) -> dict[str, object]:
        return report.to_dict()

    monkeypatch.setattr(agent_client, "request_json", request)

    with pytest.raises(ProtocolError, match="another browser"):
        asyncio.run(
            agent_client.request_analysis(
                agent_transport.StudioServerConnection(
                    "http://localhost:2718",
                    server_token="server-token",
                    browser_client="selected-browser",
                ),
                notebook,
                AnalysisRequest(
                    view="dashboard",
                    browser_client="selected-browser",
                ),
            )
        )


def test_code_mode_analysis_rejects_evidence_from_another_session(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    notebook = (tmp_path / "analysis.py").resolve()
    report = AnalysisReport(
        notebook=notebook,
        views=("dashboard",),
        runtime="server",
        revisions={"dashboard": "revision-1"},
        static_checks=(),
        runtime_checks=(),
        runtime_skipped=None,
        browser_observations=(
            BrowserObservation(
                view="dashboard",
                state="ready",
                runtime="server",
                revision="revision-1",
                client_id="browser-client-1234",
                runtime_instance="runtime-instance",
                session_id="s_654321",
                request_id="request-dashboard",
                sequence=1,
            ),
        ),
        browser_required=True,
        actions=(),
    )

    async def request(*_args, **_kwargs):
        return report.to_dict()

    monkeypatch.setattr(agent_client, "request_json", request)

    with pytest.raises(ProtocolError, match="another session"):
        asyncio.run(
            agent_client.request_analysis(
                agent_transport.StudioServerConnection(
                    "http://localhost:2718",
                    server_token="server-token",
                    session_id="s_123456",
                ),
                notebook,
                AnalysisRequest(view="dashboard"),
            )
        )


def test_external_connection_negotiates_the_server_token(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    notebook = (tmp_path / "analysis.py").resolve()
    requests: list[tuple[agent_transport.StudioServerConnection, str]] = []

    async def request(connection, path, **_kwargs):
        requests.append((connection, path))
        if path.endswith("/agent/connection"):
            return {
                "schema": 1,
                "notebook": str(notebook),
                "server_token": "server-token",
            }
        return {
            "schema": 1,
            "notebook": str(notebook),
            "observations": [
                {
                    "view": "dashboard",
                    "runtime": "server",
                    "revision": "revision-1",
                    "state": "ready",
                    "diagnostics": [],
                    "client_id": "browser-client-1234",
                    "runtime_instance": "runtime-instance",
                    "session_id": "s_123456",
                    "request_id": "request-dashboard",
                    "sequence": 2,
                    "query": "",
                }
            ],
        }

    monkeypatch.setattr(agent_client, "request_json", request)

    observations = asyncio.run(
        agent_client.observe_browser_views(
            agent_transport.StudioServerConnection(
                "http://localhost:2718",
                auth_token="access-token",
            ),
            notebook,
            ("dashboard",),
            revisions={"dashboard": "revision-1"},
            runtime="server",
        )
    )

    assert observations[0].state == "ready"
    assert [path for _, path in requests] == [
        "/_marimo-studio/agent/connection",
        "/_marimo-studio/observations",
    ]
    assert requests[1][0].server_token == "server-token"


def test_server_connection_separates_credentials_and_notebook_routing() -> None:
    connection = studio_server_connection(
        "http://localhost:2718/base/?file=analysis.py&ignored=1",
        access_token="secret",
    )

    assert connection.server_url == "http://localhost:2718/base"
    assert connection.auth_token == "secret"
    assert connection.routing_query == (("file", "analysis.py"),)


def test_server_connection_rejects_query_credentials() -> None:
    with pytest.raises(ProtocolError, match="dedicated credential input"):
        studio_server_connection(
            "https://studio.example.test/?access_token=embedded",
        )


@pytest.mark.parametrize(
    "url",
    [
        "https://user@studio.example.test/",
        "https://user:secret@studio.example.test/",
    ],
)
def test_server_connection_rejects_userinfo_credentials(url: str) -> None:
    with pytest.raises(ProtocolError, match="dedicated credential input"):
        studio_server_connection(url)


def test_server_connection_rejects_url_fragments() -> None:
    with pytest.raises(ProtocolError, match="dedicated credential input"):
        studio_server_connection("https://studio.example.test/#access_token=secret")


def test_code_mode_connection_reads_callback_and_session_context() -> None:
    request = HTTPRequest(
        url={"path": "/api/kernel/execute"},
        base_url={"path": "/"},
        headers={},
        query_params={"file": ["analysis.py"]},
        path_params={},
        cookies={},
        meta={
            SCREENSHOT_SERVER_URL_KEY: "http://localhost:2718",
            SCREENSHOT_AUTH_TOKEN_KEY: "access-token",
            STUDIO_SESSION_ID_KEY: "s_123456",
        },
        user={},
    )

    with http_request_context(request):
        connection = code_mode_connection()

    assert connection.server_url == "http://localhost:2718"
    assert connection.auth_token == "access-token"
    assert connection.routing_query == (("file", "analysis.py"),)
    assert connection.server_token == ""
    assert connection.session_id == "s_123456"


def test_code_mode_request_negotiates_the_server_token(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    notebook = (tmp_path / "analysis.py").resolve()
    notebook.write_text("", encoding="utf-8")
    request = HTTPRequest(
        url={"path": "/api/kernel/execute"},
        base_url={"path": "/"},
        headers={},
        query_params={"file": ["analysis.py"]},
        path_params={},
        cookies={},
        meta={
            SCREENSHOT_SERVER_URL_KEY: "http://localhost:2718",
            SCREENSHOT_AUTH_TOKEN_KEY: "access-token",
            STUDIO_SESSION_ID_KEY: "s_123456",
        },
        user={},
    )
    requests: list[tuple[agent_transport.StudioServerConnection, str]] = []

    async def send(connection, path, **_kwargs):
        requests.append((connection, path))
        if path.endswith("/agent/connection"):
            return {
                "schema": 1,
                "notebook": str(notebook),
                "server_token": "server-token",
            }
        return {
            "schema": 1,
            "notebook": str(notebook),
            "view": "dashboard",
            "state": "active",
            "generation": 1,
            "transition": "in-place",
            "client_id": "browser-client-1234",
            "session_id": "s_123456",
        }

    monkeypatch.setattr(agent_client, "request_json", send)

    with http_request_context(request):
        result = asyncio.run(
            agent_client.request_view_activation(
                code_mode_connection(),
                notebook,
                ViewActivationRequest("dashboard"),
            )
        )

    assert result.state == "active"
    assert [path for _, path in requests] == [
        "/_marimo-studio/agent/connection",
        "/_marimo-studio/views/dashboard/activate",
    ]
    assert requests[0][0].server_token == ""
    assert requests[1][0].server_token == "server-token"
    assert requests[1][0].session_id == "s_123456"


def test_activation_rejects_mixed_selectors_before_token_negotiation(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    notebook = (tmp_path / "analysis.py").resolve()
    requested = False

    async def request(*_args: object, **_kwargs: object) -> dict[str, object]:
        nonlocal requested
        requested = True
        return {}

    monkeypatch.setattr(agent_client, "request_json", request)

    with pytest.raises(CapabilityInputError, match="cannot select another"):
        asyncio.run(
            agent_client.request_view_activation(
                agent_transport.StudioServerConnection(
                    "http://localhost:2718",
                    session_id="s_123456",
                ),
                notebook,
                ViewActivationRequest(
                    "dashboard",
                    browser_client="browser-client-1234",
                ),
            )
        )

    assert requested is False


def test_external_activation_rejects_a_reload_result(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    notebook = (tmp_path / "analysis.py").resolve()

    async def request(*_args: object, **_kwargs: object) -> dict[str, object]:
        return {
            "schema": 1,
            "notebook": str(notebook),
            "view": "dashboard",
            "state": "reload-requested",
            "generation": 1,
            "transition": "reload",
            "session_id": "s_123456",
        }

    monkeypatch.setattr(agent_client, "request_json", request)

    with pytest.raises(ProtocolError, match="cannot request a page reload"):
        asyncio.run(
            agent_client.request_view_activation(
                agent_transport.StudioServerConnection(
                    "http://localhost:2718",
                    server_token="server-token",
                ),
                notebook,
                ViewActivationRequest("dashboard"),
            )
        )


def test_code_mode_scope_adds_session_without_mutating_request_meta() -> None:
    scope = {
        "type": "http",
        "headers": [(b"marimo-session-id", b"s_123456")],
        "meta": {"request-id": "abc"},
    }

    updated = attach_code_mode_session(scope)

    assert scope["meta"] == {"request-id": "abc"}
    assert updated["meta"] == {
        "request-id": "abc",
        STUDIO_SESSION_ID_KEY: "s_123456",
    }


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

    monkeypatch.setattr(agent_transport._HttpExchange, "send", send)
    monkeypatch.setattr(agent_transport._HttpExchange, "cancel", cancel)

    async def exercise() -> None:
        task = asyncio.create_task(
            agent_transport.request_json(
                agent_transport.StudioServerConnection("http://localhost:2718"),
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

    monkeypatch.setattr(agent_transport.http.client, "HTTPConnection", FakeConnection)

    async def exercise() -> None:
        with pytest.raises(agent_transport.AgentRequestError) as raised:
            await agent_transport.request_json(
                agent_transport.StudioServerConnection("http://localhost:2718"),
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

    def send(*_args: object, **_kwargs: object) -> bytes:
        started.set()
        released.wait(timeout=2)
        return b"{}"

    monkeypatch.setattr(agent_transport._HttpExchange, "send", send)
    before = time.monotonic()
    try:
        with pytest.raises(agent_transport.AgentRequestError) as raised:
            asyncio.run(
                agent_transport.request_json(
                    agent_transport.StudioServerConnection("http://localhost:2718"),
                    "/_marimo-studio/analyze",
                    timeout=0.02,
                )
            )
    finally:
        released.set()

    assert started.is_set()
    assert raised.value.code == "request-timeout"
    assert time.monotonic() - before < 0.2


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
        agent_transport, "_HTTP_WORKER_SLOTS", threading.BoundedSemaphore(2)
    )
    monkeypatch.setattr(agent_transport._HttpExchange, "send", send)

    async def exercise() -> None:
        connection = agent_transport.StudioServerConnection("http://localhost:2718")
        requests = tuple(
            asyncio.create_task(
                agent_transport.request_json(
                    connection,
                    "/_marimo-studio/analyze",
                    timeout=1,
                )
            )
            for _ in range(2)
        )
        assert await asyncio.to_thread(started.wait, 1)
        with pytest.raises(agent_transport.AgentRequestError) as raised:
            await agent_transport.request_json(
                connection,
                "/_marimo-studio/analyze",
                timeout=1,
            )
        assert raised.value.code == "request-capacity-exhausted"
        assert raised.value.status_code == 503

        released.set()
        assert await asyncio.gather(*requests) == [{}, {}]
        assert (
            await agent_transport.request_json(
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
            raise OSError("closed")

        def getresponse(self) -> object:
            raise AssertionError("A cancelled request reached the response boundary")

    monkeypatch.setattr(agent_transport.http.client, "HTTPConnection", FakeConnection)

    async def exercise() -> None:
        task = asyncio.create_task(
            agent_transport.request_json(
                agent_transport.StudioServerConnection("http://localhost:2718"),
                "/_marimo-studio/analyze",
            )
        )
        assert await asyncio.to_thread(requesting.wait, 1)
        heartbeat = asyncio.create_task(asyncio.sleep(0))
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await asyncio.wait_for(heartbeat, 0.1)
        assert closed.is_set()

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

    monkeypatch.setattr(agent_transport.http.client, "HTTPConnection", FakeConnection)

    with pytest.raises(agent_transport.AgentRequestError) as raised:
        asyncio.run(
            agent_transport.request_json(
                agent_transport.StudioServerConnection("http://localhost:2718"),
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

    monkeypatch.setattr(agent_transport.http.client, "HTTPConnection", FakeConnection)
    exchange = agent_transport._HttpExchange()
    exchange.cancel()

    with pytest.raises(agent_transport.AgentRequestError) as raised:
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

    monkeypatch.setattr(agent_transport.http.client, "HTTPConnection", FakeConnection)

    async def exercise() -> None:
        task = asyncio.create_task(
            agent_transport.request_json(
                agent_transport.StudioServerConnection("http://localhost:2718"),
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
