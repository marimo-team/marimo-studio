"""Validate JSON records exchanged by Studio agent clients and routes."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlsplit

from marimo_studio._browser_client.records import PreviewAutomationTarget, ShowResult
from marimo_studio._workspace.ownership import (
    ObservedViewOwner,
    observed_view_owner,
)
from marimo_studio.errors import CapabilityInputError, ProtocolError


@dataclass(frozen=True)
class ViewShowRequest:
    """Show a view in one connected Studio tab."""

    view: str
    browser_client: str | None = None
    owner: ObservedViewOwner | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.view, str) or not self.view:
            raise CapabilityInputError(
                "invalid-show-request",
                "view",
                "view must be a non-empty string",
            )
        if self.browser_client is not None and (
            not isinstance(self.browser_client, str) or not self.browser_client
        ):
            raise CapabilityInputError(
                "invalid-show-request",
                "browser_client",
                "browser_client must be a non-empty string or null",
            )
        if self.owner is not None:
            _require_owner_generation(
                "catalog_generation",
                self.owner.catalog_generation,
            )
            if self.owner.view_generation is not None:
                _require_owner_generation(
                    "view_generation",
                    self.owner.view_generation,
                )

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema": 1,
            "browser_client": self.browser_client,
        }
        if self.owner is not None:
            payload["catalog_generation"] = self.owner.catalog_generation
            payload["view_generation"] = self.owner.view_generation
        return payload

    @classmethod
    def from_dict(cls, view: str, payload: object) -> ViewShowRequest:
        schema = payload.get("schema") if isinstance(payload, dict) else None
        required = {"schema", "browser_client"}
        allowed = {*required, "catalog_generation", "view_generation"}
        if (
            not isinstance(payload, dict)
            or not required.issubset(payload)
            or not set(payload).issubset(allowed)
            or not isinstance(schema, int)
            or isinstance(schema, bool)
            or schema != 1
        ):
            raise CapabilityInputError(
                "invalid-show-request",
                "request",
                "The show request must contain schema and browser_client",
            )
        has_catalog_owner = "catalog_generation" in payload
        has_view_owner = "view_generation" in payload
        if has_catalog_owner != has_view_owner:
            missing = (
                "catalog_generation" if not has_catalog_owner else "view_generation"
            )
            raise CapabilityInputError(
                "invalid-show-request",
                missing,
                "catalog_generation and view_generation must be provided together",
            )
        owner = None
        if has_catalog_owner:
            catalog_generation = payload.get("catalog_generation")
            view_generation = payload.get("view_generation")
            _require_owner_generation("catalog_generation", catalog_generation)
            if view_generation is not None:
                _require_owner_generation("view_generation", view_generation)
            assert isinstance(catalog_generation, str)
            assert isinstance(view_generation, str) or view_generation is None
            owner = observed_view_owner(catalog_generation, view_generation)
        return cls(
            view=view,
            browser_client=payload.get("browser_client"),
            owner=owner,
        )


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


def parse_show_result(
    payload: dict[str, Any],
    notebook: Path,
    view: str,
) -> ShowResult:
    generation = payload.get("generation")
    client_id = payload.get("client_id")
    session_id = payload.get("session_id")
    schema = payload.get("schema")
    required = {
        "schema",
        "notebook",
        "view",
        "generation",
        "session_id",
        "client_id",
        "preview_url",
        "frame_selector",
    }
    if (
        set(payload) != required
        or not isinstance(schema, int)
        or isinstance(schema, bool)
        or schema != 1
        or payload.get("notebook") != str(notebook)
        or payload.get("view") != view
        or not _nonnegative_int(generation)
        or not _nonempty(session_id)
        or not _nonempty(client_id)
    ):
        raise ProtocolError("The Studio show response is invalid.")
    preview = parse_preview_target(payload["preview_url"], payload["frame_selector"])
    return ShowResult(
        notebook=notebook,
        view=view,
        generation=cast(int, generation),
        client_id=cast(str, client_id),
        session_id=cast(str, session_id),
        preview_url=preview.preview_url,
        frame_selector=preview.frame_selector,
    )


def _nonempty(value: object) -> bool:
    return isinstance(value, str) and bool(value)


def _nonnegative_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _require_owner_generation(field: str, generation: object) -> None:
    if (
        not isinstance(generation, str)
        or len(generation) != 64
        or any(character not in "0123456789abcdef" for character in generation)
    ):
        raise CapabilityInputError(
            "invalid-show-request",
            field,
            f"{field} must be a 64-character lowercase hexadecimal string",
        )


def parse_preview_target(url: object, selector: object) -> PreviewAutomationTarget:
    """Validate addressing without interpreting the browser's CSS selector."""
    if (
        not isinstance(url, str)
        or len(url) > 16384
        or not isinstance(selector, str)
        or not selector
    ):
        raise ProtocolError("The Studio preview target is invalid.")
    try:
        parsed = urlsplit(url)
        _ = parsed.port
        valid_url = parsed.scheme in {"http", "https"} and bool(parsed.hostname)
    except ValueError:
        valid_url = False
    if not valid_url or len(selector) > 4096:
        raise ProtocolError("The Studio preview target is invalid.")
    return PreviewAutomationTarget(url, selector)
