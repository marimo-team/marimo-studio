"""Protect query application, idempotency, and request cancellation."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from starlette.requests import Request

from marimo_studio._server.agent.clients import (
    QueryOperationClaim,
    StudioClientRegistry,
)
from marimo_studio._server.ports import SessionState
from marimo_studio._server.presentation.ports import (
    KernelProjectionHost,
    QuerySyncUnavailable,
)
from marimo_studio._server.presentation.query_routes import query_response
from marimo_studio._server.records import ServerContext

from ..client_test_support import bind_native_session


def _request(
    query: str,
    operation_id: str = "query-1",
    write_generation: object = 0,
) -> Request:
    payload = json.dumps(
        {
            "clientId": "browser-client-1234",
            "operationId": operation_id,
            "query": query,
            "writeGeneration": write_generation,
        }
    ).encode()
    sent = False

    async def receive() -> dict[str, Any]:
        nonlocal sent
        if not sent:
            sent = True
            return {"type": "http.request", "body": payload, "more_body": False}
        return {"type": "http.disconnect"}

    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": "/_marimo-studio/query",
            "raw_path": b"/_marimo-studio/query",
            "query_string": b"",
            "headers": [
                (b"content-length", str(len(payload)).encode()),
                (b"marimo-server-token", b"server-token"),
            ],
            "client": ("127.0.0.1", 1),
            "server": ("127.0.0.1", 2),
            "root_path": "",
            "auth": SimpleNamespace(scopes=("edit",)),
        },
        receive,
    )


def _context() -> ServerContext:
    return cast(
        ServerContext,
        SimpleNamespace(
            file_key="notebook.py",
            mode="edit",
            server_token="server-token",
            notebook=Path("/workspace/notebook.py"),
        ),
    )


class _Sessions:
    claim_value = object()

    @staticmethod
    def exists(_context: ServerContext, session_id: str) -> bool:
        return session_id == "s_123456"

    @classmethod
    def claim(cls, _context: ServerContext, session_id: str) -> object | None:
        return cls.claim_value if session_id == "s_123456" else None


class _RecordingClients(StudioClientRegistry):
    def __init__(self) -> None:
        super().__init__()
        self.deferred: list[asyncio.Task[None]] = []

    def defer_query_mutation(
        self,
        claim: QueryOperationClaim,
        terminal: Awaitable[object],
    ) -> asyncio.Task[None] | None:
        task = super().defer_query_mutation(claim, terminal)
        if task is not None:
            self.deferred.append(task)
        return task


@pytest.mark.parametrize("generation", [-1, True, 9_007_199_254_740_992, "1"])
def test_query_rejects_an_invalid_write_generation(generation: object) -> None:
    async def exercise() -> None:
        clients = StudioClientRegistry()
        response = await query_response(
            _request("?region=emea", write_generation=generation),
            _context(),
            clients,
            cast(SessionState, _Sessions()),
            cast(KernelProjectionHost, object()),
        )

        assert response.status_code == 400
        assert json.loads(bytes(response.body))["error"] == "invalid-query"
        await clients.close()

    asyncio.run(exercise())


def test_query_retries_after_kernel_failure_and_commits_once() -> None:
    class Projections:
        def __init__(self) -> None:
            self.calls: list[tuple[dict[str, str | list[str]], str, int, int]] = []

        async def sync_query(
            self,
            _context: ServerContext,
            _session_id: str,
            query: dict[str, str | list[str]],
            operation_id: str,
            *,
            binding_generation: int,
            query_generation: int,
            deadline: float,
        ) -> None:
            self.calls.append(
                (query, operation_id, binding_generation, query_generation)
            )
            if len(self.calls) == 1:
                raise QuerySyncUnavailable("kernel function failed")

    async def exercise() -> None:
        clients = StudioClientRegistry()
        assert await clients.connect_stream("browser-client-1234", 1)
        await bind_native_session(clients, "s_123456", "browser-client-1234")
        projections = Projections()

        failed = await query_response(
            _request("?region=emea"),
            _context(),
            clients,
            cast(SessionState, _Sessions()),
            cast(KernelProjectionHost, projections),
        )
        applied = await query_response(
            _request("?region=emea"),
            _context(),
            clients,
            cast(SessionState, _Sessions()),
            cast(KernelProjectionHost, projections),
        )
        duplicate = await query_response(
            _request("?region=emea"),
            _context(),
            clients,
            cast(SessionState, _Sessions()),
            cast(KernelProjectionHost, projections),
        )
        conflict = await query_response(
            _request("?region=apac"),
            _context(),
            clients,
            cast(SessionState, _Sessions()),
            cast(KernelProjectionHost, projections),
        )

        assert failed.status_code == 409
        assert applied.status_code == 202
        assert duplicate.status_code == 202
        assert conflict.status_code == 409
        assert json.loads(bytes(conflict.body))["error"] == "query-operation-conflict"
        assert projections.calls == [
            ({"region": "emea"}, "query-1", 1, 0),
            ({"region": "emea"}, "query-1", 1, 0),
        ]
        await clients.close()

    asyncio.run(exercise())


def test_delayed_lower_generation_never_reaches_the_kernel() -> None:
    class Projections:
        def __init__(self) -> None:
            self.query: dict[str, str | list[str]] = {}
            self.calls: list[tuple[str, int, int]] = []

        async def sync_query(
            self,
            _context: ServerContext,
            _session_id: str,
            query: dict[str, str | list[str]],
            operation_id: str,
            *,
            binding_generation: int,
            query_generation: int,
            deadline: float,
        ) -> None:
            self.calls.append((operation_id, binding_generation, query_generation))
            self.query = query

    async def exercise() -> None:
        clients = StudioClientRegistry()
        assert await clients.connect_stream("browser-client-1234", 1)
        await bind_native_session(clients, "s_123456", "browser-client-1234")
        projections = Projections()

        current = await query_response(
            _request("?region=current", "query-current", 2),
            _context(),
            clients,
            cast(SessionState, _Sessions()),
            cast(KernelProjectionHost, projections),
        )
        delayed = await query_response(
            _request("?region=stale", "query-stale", 1),
            _context(),
            clients,
            cast(SessionState, _Sessions()),
            cast(KernelProjectionHost, projections),
        )
        retry = await query_response(
            _request("?region=current", "query-current", 2),
            _context(),
            clients,
            cast(SessionState, _Sessions()),
            cast(KernelProjectionHost, projections),
        )

        assert current.status_code == delayed.status_code == retry.status_code == 202
        assert projections.query == {"region": "current"}
        assert projections.calls == [("query-current", 1, 2)]
        await clients.close()

    asyncio.run(exercise())


def test_query_fence_survives_repeated_request_cancellation() -> None:
    class Projections:
        started = asyncio.Event()
        release = asyncio.Event()

        async def sync_query(self, *_args: object, **_kwargs: object) -> None:
            self.started.set()
            await self.release.wait()

    async def exercise() -> None:
        clients = StudioClientRegistry()
        assert await clients.connect_stream("browser-client-1234", 1)
        await bind_native_session(clients, "s_123456", "browser-client-1234")
        projections = Projections()
        response = asyncio.create_task(
            query_response(
                _request("?region=emea"),
                _context(),
                clients,
                cast(SessionState, _Sessions()),
                cast(KernelProjectionHost, projections),
            )
        )
        await projections.started.wait()
        response.cancel()
        response.cancel()
        assert response.cancelling() == 2
        checkpoint = asyncio.Event()
        asyncio.get_running_loop().call_soon(checkpoint.set)
        await asyncio.wait_for(checkpoint.wait(), timeout=1)
        assert not response.done()
        pending = await query_response(
            _request("?region=emea"),
            _context(),
            clients,
            cast(SessionState, _Sessions()),
            cast(KernelProjectionHost, projections),
        )
        assert pending.status_code == 409
        assert json.loads(bytes(pending.body))["error"] == "query-operation-pending"

        projections.release.set()
        with pytest.raises(asyncio.CancelledError):
            await response
        committed = await query_response(
            _request("?region=emea"),
            _context(),
            clients,
            cast(SessionState, _Sessions()),
            cast(KernelProjectionHost, projections),
        )
        assert committed.status_code == 202
        await clients.close()

    asyncio.run(exercise())


def test_query_timeout_preserves_the_live_session_until_kernel_terminal() -> None:
    class Projections:
        terminal: asyncio.Future[object] | None = None
        calls = 0

        async def sync_query(self, *_args: object, **_kwargs: object) -> None:
            self.calls += 1
            if self.calls > 1:
                return
            self.terminal = asyncio.get_running_loop().create_future()
            raise QuerySyncUnavailable(
                "kernel acknowledgement timed out",
                terminal=self.terminal,
            )

    async def exercise() -> None:
        clients = _RecordingClients()
        assert await clients.connect_stream("browser-client-1234", 1)
        await bind_native_session(clients, "s_123456", "browser-client-1234")
        projections = Projections()

        response = await query_response(
            _request("?region=emea", "query-1", 0),
            _context(),
            clients,
            cast(SessionState, _Sessions()),
            cast(KernelProjectionHost, projections),
        )
        pending = await query_response(
            _request("?region=emea", "query-1", 0),
            _context(),
            clients,
            cast(SessionState, _Sessions()),
            cast(KernelProjectionHost, projections),
        )
        assert response.status_code == 409
        assert pending.status_code == 409
        assert json.loads(bytes(pending.body))["error"] == "query-operation-pending"
        assert projections.terminal is not None
        assert not projections.terminal.done()
        assert await clients.session_for_client("browser-client-1234") == "s_123456"
        projections.terminal.set_result({"status": "expired"})
        await clients.deferred[-1]
        retry = await query_response(
            _request("?region=emea", "query-1", 0),
            _context(),
            clients,
            cast(SessionState, _Sessions()),
            cast(KernelProjectionHost, projections),
        )
        assert retry.status_code == 202
        assert projections.calls == 2
        await clients.close()

    asyncio.run(exercise())


def test_cancelled_request_transfers_its_fence_to_late_terminal() -> None:
    class Projections:
        started = asyncio.Event()
        timeout = asyncio.Event()
        terminal: asyncio.Future[object] | None = None

        async def sync_query(self, *_args: object, **_kwargs: object) -> None:
            self.started.set()
            await self.timeout.wait()
            self.terminal = asyncio.get_running_loop().create_future()
            raise QuerySyncUnavailable("kernel timeout", terminal=self.terminal)

    async def exercise() -> None:
        clients = _RecordingClients()
        assert await clients.connect_stream("browser-client-1234", 1)
        await bind_native_session(clients, "s_123456", "browser-client-1234")
        projections = Projections()
        response = asyncio.create_task(
            query_response(
                _request("?region=emea", "query-1", 0),
                _context(),
                clients,
                cast(SessionState, _Sessions()),
                cast(KernelProjectionHost, projections),
            )
        )
        await projections.started.wait()
        response.cancel()
        projections.timeout.set()

        with pytest.raises(asyncio.CancelledError):
            await response
        pending = await query_response(
            _request("?region=emea", "query-1", 0),
            _context(),
            clients,
            cast(SessionState, _Sessions()),
            cast(KernelProjectionHost, projections),
        )
        assert pending.status_code == 409
        assert json.loads(bytes(pending.body))["error"] == "query-operation-pending"
        assert projections.terminal is not None
        projections.terminal.set_result({"status": "applied"})
        await clients.deferred[-1]
        committed = await query_response(
            _request("?region=emea", "query-1", 0),
            _context(),
            clients,
            cast(SessionState, _Sessions()),
            cast(KernelProjectionHost, projections),
        )
        assert committed.status_code == 202
        await clients.close()

    asyncio.run(exercise())
