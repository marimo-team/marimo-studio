from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from starlette.testclient import TestClient

import marimo_studio._server.request_body as request_body_module

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


def _agent_response(
    notebook_path: Path, path: str, *, method: str = "POST", **kwargs: Any
):
    server = agent_edit_server(notebook_path)
    with TestClient(server.app) as client:
        return client.request(method, path, headers=server.headers, **kwargs)


def test_an_unregistered_client_handoff_explains_how_to_recover(
    notebook_path: Path,
) -> None:
    response = _agent_response(
        notebook_path,
        "/_marimo-studio/active-view-handoffs/handoff-operation-1",
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
            "Studio could not hand off the active view for this browser client."
        ),
        "hint": (
            "Reconnect the browser, confirm its active view, then retry the switch."
        ),
    }


@pytest.mark.parametrize(
    "case",
    (
        pytest.param(
            "digits",
            marks=pytest.mark.skipif(
                not 0 < getattr(sys, "get_int_max_str_digits", lambda: 0)() <= 5000,
                reason="json.loads limits integer digits from Python 3.10.7",
            ),
        ),
        "recursion",
    ),
    ids=("digit-limit", "recursion-limit"),
)
def test_json_beyond_the_decoder_limits_is_invalid_json(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    case: str,
) -> None:
    if case == "recursion":
        # The decoder's nesting limit depends on the interpreter and its C stack.
        # Python 3.14 parses 20,000 levels, more than this route's body limit
        # holds, so the decoder raises its RecursionError directly here.
        def exceed_recursion_limit(_source: str) -> object:
            raise RecursionError("maximum recursion depth exceeded")

        monkeypatch.setattr(
            request_body_module,
            "json",
            SimpleNamespace(loads=exceed_recursion_limit),
        )
        body = b"[[[0]]]"
    else:
        body = b'{"writeGeneration":' + b"9" * 5000 + b"}"
    response = _agent_response(notebook_path, "/_marimo-studio/views", content=body)

    assert response.status_code == 400
    assert response.json()["error"] == "invalid-json"


def test_a_query_with_an_unpaired_surrogate_is_an_invalid_query(
    notebook_path: Path,
) -> None:
    response = _agent_response(
        notebook_path,
        "/_marimo-studio/query",
        content=(
            b'{"clientId": "browser-client-1234", "operationId": "op-123", '
            b'"query": "?q=\\ud800", "writeGeneration": 1}'
        ),
    )

    assert response.status_code == 400
    assert response.json()["error"] == "invalid-query"


def test_oversized_decimal_identifiers_are_client_errors(notebook_path: Path) -> None:
    digits = "9" * 5000
    activation = _agent_response(
        notebook_path,
        "/_marimo-studio/activations/" + digits + "/ack",
        content=b"{}",
    )
    preview = _agent_response(
        notebook_path,
        "/dashboard/",
        method="GET",
        params={
            "marimo_studio_lifecycle": digits,
            "marimo_studio_client": "browser-client-1234",
        },
    )

    assert activation.status_code == 404
    assert preview.status_code < 500
