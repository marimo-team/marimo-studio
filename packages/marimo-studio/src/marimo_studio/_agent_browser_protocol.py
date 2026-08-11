"""Decode strict rendered-browser evidence records."""

from __future__ import annotations

import re
from typing import Any, Literal, cast

from marimo_studio.agent_models import (
    BrowserDiagnostic,
    BrowserObservation,
    BrowserObservationState,
)
from marimo_studio.errors import ProtocolError

_RUNTIME_ID_PATTERN = re.compile(r"^[a-z][a-z0-9-]*$")


def parse_observation_response(
    payload: dict[str, Any],
    views: tuple[str, ...],
) -> tuple[BrowserObservation, ...]:
    if (
        set(payload) != {"schema", "notebook", "observations"}
        or payload.get("schema") != 1
    ):
        raise ProtocolError("The Studio observation response is invalid.")
    raw = payload.get("observations")
    if not isinstance(raw, list):
        raise ProtocolError("The Studio observation response is invalid.")
    observations = tuple(parse_browser_observation(item) for item in raw)
    if tuple(item.view for item in observations) != views:
        raise ProtocolError("The Studio server returned observations for other views.")
    return observations


def decode_browser_observation(
    value: object,
    expected_view: str,
) -> BrowserObservation:
    """Decode one browser upload for a server-issued observation request."""
    if not isinstance(value, dict) or set(value) != {
        "schema",
        "view",
        "runtime",
        "revision",
        "state",
        "diagnostics",
        "clientId",
        "runtimeInstance",
        "sessionId",
        "requestId",
        "sequence",
        "query",
    }:
        raise ProtocolError("The browser observation payload is invalid.")
    view = value.get("view")
    runtime = value.get("runtime")
    revision = value.get("revision")
    state = value.get("state")
    diagnostics = value.get("diagnostics")
    client_id = value.get("clientId")
    runtime_instance = value.get("runtimeInstance")
    session_id = value.get("sessionId")
    request_id = value.get("requestId")
    sequence = value.get("sequence")
    query = value.get("query")
    if (
        value.get("schema") != 1
        or view != expected_view
        or not _runtime_id(runtime)
        or not _nonempty(revision)
        or state not in {"ready", "loading", "error"}
        or not isinstance(diagnostics, list)
        or len(diagnostics) > 200
        or not _nonempty(client_id)
        or not _nonempty(runtime_instance)
        or (session_id is not None and not _nonempty(session_id))
        or not _nonempty(request_id)
        or not _nonnegative_int(sequence)
        or not isinstance(query, str)
    ):
        raise ProtocolError("The browser observation payload is invalid.")
    parsed = tuple(_parse_diagnostic(item, expected_view) for item in diagnostics)
    observed_state = (
        "error"
        if state == "ready"
        and any(diagnostic.severity == "error" for diagnostic in parsed)
        else state
    )
    return BrowserObservation(
        view=expected_view,
        runtime=cast(str, runtime),
        revision=cast(str, revision),
        state=cast(BrowserObservationState, observed_state),
        diagnostics=parsed,
        client_id=cast(str, client_id),
        runtime_instance=cast(str, runtime_instance),
        session_id=cast(str | None, session_id),
        request_id=cast(str, request_id),
        sequence=cast(int, sequence),
        query=query,
    )


