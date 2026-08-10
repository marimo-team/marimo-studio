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
    AnalysisAction,
    AnalysisReport,
    BrowserDiagnostic,
    BrowserObservation,
    BrowserObservationState,
    CheckResult,
    ViewActivationResult,
)


@dataclass(frozen=True)
class StudioServerConnection:
    server_url: str
    auth_token: str = ""
    routing_query: tuple[tuple[str, str], ...] = ()
    server_token: str = ""


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
    """Request one validated view as the browser's active Studio view."""
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
        or payload.get("transition") not in {"in-place", "reload"}
    ):
        raise ProtocolError("The Studio activation response is invalid.")
    return ViewActivationResult(
        notebook=notebook,
        view=view,
        state="requested",
        generation=payload["generation"],
        transition=cast(Literal["in-place", "reload"], payload["transition"]),
    )


async def request_analysis(
    connection: StudioServerConnection,
    notebook: Path,
    *,
    view_name: str | None = None,
    timeout: float = 10.0,
    require_browser: bool = True,
) -> AnalysisReport:
    """Run Studio analysis in the server attached to the active notebook."""
    payload = await _request_json(
        connection,
        f"{SUPPORT_PATH}/analyze",
        method="POST",
        body={
            "view": view_name,
            "timeout": timeout,
            "require_browser": require_browser,
        },
        timeout=max(90.0, timeout + 90.0),
    )
    _require_notebook(payload, notebook)
    report = _parse_analysis_report(payload)
    if view_name is not None and report.views != (view_name,):
        raise ProtocolError("The Studio analysis response is invalid.")
    return report


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
    request = Request(url, data=data, headers=headers, method=method)

    def send() -> bytes:
        try:
            with urlopen(request, timeout=timeout) as response:
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


def _parse_analysis_report(payload: dict[str, Any]) -> AnalysisReport:
    notebook = payload.get("notebook")
    views = payload.get("views")
    stages = payload.get("stages")
    actions = payload.get("actions")
    if (
        payload.get("schema") != 1
        or not isinstance(notebook, str)
        or not isinstance(views, list)
        or not all(isinstance(view, str) for view in views)
        or not isinstance(stages, dict)
        or not isinstance(actions, list)
    ):
        raise ProtocolError("The Studio analysis response is invalid.")
    static = stages.get("static")
    runtime = stages.get("runtime")
    browser = stages.get("browser")
    if (
        not isinstance(static, dict)
        or not isinstance(runtime, dict)
        or not isinstance(browser, dict)
        or not isinstance(static.get("checks"), list)
        or not isinstance(runtime.get("checks"), list)
        or not isinstance(browser.get("observations"), list)
        or not isinstance(browser.get("required"), bool)
        or (
            runtime.get("reason") is not None
            and not isinstance(runtime.get("reason"), str)
        )
    ):
        raise ProtocolError("The Studio analysis response is invalid.")
    report = AnalysisReport(
        notebook=Path(notebook).resolve(),
        views=tuple(cast(list[str], views)),
        static_checks=tuple(_parse_check(item) for item in static["checks"]),
        runtime_checks=tuple(_parse_check(item) for item in runtime["checks"]),
        runtime_skipped=cast(str | None, runtime.get("reason")),
        browser_observations=tuple(
            _parse_observation(item) for item in browser["observations"]
        ),
        browser_required=browser["required"],
        actions=tuple(_parse_action(item) for item in actions),
    )
    if (
        payload.get("ok") is not report.ok
        or payload.get("handoff_ready") is not report.handoff_ready
    ):
        raise ProtocolError("The Studio analysis response is invalid.")
    return report


def _parse_check(value: object) -> CheckResult:
    if not isinstance(value, dict):
        raise ProtocolError("A Studio analysis check is invalid.")
    name = value.get("name")
    status = value.get("status")
    message = value.get("message")
    code = value.get("code")
    details = value.get("details")
    if (
        not isinstance(name, str)
        or status not in {"pass", "warn", "fail"}
        or not isinstance(message, str)
        or (code is not None and not isinstance(code, str))
        or (details is not None and not _string_keyed_mapping(details))
    ):
        raise ProtocolError("A Studio analysis check is invalid.")
    return CheckResult(
        name=name,
        status=cast(Literal["pass", "warn", "fail"], status),
        message=message,
        code=code,
        details=cast(dict[str, Any] | None, details),
    )


def _parse_action(value: object) -> AnalysisAction:
    if not isinstance(value, dict):
        raise ProtocolError("A Studio analysis action is invalid.")
    stage = value.get("stage")
    severity = value.get("severity")
    code = value.get("code")
    message = value.get("message")
    advice = value.get("advice")
    view = value.get("view")
    target = value.get("target")
    source = value.get("source")
    if (
        stage not in {"static", "runtime", "browser"}
        or severity not in {"warning", "error"}
        or not isinstance(code, str)
        or not isinstance(message, str)
        or not isinstance(advice, str)
        or (view is not None and not isinstance(view, str))
        or (target is not None and not isinstance(target, str))
        or (source is not None and not _string_keyed_mapping(source))
    ):
        raise ProtocolError("A Studio analysis action is invalid.")
    return AnalysisAction(
        stage=cast(Literal["static", "runtime", "browser"], stage),
        severity=cast(Literal["warning", "error"], severity),
        code=code,
        message=message,
        advice=advice,
        view=view,
        target=target,
        source=cast(dict[str, object] | None, source),
    )


def _string_keyed_mapping(value: object) -> bool:
    return isinstance(value, dict) and all(isinstance(key, str) for key in value)


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
    "request_analysis",
    "request_view_activation",
    "studio_server_connection",
]
