"""Validate JSON records exchanged by Studio agent clients and routes."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from marimo_studio._browser_client.analysis_protocol import (
    parse_analysis_report as parse_analysis_report,
)
from marimo_studio._browser_client.browser_protocol import (
    decode_browser_observation as decode_browser_observation,
)
from marimo_studio._browser_client.browser_protocol import (
    parse_browser_observation as parse_browser_observation,
)
from marimo_studio._browser_client.browser_protocol import (
    parse_observation_response as parse_observation_response,
)
from marimo_studio._browser_client.records import ViewActivationResult
from marimo_studio.errors import CapabilityInputError, ProtocolError


@dataclass(frozen=True)
class ViewActivationRequest:
    """Select a view and optional external browser client."""

    view: str
    browser_client: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.view, str) or not self.view:
            raise CapabilityInputError(
                "invalid-activation-request",
                "view",
                "view must be a non-empty string",
            )
        if self.browser_client is not None and (
            not isinstance(self.browser_client, str) or not self.browser_client
        ):
            raise CapabilityInputError(
                "invalid-activation-request",
                "browser_client",
                "browser_client must be a non-empty string or null",
            )

    def to_dict(self) -> dict[str, object]:
        return {"schema": 1, "browser_client": self.browser_client}

    @classmethod
    def from_dict(cls, view: str, payload: object) -> ViewActivationRequest:
        schema = payload.get("schema") if isinstance(payload, dict) else None
        if (
            not isinstance(payload, dict)
            or set(payload) != {"schema", "browser_client"}
            or not isinstance(schema, int)
            or isinstance(schema, bool)
            or schema != 1
        ):
            raise CapabilityInputError(
                "invalid-activation-request",
                "request",
                "The activation request must contain schema and browser_client",
            )
        return cls(view=view, browser_client=payload.get("browser_client"))


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
    generation = payload.get("generation")
    client_id = payload.get("client_id")
    client_id_present = "client_id" in payload
    session_id = payload.get("session_id")
    schema = payload.get("schema")
    required = {
        "schema",
        "notebook",
        "view",
        "generation",
        "session_id",
    }
    optional = {"client_id"}
    if (
        not required.issubset(payload)
        or not set(payload).issubset(required | optional)
        or not isinstance(schema, int)
        or isinstance(schema, bool)
        or schema != 2
        or payload.get("notebook") != str(notebook)
        or payload.get("view") != view
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
        generation=cast(int, generation),
        client_id=cast(str, client_id),
        session_id=cast(str, session_id),
    )


def _nonempty(value: object) -> bool:
    return isinstance(value, str) and bool(value)


def _nonnegative_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0
