"""Protect the mounted Studio query endpoint."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from starlette.testclient import TestClient

from marimo_studio._server.agent.clients import (
    QueryOperationClaim,
    QueryOperationStatus,
    StudioClientRegistry,
)

from ..app_helpers import configured as _configured
from ..app_helpers import edit_mode as _edit_mode
from ..app_helpers import marimo_app as _marimo_app
from ..app_helpers import session_manager as _session_manager


@dataclass(frozen=True)
class _QueryHTTP:
    app: Any
    token: str
    received: list[dict[str, str | list[str]]]


@pytest.fixture
def query_http(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> _QueryHTTP:
    studio = _configured(notebook_path)
    app = _marimo_app(studio.notebook)
    _edit_mode(app)
    received: list[dict[str, str | list[str]]] = []
    sessions = {
        "browser-client-1234": "s_123456",
        "browser-client-5678": "s_654321",
    }
    claimed_operations: set[tuple[str, str]] = set()

    async def session_for_client(
        _self: StudioClientRegistry,
        client_id: str,
    ) -> str | None:
        return sessions.get(client_id)

    async def claim_query_operation(
        _self: StudioClientRegistry,
        client_id: str,
        operation_id: str,
        expected_session_id: str,
        fingerprint: str,
        query_generation: int,
    ) -> QueryOperationClaim | None:
        if sessions.get(client_id) != expected_session_id:
            return None
        operation = (client_id, operation_id)
        status = (
            QueryOperationStatus.NEW
            if operation not in claimed_operations
            else QueryOperationStatus.COMMITTED
        )
        claimed_operations.add(operation)
        return QueryOperationClaim(
            client_id,
            expected_session_id,
            1,
            operation_id,
            fingerprint,
            query_generation,
            status,
        )

    async def commit_query_operation(
        _self: StudioClientRegistry,
        _claim: QueryOperationClaim,
    ) -> bool:
        return True

    async def acquire_query_mutation(
        _self: StudioClientRegistry,
        _claim: QueryOperationClaim,
    ) -> bool:
        return True

    async def finish_query_mutation(
        _self: StudioClientRegistry,
        _claim: QueryOperationClaim,
    ) -> None:
        return None

    async def sync_query(
        _host: object,
        _context: object,
        session_id: str,
        query: dict[str, str | list[str]],
        operation_id: str,
        **_metadata: int | float,
    ) -> None:
        received.append(
            {
                "session": session_id,
                "operation": operation_id,
                **query,
            }
        )

    monkeypatch.setattr(
        StudioClientRegistry,
        "session_for_client",
        session_for_client,
    )
    monkeypatch.setattr(
        StudioClientRegistry,
        "claim_query_operation",
        claim_query_operation,
    )
    monkeypatch.setattr(
        StudioClientRegistry,
        "commit_query_operation",
        commit_query_operation,
    )
    monkeypatch.setattr(
        StudioClientRegistry,
        "acquire_query_mutation",
        acquire_query_mutation,
    )
    monkeypatch.setattr(
        StudioClientRegistry,
        "finish_query_mutation",
        finish_query_mutation,
    )
    monkeypatch.setattr(
        "marimo_studio._compat.server.session_state.PrivateSessionState.exists",
        lambda _sessions, _context, session_id: session_id in sessions.values(),
    )
    monkeypatch.setattr(
        "marimo_studio._compat.kernel_values.host.PrivateKernelProjectionHost.sync_query",
        sync_query,
    )
    return _QueryHTTP(
        app,
        str(_session_manager(app).skew_protection_token),
        received,
    )


def _post_query(
    client: TestClient,
    query_http: _QueryHTTP,
    *,
    query: str,
    operation_id: str = "query-1",
    client_id: str = "browser-client-1234",
    write_generation: int = 0,
) -> Any:
    return client.post(
        "/_marimo-studio/query",
        headers={"Marimo-Server-Token": query_http.token},
        json={
            "clientId": client_id,
            "operationId": operation_id,
            "writeGeneration": write_generation,
            "query": query,
        },
    )


def test_query_http_preserves_multivalue_and_blank_values(
    query_http: _QueryHTTP,
) -> None:
    with TestClient(query_http.app) as client:
        response = _post_query(
            client,
            query_http,
            query="?region=emea&region=apac&empty=",
        )

    assert response.status_code == 202
    assert query_http.received == [
        {
            "session": "s_123456",
            "operation": "query-1",
            "region": ["emea", "apac"],
            "empty": "",
        }
    ]


def test_query_http_routes_each_client_to_its_bound_session(
    query_http: _QueryHTTP,
) -> None:
    with TestClient(query_http.app) as client:
        first = _post_query(client, query_http, query="?region=emea")
        second = _post_query(
            client,
            query_http,
            client_id="browser-client-5678",
            operation_id="query-2",
            query="?region=apac",
        )

    assert first.status_code == second.status_code == 202
    assert [(item["session"], item["region"]) for item in query_http.received] == [
        ("s_123456", "emea"),
        ("s_654321", "apac"),
    ]


def test_query_http_rejects_private_routing_keys(query_http: _QueryHTTP) -> None:
    with TestClient(query_http.app) as client:
        response = _post_query(
            client,
            query_http,
            query="?region=public&session_id=s_private",
        )

    assert response.status_code == 400
    assert response.json()["error"] == "invalid-query"
    assert query_http.received == []


def test_query_http_requires_edit_access(
    query_http: _QueryHTTP,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "marimo_studio._server.presentation.query_routes.has_edit_access",
        lambda _scope: False,
    )

    with TestClient(query_http.app) as client:
        response = _post_query(client, query_http, query="?region=private")

    assert response.status_code == 403
    assert response.json()["error"] == "edit-access-required"
    assert query_http.received == []


def test_query_http_retries_when_the_session_claim_is_unavailable(
    query_http: _QueryHTTP,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def reject_claim(
        _self: StudioClientRegistry,
        _client_id: str,
        _operation_id: str,
        expected_session_id: str,
        _fingerprint: str,
        _query_generation: int,
    ) -> None:
        assert expected_session_id == "s_123456"
        return None

    monkeypatch.setattr(
        StudioClientRegistry,
        "claim_query_operation",
        reject_claim,
    )

    with TestClient(query_http.app) as client:
        response = _post_query(client, query_http, query="?region=emea")

    assert response.status_code == 409
    assert response.json()["error"] == "query-session-unavailable"
    assert response.json()["transient"] is True
    assert query_http.received == []
