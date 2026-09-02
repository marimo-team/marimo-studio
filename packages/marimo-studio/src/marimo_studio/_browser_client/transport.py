"""Send bounded, cancellable requests to a running Studio server."""

from __future__ import annotations

import asyncio
import http.client
import json
import socket
import threading
from contextlib import suppress
from dataclasses import dataclass
from ipaddress import IPv6Address, ip_address
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from marimo_studio.errors import AgentRequestError, ProtocolError

_MAX_RESPONSE_BYTES = 5_000_000
_MAX_HTTP_WORKERS = 8
_HTTP_WORKER_SLOTS = threading.BoundedSemaphore(_MAX_HTTP_WORKERS)


@dataclass(frozen=True)
class StudioServerConnection:
    server_url: str
    auth_token: str = ""
    routing_query: tuple[tuple[str, str], ...] = ()
    server_token: str = ""
    session_id: str = ""
    browser_client: str = ""


def studio_server_connection(
    url: str,
    *,
    access_token: str = "",
    browser_client: str = "",
) -> StudioServerConnection:
    """Parse a server URL and keep credentials in dedicated connection fields."""
    try:
        parts = urlsplit(url)
        hostname = parts.hostname
        _ = parts.port
    except ValueError as error:
        raise ProtocolError("The Studio server URL is invalid.") from error
    if parts.scheme not in {"http", "https"} or not parts.netloc or hostname is None:
        raise ProtocolError("Studio server URLs must use http or https.")
    if parts.scheme == "http" and not _is_loopback_host(hostname):
        raise ProtocolError("Non-loopback Studio server URLs must use https.")
    parameters = parse_qsl(parts.query, keep_blank_values=True)
    if (
        parts.username is not None
        or parts.password is not None
        or bool(parts.fragment)
        or any(key == "access_token" for key, _value in parameters)
    ):
        raise ProtocolError(
            "Provide the Studio access token through its dedicated credential input."
        )
    routing_query = tuple((key, value) for key, value in parameters if key == "file")
    server_url = urlunsplit(
        (parts.scheme, parts.netloc, parts.path.rstrip("/"), "", "")
    )
    return StudioServerConnection(
        server_url=server_url,
        auth_token=access_token,
        routing_query=routing_query,
        browser_client=browser_client,
    )


def _is_loopback_host(hostname: str) -> bool:
    normalized = hostname.rstrip(".").lower()
    if normalized == "localhost" or normalized.endswith(".localhost"):
        return True
    try:
        address = ip_address(normalized)
    except ValueError:
        return False
    if address.is_loopback:
        return True
    return (
        isinstance(address, IPv6Address)
        and address.ipv4_mapped is not None
        and address.ipv4_mapped.is_loopback
    )


class _HttpExchange:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._cancelled = threading.Event()
        self._connection: http.client.HTTPConnection | None = None

    def cancel(self) -> None:
        self._cancelled.set()
        with self._lock:
            connection = self._connection
        if connection is not None:
            sock = getattr(connection, "sock", None)
            if sock is not None:
                with suppress(OSError):
                    sock.shutdown(socket.SHUT_RDWR)
            with suppress(OSError):
                connection.close()

    def send(
        self,
        url: str,
        method: str,
        headers: dict[str, str],
        body: bytes | None,
        timeout: float,
    ) -> bytes:
        parts = urlsplit(url)
        connection_type = (
            http.client.HTTPSConnection
            if parts.scheme == "https"
            else http.client.HTTPConnection
        )
        hostname = parts.hostname
        if hostname is None:
            raise ProtocolError("The Studio server URL has no hostname.")
        connection = connection_type(hostname, parts.port, timeout=timeout)
        # The request starts with an explicit connect. Disabling auto-open
        # prevents request() from reconnecting a socket closed by cancel().
        connection.auto_open = False
        with self._lock:
            if self._cancelled.is_set():
                connection.close()
                raise AgentRequestError(
                    "request-cancelled",
                    "The Studio server request was cancelled.",
                )
            self._connection = connection
        target = urlunsplit(("", "", parts.path or "/", parts.query, ""))
        try:
            connection.connect()
            if self._cancelled.is_set():
                connection.close()
                raise AgentRequestError(
                    "request-cancelled",
                    "The Studio server request was cancelled.",
                )
            connection.request(method, target, body=body, headers=headers)
            response = connection.getresponse()
            raw = response.read(_MAX_RESPONSE_BYTES + 1)
            if len(raw) > _MAX_RESPONSE_BYTES:
                raise ProtocolError("The Studio server response exceeded 5 MB.")
            if response.status >= 400:
                _raise_response_error(response.status, raw)
            return raw
        except AgentRequestError:
            raise
        except (OSError, TimeoutError, http.client.HTTPException) as error:
            if self._cancelled.is_set():
                raise AgentRequestError(
                    "request-cancelled",
                    "The Studio server request was cancelled.",
                ) from error
            raise AgentRequestError(
                "server-unavailable",
                "The running Studio server is unavailable.",
            ) from error
        finally:
            with suppress(OSError):
                connection.close()
            with self._lock:
                if self._connection is connection:
                    self._connection = None


