from __future__ import annotations

import sys
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from ..agent_support import agent_edit_server


def test_authenticated_agent_connection_returns_the_mutation_token(
    notebook_path: Path,
) -> None:
    server = agent_edit_server(notebook_path, token="test-token")

    with TestClient(server.app) as client:
        missing = client.get(
            "/_marimo-studio/agent/connection",
            headers={"Accept": "application/json"},
            follow_redirects=False,
        )
        invalid = client.get(
            "/_marimo-studio/agent/connection",
            headers={
                "Accept": "application/json",
                "Authorization": "Bearer invalid-token",
            },
            follow_redirects=False,
        )
        response = client.get(
            "/_marimo-studio/agent/connection",
            headers={
                "Accept": "application/json",
                "Authorization": "Bearer test-token",
            },
        )

    assert missing.status_code == 401
    assert missing.json()["error"] == "authentication-required"
    assert invalid.status_code == 401
    assert invalid.json()["error"] == "authentication-required"
    assert response.status_code == 200
    assert response.json() == {
        "schema": 1,
        "notebook": str(server.studio.notebook),
        "server_token": server.headers["Marimo-Server-Token"],
    }


def test_show_http_rejects_mixed_session_and_browser_selectors(
    notebook_path: Path,
) -> None:
    server = agent_edit_server(notebook_path)

    with TestClient(server.app) as client:
        mixed_activation = client.patch(
            "/_marimo-studio/views/dashboard/show",
            headers={**server.headers, "Marimo-Session-Id": "s_123456"},
            json={"schema": 1, "browser_client": "browser-client-1234"},
        )

    assert mixed_activation.status_code == 400
    assert mixed_activation.json()["error"] == "invalid-show-request"
    assert mixed_activation.json()["field"] == "browser_client"


def test_browser_mutation_http_rejects_noncanonical_records(
    notebook_path: Path,
) -> None:
    server = agent_edit_server(notebook_path)
    cases = (
        (
            "PATCH",
            "/_marimo-studio/views/dashboard/show",
            {},
            "invalid-show-request",
            "request",
        ),
        (
            "POST",
            "/_marimo-studio/activations/1/ack",
            {
                "schema": True,
                "clientId": "browser-client-1234",
                "view": "dashboard",
            },
            "invalid-activation-ack",
            None,
        ),
        (
            "POST",
            "/_marimo-studio/active-view-handoffs/handoff-operation-1",
            {
                "schema": True,
                "clientId": "browser-client-1234",
                "fromView": "dashboard",
                "toView": "report",
            },
            "invalid-active-view-handoff",
            None,
        ),
    )

    with TestClient(server.app) as client:
        for method, path, payload, error, field in cases:
            response = client.request(
                method,
                path,
                headers=server.headers,
                json=payload,
            )
            assert response.status_code == 400, path
            assert response.json()["error"] == error, path
            if field is not None:
                assert response.json()["field"] == field, path


def test_a_refused_active_view_handoff_explains_the_conflict(
    notebook_path: Path,
) -> None:
    server = agent_edit_server(notebook_path)

    with TestClient(server.app) as client:
        response = client.post(
            "/_marimo-studio/active-view-handoffs/handoff-operation-1",
            headers=server.headers,
            json={
                "schema": 1,
                "clientId": "browser-client-1234",
                "fromView": "dashboard",
                "toView": "executive",
            },
        )

    assert response.status_code == 409
    assert response.json() == {
        "error": "active-view-handoff-refused",
        "message": (
            "Studio could not hand off the active view because this browser "
            "is already switching views or handling an agent request."
        ),
        "hint": "Wait for that to finish, then switch views again.",
    }


@pytest.mark.parametrize(
    "body",
    [
        pytest.param(
            b'{"writeGeneration":' + b"9" * 5000 + b"}",
            id="oversized-integer",
            marks=pytest.mark.skipif(
                not 0 < getattr(sys, "get_int_max_str_digits", lambda: 0)() <= 5000,
                reason="json.loads limits integer digits from Python 3.10.7",
            ),
        ),
        pytest.param(b"[" * 4096 + b"0" + b"]" * 4096, id="deep-nesting"),
    ],
)
def test_json_beyond_the_decoder_limits_is_invalid_json(
    notebook_path: Path,
    body: bytes,
) -> None:
    server = agent_edit_server(notebook_path)

    with TestClient(server.app) as client:
        response = client.post(
            "/_marimo-studio/views", content=body, headers=server.headers
        )

    assert response.status_code == 400
    assert response.json()["error"] == "invalid-json"


def test_a_query_with_an_unpaired_surrogate_is_an_invalid_query(
    notebook_path: Path,
) -> None:
    server = agent_edit_server(notebook_path)

    with TestClient(server.app) as client:
        response = client.post(
            "/_marimo-studio/query",
            headers=server.headers,
            content=(
                b'{"clientId": "browser-client-1234", "operationId": "op-123", '
                b'"query": "?q=\\ud800", "writeGeneration": 1}'
            ),
        )

    assert response.status_code == 400
    assert response.json()["error"] == "invalid-query"


def test_oversized_decimal_identifiers_are_client_errors(notebook_path: Path) -> None:
    server = agent_edit_server(notebook_path)

    with TestClient(server.app) as client:
        activation = client.post(
            "/_marimo-studio/activations/" + "9" * 5000 + "/ack",
            content=b"{}",
            headers=server.headers,
        )
        preview = client.get(
            "/dashboard/",
            params={
                "marimo_studio_lifecycle": "9" * 5000,
                "marimo_studio_client": "browser-client-1234",
            },
        )

    assert activation.status_code == 404
    assert preview.status_code < 500
