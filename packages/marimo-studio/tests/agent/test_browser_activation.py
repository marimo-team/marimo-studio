from __future__ import annotations

from pathlib import Path

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
