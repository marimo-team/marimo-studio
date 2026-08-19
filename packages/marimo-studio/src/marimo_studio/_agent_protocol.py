"""Validate JSON records exchanged by Studio agent clients and routes."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

from marimo_studio._agent_analysis_protocol import parse_analysis_report
from marimo_studio._agent_browser_protocol import (
    decode_browser_observation,
    parse_browser_observation,
    parse_observation_response,
)
from marimo_studio.activation import ViewActivationResult
from marimo_studio.errors import ProtocolError


def parse_connection_token(payload: dict[str, Any], notebook: Path) -> str:
    if (
        set(payload) != {"schema", "notebook", "server_token"}
        or type(payload.get("schema")) is not int
        or payload.get("schema") != 1
        or payload.get("notebook") != str(notebook)
        or not _nonempty(payload.get("server_token"))
    ):
        raise ProtocolError("The Studio connection response is invalid.")
    return cast(str, payload["server_token"])


def parse_activation_result(
    payload: dict[str, Any],
    notebook: Path,
    view: str,
) -> ViewActivationResult:
    state = payload.get("state")
    transition = payload.get("transition")
    generation = payload.get("generation")
    client_id = payload.get("client_id")
    client_id_present = "client_id" in payload
    session_id = payload.get("session_id")
    schema = payload.get("schema")
    required = {
        "schema",
        "notebook",
        "view",
        "state",
        "generation",
        "transition",
        "session_id",
    }
    optional = {"client_id"}
    if (
        not required.issubset(payload)
        or not set(payload).issubset(required | optional)
        or not isinstance(schema, int)
        or isinstance(schema, bool)
        or schema != 1
        or payload.get("notebook") != str(notebook)
        or payload.get("view") != view
        or state != "active"
        or transition != "in-place"
        or not _nonnegative_int(generation)
        or (client_id is not None and not _nonempty(client_id))
        or not _nonempty(session_id)
        or not client_id_present
        or not _nonempty(client_id)
    ):
        raise ProtocolError("The Studio activation response is invalid.")
    return ViewActivationResult(
        notebook=notebook,
        view=view,
        state="active",
        generation=cast(int, generation),
        transition="in-place",
        client_id=cast(str, client_id),
        session_id=cast(str, session_id),
    )


def _nonempty(value: object) -> bool:
    return isinstance(value, str) and bool(value)


def _nonnegative_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


__all__ = [
    "decode_browser_observation",
    "parse_activation_result",
    "parse_analysis_report",
    "parse_browser_observation",
    "parse_connection_token",
    "parse_observation_response",
]
