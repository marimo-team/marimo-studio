"""Validate JSON records exchanged by Studio agent clients and routes."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal, cast

from marimo_studio._agent_analysis_protocol import parse_analysis_report
from marimo_studio._agent_browser_protocol import (
    decode_browser_observation,
    parse_browser_observation,
    parse_observation_response,
)
from marimo_studio.agent_models import ViewActivationResult
from marimo_studio.errors import ProtocolError


def parse_connection_token(payload: dict[str, Any], notebook: Path) -> str:
    if (
        set(payload) != {"schema", "notebook", "server_token"}
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
    session_id = payload.get("session_id")
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
        or payload.get("schema") != 1
        or payload.get("notebook") != str(notebook)
        or payload.get("view") != view
        or state not in {"active", "reload-requested"}
        or transition not in {"in-place", "reload"}
        or not _nonnegative_int(generation)
        or (client_id is not None and not _nonempty(client_id))
        or not _nonempty(session_id)
        or (state == "active" and not _nonempty(client_id))
        or (state == "reload-requested" and client_id is not None)
        or (state == "active") != (transition == "in-place")
    ):
        raise ProtocolError("The Studio activation response is invalid.")
    return ViewActivationResult(
        notebook=notebook,
        view=view,
        state=cast(Literal["active", "reload-requested"], state),
        generation=cast(int, generation),
        transition=cast(Literal["in-place", "reload"], transition),
        client_id=cast(str | None, client_id),
        session_id=cast(str | None, session_id),
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