async def request_json(
    connection: StudioServerConnection,
    path: str,
    *,
    method: str = "GET",
    query: tuple[tuple[str, str], ...] = (),
    body: dict[str, object] | None = None,
    timeout: float = 15.0,
) -> dict[str, Any]:
    parameters = (*connection.routing_query, *query)
    suffix = f"?{urlencode(parameters)}" if parameters else ""
    url = f"{connection.server_url.rstrip('/')}{path}{suffix}"
    headers = {"Accept": "application/json"}
    data = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body, separators=(",", ":")).encode()
    if connection.auth_token:
        headers["Authorization"] = f"Bearer {connection.auth_token}"
    if connection.server_token:
        headers["Marimo-Server-Token"] = connection.server_token
    if connection.session_id:
        headers["Marimo-Session-Id"] = connection.session_id
    exchange = _HttpExchange()
    future = _start_exchange(exchange, url, method, headers, data, timeout)
    try:
        raw = await asyncio.wait_for(asyncio.shield(future), timeout)
    except asyncio.TimeoutError as error:
        exchange.cancel()
        future.cancel()
        raise AgentRequestError(
            "request-timeout",
            "The Studio server request timed out.",
        ) from error
    except asyncio.CancelledError:
        exchange.cancel()
        future.cancel()
        raise
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise ProtocolError("The Studio server returned invalid JSON.") from error
    if not isinstance(payload, dict):
        raise ProtocolError("The Studio server returned an invalid response.")
    return payload


def _start_exchange(
    exchange: _HttpExchange,
    url: str,
    method: str,
    headers: dict[str, str],
    body: bytes | None,
    timeout: float,
) -> asyncio.Future[bytes]:
    worker_slots = _HTTP_WORKER_SLOTS
    if not worker_slots.acquire(blocking=False):
        raise AgentRequestError(
            "request-capacity-exhausted",
            (
                "Studio server request capacity is exhausted. Retry after an "
                "in-flight request finishes."
            ),
            status_code=503,
        )
    loop = asyncio.get_running_loop()
    future: asyncio.Future[bytes] = loop.create_future()

    def send() -> None:
        result: bytes | None = None
        error: BaseException | None = None
        try:
            result = exchange.send(url, method, headers, body, timeout)
        except BaseException as caught:
            error = caught
        finally:
            worker_slots.release()
        with suppress(RuntimeError):
            loop.call_soon_threadsafe(_finish_exchange, future, result, error)

    worker = threading.Thread(
        target=send,
        name="marimo-studio-http",
        daemon=True,
    )
    try:
        worker.start()
    except Exception:
        worker_slots.release()
        future.cancel()
        raise
    return future


def _finish_exchange(
    future: asyncio.Future[bytes],
    result: bytes | None,
    error: BaseException | None,
) -> None:
    if future.done():
        return
    if error is not None:
        future.set_exception(error)
    else:
        assert result is not None
        future.set_result(result)


def _raise_response_error(status: int, raw: bytes) -> None:
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError):
        payload = None
    code = payload.get("error") if isinstance(payload, dict) else None
    message = payload.get("message") if isinstance(payload, dict) else None
    details = (
        {
            key: value
            for key, value in payload.items()
            if key not in {"error", "message"}
        }
        if isinstance(payload, dict)
        else None
    )
    raise AgentRequestError(
        code if isinstance(code, str) and code else f"http-{status}",
        message if isinstance(message, str) and message else f"HTTP {status}",
        status_code=status,
        details=details,
    )
