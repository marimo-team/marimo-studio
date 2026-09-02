from __future__ import annotations

import asyncio
from typing import Any, cast

import pytest
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Scope, Send

import marimo_studio._server.editor_bridge as editor_bridge
from marimo_studio._server.editor_bridge import delegate_editor_request
from marimo_studio._server.ports import DocumentTransactionEvidence


class _Evidence:
    def __init__(self) -> None:
        self.bodies: list[bytes] = []

    async def serve(
        self,
        _app: ASGIApp,
        scope: Scope,
        send: Send,
        body: bytes,
    ) -> None:
        self.bodies.append(body)
        await JSONResponse(
            {"success": True},
            headers={"marimo-studio-document-changed": "false"},
        )(scope, _empty_receive, send)


class _Server:
    async def location(self, _connection: object) -> None:
        return None


async def _empty_receive() -> Message:
    return {"type": "http.request", "body": b"", "more_body": False}


def _scope(size: int) -> Scope:
    return {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/_marimo-studio/editor/api/document/transaction",
        "raw_path": b"/_marimo-studio/editor/api/document/transaction",
        "query_string": b"",
        "root_path": "",
        "headers": [(b"content-length", str(size).encode())],
        "client": ("test", 1),
        "server": ("test", 80),
    }


def _delegate(body: bytes, evidence: _Evidence) -> list[Message]:
    messages: list[Message] = [
        {"type": "http.request", "body": body, "more_body": False}
    ]
    responses: list[Message] = []

    async def app(_scope: Scope, _receive, _send) -> None:
        raise AssertionError("The prefixed transaction bypassed its evidence adapter")

    async def receive() -> Message:
        return messages.pop(0)

    async def send(message: Message) -> None:
        responses.append(message)

    served = asyncio.run(
        delegate_editor_request(
            app,
            cast(Any, object()),
            _scope(len(body)),
            receive,
            send,
            server=cast(Any, _Server()),
            sessions=cast(Any, object()),
            attachment=cast(Any, object()),
            persistence=cast(Any, object()),
            code_mode=cast(Any, object()),
            editor_runtime=cast(Any, object()),
            document_transactions=cast(DocumentTransactionEvidence, evidence),
            relative="/_marimo-studio/editor/api/document/transaction",
            mode="edit",
        )
    )
    assert served is True
    return responses


def test_prefixed_transaction_accepts_supported_large_cell_source() -> None:
    evidence = _Evidence()
    body = b"x" * (4 * 1024 * 1024 + 1)

    response = _delegate(body, evidence)

    assert response[0]["status"] == 200
    assert dict(response[0]["headers"])[b"marimo-studio-document-changed"] == b"false"
    assert evidence.bodies == [body]


def test_prefixed_transaction_rejects_oversize_before_adapter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    evidence = _Evidence()
    monkeypatch.setattr(editor_bridge, "_DOCUMENT_TRANSACTION_MAX_BYTES", 8)

    response = _delegate(b"123456789", evidence)

    assert response[0]["status"] == 413
    assert evidence.bodies == []