def parse_browser_observation(value: object) -> BrowserObservation:
    if not isinstance(value, dict):
        raise ProtocolError("A Studio browser observation is invalid.")
    required = {"view", "state", "diagnostics"}
    optional = {
        "runtime",
        "revision",
        "message",
        "code",
        "client_id",
        "runtime_instance",
        "session_id",
        "request_id",
        "sequence",
        "query",
    }
    if not required.issubset(value) or not set(value).issubset(required | optional):
        raise ProtocolError("A Studio browser observation is invalid.")
    view = value.get("view")
    state = value.get("state")
    runtime = value.get("runtime")
    revision = value.get("revision")
    message = value.get("message")
    code = value.get("code")
    diagnostics = value.get("diagnostics")
    client_id = value.get("client_id")
    runtime_instance = value.get("runtime_instance")
    session_id = value.get("session_id")
    request_id = value.get("request_id")
    sequence = value.get("sequence")
    query = value.get("query")
    if (
        not _nonempty(view)
        or state not in {"ready", "loading", "error", "stale", "not-observed"}
        or (runtime is not None and not _runtime_id(runtime))
        or (revision is not None and not _nonempty(revision))
        or (message is not None and not isinstance(message, str))
        or (code is not None and not _nonempty(code))
        or not isinstance(diagnostics, list)
        or (client_id is not None and not _nonempty(client_id))
        or (runtime_instance is not None and not _nonempty(runtime_instance))
        or (session_id is not None and not _nonempty(session_id))
        or (request_id is not None and not _nonempty(request_id))
        or (sequence is not None and not _nonnegative_int(sequence))
        or (query is not None and not isinstance(query, str))
    ):
        raise ProtocolError("A Studio browser observation is invalid.")
    return BrowserObservation(
        view=cast(str, view),
        state=cast(BrowserObservationState, state),
        runtime=cast(str | None, runtime),
        revision=cast(str | None, revision),
        diagnostics=tuple(
            _parse_diagnostic(item, cast(str, view)) for item in diagnostics
        ),
        message=message,
        code=cast(str | None, code),
        client_id=cast(str | None, client_id),
        runtime_instance=cast(str | None, runtime_instance),
        session_id=cast(str | None, session_id),
        request_id=cast(str | None, request_id),
        sequence=cast(int | None, sequence),
        query=query,
    )


def _parse_diagnostic(value: object, expected_view: str) -> BrowserDiagnostic:
    if not isinstance(value, dict):
        raise ProtocolError("A Studio browser diagnostic is invalid.")
    required = {"code", "severity", "message", "hint", "view", "scope"}
    optional = {"projection", "target", "source"}
    if not required.issubset(value) or not set(value).issubset(required | optional):
        raise ProtocolError("A Studio browser diagnostic is invalid.")
    code = value.get("code")
    severity = value.get("severity")
    message = value.get("message")
    hint = value.get("hint")
    view = value.get("view")
    scope = value.get("scope")
    target = value.get("target")
    projection = value.get("projection")
    source = value.get("source")
    if (
        not _nonempty(code)
        or severity not in {"warning", "error"}
        or not isinstance(message, str)
        or not isinstance(hint, str)
        or view != expected_view
        or not _nonempty(scope)
        or (projection is not None and projection not in {"cell", "value", "output"})
        or (target is not None and not isinstance(target, str))
        or not _valid_source(source)
    ):
        raise ProtocolError("A Studio browser diagnostic is invalid.")
    return BrowserDiagnostic(
        code=cast(str, code),
        severity=cast(Literal["warning", "error"], severity),
        message=message,
        hint=hint,
        view=expected_view,
        scope=cast(str, scope),
        projection=cast(Literal["cell", "value", "output"] | None, projection),
        target=target,
        source=cast(dict[str, object] | None, source),
    )


def _valid_source(value: object) -> bool:
    if value is None:
        return True
    if not isinstance(value, dict) or set(value) != {"path", "line", "column"}:
        return False
    return (
        isinstance(value.get("path"), str)
        and _nonnegative_int(value.get("line"))
        and _nonnegative_int(value.get("column"))
    )


def _nonempty(value: object) -> bool:
    return isinstance(value, str) and bool(value)


def _runtime_id(value: object) -> bool:
    return isinstance(value, str) and _RUNTIME_ID_PATTERN.fullmatch(value) is not None


def _nonnegative_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


__all__ = [
    "decode_browser_observation",
    "parse_browser_observation",
    "parse_observation_response",
]
