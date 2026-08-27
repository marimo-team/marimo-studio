from __future__ import annotations

import asyncio

import pytest
from marimo._code_mode.screenshot_meta import (
    SCREENSHOT_AUTH_TOKEN_KEY,
    SCREENSHOT_SERVER_URL_KEY,
)
from marimo._messaging.context import http_request_context
from marimo._runtime.commands import HTTPRequest
from marimo._types.encodable import Encodable

import marimo_studio.agent._client as agent_client
import marimo_studio.agent._transport as agent_transport
from marimo_studio._compat.code_mode import (
    STUDIO_NOTEBOOK_PATH_KEY,
    STUDIO_SESSION_ID_KEY,
    active_notebook,
    attach_code_mode_session,
    code_mode_connection,
)
from marimo_studio.agent._client import studio_server_connection
from marimo_studio.agent._protocol import ViewActivationRequest
from marimo_studio.errors import CapabilityInputError, ProtocolError


def _code_mode_request(
    *,
    meta: dict[str, Encodable],
    query_params: dict[str, list[str]] | None = None,
) -> HTTPRequest:
    return HTTPRequest(
        url={"path": "/api/kernel/execute"},
        base_url={"path": "/"},
        headers={},
        query_params=query_params or {},
        path_params={},
        cookies={},
        meta=meta,
        user={},
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


@pytest.mark.parametrize(
    ("url", "message"),
    (
        pytest.param(
            "https://studio.example.test/?access_token=embedded",
            "dedicated credential input",
            id="query",
        ),
        pytest.param(
            "https://user:secret@studio.example.test/",
            "dedicated credential input",
            id="userinfo",
        ),
        pytest.param(
            "https://studio.example.test/#access_token=secret",
            "dedicated credential input",
            id="fragment",
        ),
        pytest.param(
            "ftp://studio.example.test/",
            "must use http or https",
            id="scheme",
        ),
        pytest.param(
            "http://studio.example.test:invalid/",
            "server URL is invalid",
            id="port",
        ),
    ),
)
def test_server_connection_rejects_malformed_endpoints(
    url: str,
    message: str,
) -> None:
    with pytest.raises(ProtocolError, match=message):
        studio_server_connection(url)


def test_code_mode_connection_reads_callback_and_session_context() -> None:
    request = _code_mode_request(
        query_params={"file": ["analysis.py"]},
        meta={
            SCREENSHOT_SERVER_URL_KEY: "http://localhost:2718",
            SCREENSHOT_AUTH_TOKEN_KEY: "access-token",
            STUDIO_SESSION_ID_KEY: "s_123456",
        },
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
    request = _code_mode_request(
        query_params={"file": ["analysis.py"]},
        meta={
            SCREENSHOT_SERVER_URL_KEY: "http://localhost:2718",
            SCREENSHOT_AUTH_TOKEN_KEY: "access-token",
            STUDIO_SESSION_ID_KEY: "s_123456",
        },
    )
    requests: list[
        tuple[agent_transport.StudioServerConnection, str, float | None]
    ] = []

    async def send(connection, path, **kwargs):
        requests.append((connection, path, kwargs.get("timeout")))
        if path.endswith("/agent/connection"):
            return {
                "schema": 1,
                "notebook": str(notebook),
                "server_token": "server-token",
            }
        return {
            "schema": 2,
            "notebook": str(notebook),
            "view": "dashboard",
            "generation": 1,
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

    assert result.generation == 1
    assert [path for _, path, _timeout in requests] == [
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


def test_code_mode_scope_adds_notebook_and_session_without_mutating_request_meta(
    tmp_path,
) -> None:
    notebook = (tmp_path / "analysis.py").resolve()
    notebook.write_text("", encoding="utf-8")
    scope = {
        "type": "http",
        "headers": [(b"marimo-session-id", b"s_123456")],
        "meta": {"request-id": "abc"},
    }

    updated = attach_code_mode_session(scope, notebook)

    assert scope["meta"] == {"request-id": "abc"}
    assert updated["meta"] == {
        "request-id": "abc",
        STUDIO_NOTEBOOK_PATH_KEY: str(notebook),
        STUDIO_SESSION_ID_KEY: "s_123456",
    }


def test_active_notebook_reads_the_code_mode_request(tmp_path) -> None:
    notebook = (tmp_path / "analysis.py").resolve()
    notebook.write_text("", encoding="utf-8")
    request = _code_mode_request(
        meta={STUDIO_NOTEBOOK_PATH_KEY: str(notebook)},
    )

    with http_request_context(request):
        assert active_notebook() == notebook
