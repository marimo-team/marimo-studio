from __future__ import annotations

from marimo._code_mode.screenshot_meta import (
    SCREENSHOT_AUTH_TOKEN_KEY,
    SCREENSHOT_SERVER_URL_KEY,
)
from marimo._messaging.context import http_request_context
from marimo._runtime.commands import HTTPRequest

from marimo_studio._agent_client import studio_server_connection
from marimo_studio._compat.code_mode import (
    STUDIO_SERVER_TOKEN_KEY,
    attach_code_mode_server_token,
    code_mode_connection,
)


def test_server_connection_separates_credentials_and_notebook_routing() -> None:
    connection = studio_server_connection(
        "http://localhost:2718/base/?access_token=secret&file=analysis.py&ignored=1"
    )

    assert connection.server_url == "http://localhost:2718/base"
    assert connection.auth_token == "secret"
    assert connection.routing_query == (("file", "analysis.py"),)


def test_explicit_access_token_takes_precedence() -> None:
    connection = studio_server_connection(
        "https://studio.example.test/?access_token=embedded",
        access_token="explicit",
    )

    assert connection.auth_token == "explicit"
    assert "access_token" not in connection.server_url


def test_code_mode_connection_reads_studio_callback_credentials() -> None:
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
            STUDIO_SERVER_TOKEN_KEY: "server-token",
        },
        user={},
    )

    with http_request_context(request):
        connection = code_mode_connection()

    assert connection.server_url == "http://localhost:2718"
    assert connection.auth_token == "access-token"
    assert connection.routing_query == (("file", "analysis.py"),)
    assert connection.server_token == "server-token"


def test_code_mode_scope_adds_server_token_without_mutating_request_meta() -> None:
    scope = {"type": "http", "meta": {"request-id": "abc"}}

    updated = attach_code_mode_server_token(scope, "server-token")

    assert scope["meta"] == {"request-id": "abc"}
    assert updated["meta"] == {
        "request-id": "abc",
        STUDIO_SERVER_TOKEN_KEY: "server-token",
    }
