"""Report whether a native editor transaction changed authored notebook state."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from collections import OrderedDict
from dataclasses import dataclass
from threading import RLock
from typing import Any, cast
from weakref import WeakKeyDictionary

from marimo._server.api.deps import AppState
from marimo._session.session import Session
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Scope, Send

from marimo_studio.errors import ProtocolError

DOCUMENT_CHANGED_HEADER = b"marimo-studio-document-changed"
DOCUMENT_OPERATION_HEADER = "Marimo-Studio-Document-Operation"
_OPERATION = re.compile(r"^[A-Za-z0-9_-]{16,128}$")
_LEDGER_LIMIT = 128


@dataclass(frozen=True)
class _TerminalOutcome:
    fingerprint: bytes
    status: int
    headers: tuple[tuple[bytes, bytes], ...]
    body: bytes


def _document_state(session: Session) -> tuple[tuple[object, ...], ...]:
    return tuple(
        (
            str(cell.id),
            cell.code,
            cell.name,
            cell.config.column,
            cell.config.disabled,
            cell.config.hide_code,
        )
        for cell in session.document.cells
    )


class PrivateDocumentTransactionEvidence:
    """Serialize and classify native transactions for their exact session."""

    def __init__(self) -> None:
        self._locks: WeakKeyDictionary[Any, asyncio.Lock] = WeakKeyDictionary()
        self._outcomes: WeakKeyDictionary[Any, OrderedDict[str, _TerminalOutcome]] = (
            WeakKeyDictionary()
        )
        self._locks_guard = RLock()

    def _lock(self, session: Session) -> asyncio.Lock:
        with self._locks_guard:
            lock = self._locks.get(cast(Any, session))
            if lock is None:
                lock = asyncio.Lock()
                self._locks[cast(Any, session)] = lock
            return lock

    def _ledger(self, session: Session) -> OrderedDict[str, _TerminalOutcome]:
        with self._locks_guard:
            ledger = self._outcomes.get(cast(Any, session))
            if ledger is None:
                ledger = OrderedDict()
                self._outcomes[cast(Any, session)] = ledger
            return ledger

    async def serve(
        self,
        app: ASGIApp,
        scope: Scope,
        send: Send,
        body: bytes,
    ) -> None:
        request = Request(scope)
        session = AppState(request).get_current_session()
        operation = request.headers.get(DOCUMENT_OPERATION_HEADER)
        if session is None:
            await JSONResponse(
                {
                    "error": "document-session-unavailable",
                    "message": "The document transaction session is unavailable.",
                },
                status_code=400,
            )(scope, _empty_receive, send)
            return
        if operation is None or _OPERATION.fullmatch(operation) is None:
            await JSONResponse(
                {
                    "error": "invalid-document-operation",
                    "message": "The document operation identity is invalid.",
                },
                status_code=400,
            )(scope, _empty_receive, send)
            return
        fingerprint = hashlib.sha256(body).digest()
        lock = self._lock(session)
        async with lock:
            ledger = self._ledger(session)
            retained = ledger.get(operation)
            if retained is not None:
                if retained.fingerprint != fingerprint:
                    await JSONResponse(
                        {
                            "error": "document-operation-conflict",
                            "message": (
                                "The document operation was reused with "
                                "different changes."
                            ),
                        },
                        status_code=409,
                    )(scope, _empty_receive, send)
                    return
                await send(
                    {
                        "type": "http.response.start",
                        "status": retained.status,
                        "headers": list(retained.headers),
                    }
                )
                await send(
                    {
                        "type": "http.response.body",
                        "body": retained.body,
                    }
                )
                return

            before = _document_state(session)
            consumed = False

            async def replay() -> Message:
                nonlocal consumed
                payload = b"" if consumed else body
                consumed = True
                return {
                    "type": "http.request",
                    "body": payload,
                    "more_body": False,
                }

            start: Message | None = None
            response_body = bytearray()
            complete = False

            async def capture(message: Message) -> None:
                nonlocal complete, start
                if complete:
                    raise ProtocolError(
                        "Marimo sent data after the document transaction response."
                    )
                if message["type"] == "http.response.start":
                    if start is not None:
                        raise ProtocolError(
                            "Marimo started the document transaction response twice."
                        )
                    start = message
                    return
                if message["type"] != "http.response.body":
                    raise ProtocolError(
                        "Marimo returned an invalid document transaction response."
                    )
                response_body.extend(message.get("body", b""))
                complete = not message.get("more_body", False)

            await app(scope, replay, capture)
            if start is None or not complete:
                raise ProtocolError(
                    "Marimo omitted the complete document transaction response."
                )
            if 200 <= start["status"] < 300:
                try:
                    payload = json.loads(response_body)
                except (UnicodeDecodeError, json.JSONDecodeError) as error:
                    raise ProtocolError(
                        "Marimo returned invalid document transaction success."
                    ) from error
                if (
                    start["status"] != 200
                    or not isinstance(payload, dict)
                    or set(payload) != {"success"}
                    or payload["success"] is not True
                ):
                    raise ProtocolError(
                        "Marimo returned invalid document transaction success."
                    )
                headers = list(start.get("headers", []))
                if any(name.lower() == DOCUMENT_CHANGED_HEADER for name, _ in headers):
                    raise ProtocolError(
                        "Marimo returned Studio document transaction evidence."
                    )
                changed = _document_state(session) != before
                headers.append(
                    (
                        DOCUMENT_CHANGED_HEADER,
                        b"true" if changed else b"false",
                    )
                )
                start = {**start, "headers": headers}
                ledger[operation] = _TerminalOutcome(
                    fingerprint=fingerprint,
                    status=start["status"],
                    headers=tuple(headers),
                    body=bytes(response_body),
                )
                ledger.move_to_end(operation)
                while len(ledger) > _LEDGER_LIMIT:
                    ledger.popitem(last=False)
            await send(start)
            await send({"type": "http.response.body", "body": bytes(response_body)})


async def _empty_receive() -> Message:
    return {"type": "http.request", "body": b"", "more_body": False}
