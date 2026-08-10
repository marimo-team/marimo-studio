from __future__ import annotations

from marimo_studio._agent_client import studio_server_connection


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
