from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

import pytest
from starlette.types import ASGIApp, Message, Scope

import marimo_studio._compat.server.document_transaction as transaction_module
from marimo_studio._compat.server.document_transaction import (
    DOCUMENT_CHANGED_HEADER,
    DOCUMENT_OPERATION_HEADER,
    PrivateDocumentTransactionEvidence,
)
from marimo_studio.errors import ProtocolError

from ..async_test_support import wait_for_event


@dataclass
class _Cell:
    id: str
    code: str
    name: str = "cell"
    config: Any = None

    def __post_init__(self) -> None:
        if self.config is None:
            self.config = SimpleNamespace(column=None, disabled=False, hide_code=False)


class _Document:
    def __init__(self, code: str = "value = 1") -> None:
        self.cells = [_Cell("cell-1", code)]


class _Session:
    def __init__(self, code: str = "value = 1") -> None:
        self.document = _Document(code)


def _scope(
    operation: str | None = "operation-0000001",
    session_id: str = "s_document",
) -> Scope:
    headers = [(b"marimo-session-id", session_id.encode())]
    if operation is not None:
        headers.append((DOCUMENT_OPERATION_HEADER.lower().encode(), operation.encode()))
    return {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/api/document/transaction",
        "raw_path": b"/api/document/transaction",
        "query_string": b"",
        "root_path": "",
        "headers": headers,
        "client": ("test", 1),
        "server": ("test", 80),
    }


def _bind_session(monkeypatch: pytest.MonkeyPatch, session: _Session | None) -> None:
    monkeypatch.setattr(
        transaction_module,
        "AppState",
        lambda _request: SimpleNamespace(get_current_session=lambda: session),
    )


def _native_app(
    session: _Session,
    calls: list[bytes],
    *,
    code: str | None,
    response: bytes = b'{"success":true}',
    status: int = 200,
) -> ASGIApp:
    async def app(_scope: Scope, receive, send) -> None:
        message = await receive()
        body = message.get("body", b"")
        calls.append(body)
        if code is not None:
            session.document.cells[0].code = code
        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": [(b"content-type", b"application/json")],
            }
        )
        await send({"type": "http.response.body", "body": response})

    return app


def _serve(
    adapter: PrivateDocumentTransactionEvidence,
    app: ASGIApp,
    scope: Scope,
    body: bytes,
    *,
    fail_send: bool = False,
) -> list[Message]:
    messages: list[Message] = []

    async def send(message: Message) -> None:
        if fail_send:
            raise ConnectionError("response lost")
        messages.append(message)

    asyncio.run(adapter.serve(app, scope, send, body))
    return messages


def _changed_header(messages: list[Message]) -> bytes | None:
    start = next(
        message for message in messages if message["type"] == "http.response.start"
    )
    return dict(start.get("headers", [])).get(DOCUMENT_CHANGED_HEADER)


@pytest.mark.parametrize(
    ("next_code", "expected"),
    (("value = 1", b"false"), ("value = 2", b"true")),
)
def test_transaction_reports_semantic_document_change(
    monkeypatch: pytest.MonkeyPatch,
    next_code: str,
    expected: bytes,
) -> None:
    session = _Session()
    _bind_session(monkeypatch, session)
    calls: list[bytes] = []

    messages = _serve(
        PrivateDocumentTransactionEvidence(),
        _native_app(session, calls, code=next_code),
        _scope(),
        b'{"changes":[]}',
    )

    assert calls == [b'{"changes":[]}']
    assert _changed_header(messages) == expected


