"""Call agent-facing routes on a running Studio server."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, cast
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen

from marimo_studio._urls import SUPPORT_PATH
from marimo_studio.errors import ProtocolError
from marimo_studio.types import (
    BrowserDiagnostic,
    BrowserObservation,
    BrowserObservationState,
    ViewActivationResult,
)


@dataclass(frozen=True)
class StudioServerConnection:
    server_url: str
    auth_token: str = ""
    routing_query: tuple[tuple[str, str], ...] = ()


def studio_server_connection(
    url: str,
    *,
    access_token: str = "",
) -> StudioServerConnection:
    """Parse a running Marimo URL without retaining its access token."""
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        raise ProtocolError("Studio server URLs must use http or https.")
    parameters = parse_qsl(parts.query, keep_blank_values=True)
    embedded_tokens = [value for key, value in parameters if key == "access_token"]
    token = access_token or (embedded_tokens[-1] if embedded_tokens else "")
    routing_query = tuple((key, value) for key, value in parameters if key == "file")
    server_url = urlunsplit(
        (parts.scheme, parts.netloc, parts.path.rstrip("/"), "", "")
    )
    return StudioServerConnection(
        server_url=server_url,
        auth_token=token,
        routing_query=routing_query,
    )


async def request_view_activation(
    connection: StudioServerConnection,
    notebook: Path,
    view: str,
) -> ViewActivationResult:
    """Ask connected Studio workspaces to select one validated view."""
    payload = await _request_json(
        connection,
        f"{SUPPORT_PATH}/views/{quote(view, safe='')}/activate",
        method="PATCH",
    )
    _require_notebook(payload, notebook)
    if (
        payload.get("view") != view
        or payload.get("state") != "requested"
        or not isinstance(payload.get("generation"), int)
    ):
        raise ProtocolError("The Studio activation response is invalid.")
    return ViewActivationResult(
        notebook=notebook,
        view=view,
        state="requested",
        generation=payload["generation"],
    )


async def observe_browser_views(
    connection: StudioServerConnection,
    notebook: Path,
    views: tuple[str, ...],
    *,
    runtime: str | None = None,
    timeout: float = 10.0,
) -> tuple[BrowserObservation, ...]:
    """Wait for current browser evidence from a running Studio server."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    query = [("view", view) for view in views]
    if runtime is not None:
        query.append(("runtime", runtime))
    observations: tuple[BrowserObservation, ...] = ()
    while True:
        payload = await _request_json(
            connection,
            f"{SUPPORT_PATH}/observations",
            query=tuple(query),
        )
        _require_notebook(payload, notebook)
        observations = _parse_observations(payload, views)
        if all(item.state in {"ready", "error"} for item in observations):
            return observations
        remaining = deadline - loop.time()
        if remaining <= 0:
            return observations
        await asyncio.sleep(min(0.25, remaining))


async def _request_json(
    connection: StudioServerConnection,
    path: str,
    *,
    method: str = "GET",
    query: tuple[tuple[str, str], ...] = (),
) -> dict[str, Any]:
    parameters = (*connection.routing_query, *query)
    suffix = f"?{urlencode(parameters)}" if parameters else ""
    url = f"{connection.server_url.rstrip('/')}{path}{suffix}"
    headers = {"Accept": "application/json"}
    if connection.auth_token:
        headers["Authorization"] = f"Bearer {connection.auth_token}"
    request = Request(url, headers=headers, method=method)

    def send() -> bytes:
        try:
            with urlopen(request, timeout=15) as response:
                return response.read()
        except HTTPError as error:
            try:
                detail = json.loads(error.read()).get("message")
            except (AttributeError, json.JSONDecodeError, UnicodeDecodeError):
                detail = None
            message = detail if isinstance(detail, str) else f"HTTP {error.code}"
            raise ProtocolError(
                f"The Studio server rejected the request: {message}"
            ) from error
        except URLError as error:
            raise ProtocolError("The running Studio server is unavailable.") from error

    raw = await asyncio.to_thread(send)
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise ProtocolError("The Studio server returned invalid JSON.") from error
    if not isinstance(payload, dict):
        raise ProtocolError("The Studio server returned an invalid response.")
    return payload


def _require_notebook(payload: dict[str, Any], notebook: Path) -> None:
    reported = payload.get("notebook")
    if not isinstance(reported, str) or Path(reported).resolve() != notebook.resolve():
        raise ProtocolError("The Studio server is attached to a different notebook.")


def _parse_observations(
    payload: dict[str, Any],
    views: tuple[str, ...],
) -> tuple[BrowserObservation, ...]:
    raw = payload.get("observations")
    if not isinstance(raw, list):
        raise ProtocolError("The Studio observation response is invalid.")
    observations = tuple(_parse_observation(item) for item in raw)
    if tuple(item.view for item in observations) != views:
        raise ProtocolError("The Studio server returned observations for other views.")
    return observations


def _parse_observation(value: object) -> BrowserObservation:
    if not isinstance(value, dict):
        raise ProtocolError("A Studio browser observation is invalid.")
    view = value.get("view")
    state = value.get("state")
    runtime = value.get("runtime")
    revision = value.get("revision")
    message = value.get("message")
    diagnostics = value.get("diagnostics")
    if (
        not isinstance(view, str)
        or state not in {"ready", "loading", "error", "stale", "not-observed"}
        or (runtime is not None and not isinstance(runtime, str))
        or (revision is not None and not isinstance(revision, str))
        or (message is not None and not isinstance(message, str))
        or not isinstance(diagnostics, list)
    ):
        raise ProtocolError("A Studio browser observation is invalid.")
    return BrowserObservation(
        view=view,
        state=cast(BrowserObservationState, state),
        runtime=runtime,
        revision=revision,
        diagnostics=tuple(_parse_diagnostic(item) for item in diagnostics),
        message=message,
    )


def _parse_diagnostic(value: object) -> BrowserDiagnostic:
    if not isinstance(value, dict):
        raise ProtocolError("A Studio browser diagnostic is invalid.")
    code = value.get("code")
    severity = value.get("severity")
    message = value.get("message")
    hint = value.get("hint")
    view = value.get("view")
    scope = value.get("scope")
    if (
        not isinstance(code, str)
        or severity not in {"warning", "error"}
        or not isinstance(message, str)
        or not isinstance(hint, str)
        or not isinstance(view, str)
        or not isinstance(scope, str)
    ):
        raise ProtocolError("A Studio browser diagnostic is invalid.")
    target = value.get("target")
    source = value.get("source")
    if target is not None and not isinstance(target, str):
        raise ProtocolError("A Studio browser diagnostic target is invalid.")
    if source is not None and not isinstance(source, dict):
        raise ProtocolError("A Studio browser diagnostic source is invalid.")
    parsed_source = (
        cast(dict[str, object], source) if isinstance(source, dict) else None
    )
    return BrowserDiagnostic(
        code=code,
        severity=cast(Literal["warning", "error"], severity),
        message=message,
        hint=hint,
        view=view,
        scope=scope,
        target=target,
        source=parsed_source,
    )


__all__ = [
    "StudioServerConnection",
    "observe_browser_views",
    "request_view_activation",
    "studio_server_connection",
]