def test_retry_replays_original_evidence_after_response_loss(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _Session()
    _bind_session(monkeypatch, session)
    adapter = PrivateDocumentTransactionEvidence()
    calls: list[bytes] = []
    app = _native_app(session, calls, code="value = 2")
    scope = _scope()
    body = b'{"changes":[{"type":"set-code"}]}'

    with pytest.raises(ConnectionError, match="response lost"):
        _serve(adapter, app, scope, body, fail_send=True)
    replay = _serve(adapter, app, scope, body)

    assert calls == [body]
    assert _changed_header(replay) == b"true"
    assert dict(replay[0]["headers"])[b"content-type"] == b"application/json"
    assert json.loads(replay[-1]["body"]) == {"success": True}


def test_operation_identity_rejects_a_different_retry_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _Session()
    _bind_session(monkeypatch, session)
    adapter = PrivateDocumentTransactionEvidence()
    calls: list[bytes] = []
    app = _native_app(session, calls, code="value = 2")
    scope = _scope()

    _serve(adapter, app, scope, b'{"changes":[1]}')
    conflict = _serve(adapter, app, scope, b'{"changes":[2]}')

    assert calls == [b'{"changes":[1]}']
    assert conflict[0]["status"] == 409
    assert json.loads(conflict[-1]["body"])["error"] == "document-operation-conflict"


def test_transaction_requires_a_current_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _bind_session(monkeypatch, None)
    calls: list[bytes] = []
    session = _Session()

    messages = _serve(
        PrivateDocumentTransactionEvidence(),
        _native_app(session, calls, code=None),
        _scope(),
        b'{"changes":[]}',
    )

    assert messages[0]["status"] == 400
    assert calls == []


def test_transaction_requires_a_valid_operation_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _Session()
    _bind_session(monkeypatch, session)
    adapter = PrivateDocumentTransactionEvidence()

    for operation in (None, "short", "contains spaces 123"):
        calls: list[bytes] = []
        messages = _serve(
            adapter,
            _native_app(session, calls, code=None),
            _scope(operation),
            b'{"changes":[]}',
        )

        assert messages[0]["status"] == 400, operation
        assert calls == [], operation


def test_terminal_ledger_evicts_oldest_outcomes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(transaction_module, "_LEDGER_LIMIT", 2)
    session = _Session()
    _bind_session(monkeypatch, session)
    adapter = PrivateDocumentTransactionEvidence()
    calls: list[bytes] = []
    app = _native_app(session, calls, code="value = 1")
    body = b'{"changes":[]}'

    for index in range(3):
        _serve(adapter, app, _scope(f"operation-{index:07d}"), body)
    _serve(adapter, app, _scope("operation-0000000"), body)

    assert len(calls) == 4


def test_same_session_transactions_are_serialized_and_attributed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sessions = {"s_first": _Session(), "s_second": _Session()}

    class _State:
        def __init__(self, request) -> None:
            self.request = request

        def get_current_session(self) -> _Session:
            return sessions[self.request.headers["marimo-session-id"]]

    monkeypatch.setattr(transaction_module, "AppState", _State)
    adapter = PrivateDocumentTransactionEvidence()

    async def scenario() -> tuple[
        list[Message], list[Message], list[Message], list[str]
    ]:
        first_entered = asyncio.Event()
        release_first = asyncio.Event()
        entered: list[str] = []

        async def app(scope: Scope, receive, send) -> None:
            message = await receive()
            body = message.get("body", b"")
            session_id = dict(scope["headers"])[b"marimo-session-id"].decode()
            entered.append(body.decode())
            if body == b'{"code":"value = 2","wait":true}':
                first_entered.set()
                await release_first.wait()
            sessions[session_id].document.cells[0].code = json.loads(body)["code"]
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b'{"success":true}'})

        async def request(scope: Scope, body: bytes) -> list[Message]:
            messages: list[Message] = []

            async def send(message: Message) -> None:
                messages.append(message)

            await adapter.serve(app, scope, send, body)
            return messages

        first = asyncio.create_task(
            request(
                _scope("operation-0000001", "s_first"),
                b'{"code":"value = 2","wait":true}',
            )
        )
        await wait_for_event(first_entered)
        same_session = asyncio.create_task(
            request(
                _scope("operation-0000002", "s_first"),
                b'{"code":"value = 2"}',
            )
        )
        other_session = await request(
            _scope("operation-0000003", "s_second"),
            b'{"code":"value = 3"}',
        )
        assert entered == [
            '{"code":"value = 2","wait":true}',
            '{"code":"value = 3"}',
        ]
        release_first.set()
        return await first, await same_session, other_session, entered

    first, same_session, other_session, entered = asyncio.run(scenario())

    assert entered[-1] == '{"code":"value = 2"}'
    assert _changed_header(first) == b"true"
    assert _changed_header(same_session) == b"false"
    assert _changed_header(other_session) == b"true"


def test_cancellation_releases_the_exact_session_lock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _Session()
    _bind_session(monkeypatch, session)
    adapter = PrivateDocumentTransactionEvidence()

    async def scenario() -> list[Message]:
        entered = asyncio.Event()
        wait = asyncio.Event()

        async def blocked(_scope: Scope, receive, _send) -> None:
            await receive()
            entered.set()
            await wait.wait()

        async def discard(_message: Message) -> None:
            return None

        first = asyncio.create_task(
            adapter.serve(blocked, _scope("operation-0000001"), discard, b"first")
        )
        await wait_for_event(entered)
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first

        messages: list[Message] = []

        async def send(message: Message) -> None:
            messages.append(message)

        await adapter.serve(
            _native_app(session, [], code="value = 2"),
            _scope("operation-0000002"),
            send,
            b"second",
        )
        return messages

    assert _changed_header(asyncio.run(scenario())) == b"true"


def test_native_non_success_response_passes_through(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _Session()
    _bind_session(monkeypatch, session)
    calls: list[bytes] = []
    body = b'{"error":"invalid-transaction"}'

    messages = _serve(
        PrivateDocumentTransactionEvidence(),
        _native_app(session, calls, code=None, response=body, status=422),
        _scope(),
        b'{"changes":[]}',
    )

    assert messages[0]["status"] == 422
    assert messages[-1]["body"] == body
    assert _changed_header(messages) is None


def test_unexpected_success_response_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _Session()
    _bind_session(monkeypatch, session)
    calls: list[bytes] = []

    with pytest.raises(ProtocolError, match="invalid document transaction success"):
        _serve(
            PrivateDocumentTransactionEvidence(),
            _native_app(session, calls, code="value = 2", response=b'{"success":1}'),
            _scope(),
            b'{"changes":[]}',
        )

    assert calls == [b'{"changes":[]}']
