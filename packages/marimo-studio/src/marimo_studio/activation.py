"""Activate one Studio view through a live server connection."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from marimo_studio._workspace.models import StudioWorkspace
from marimo_studio.agent_models import ViewActivationResult
from marimo_studio.errors import CapabilityInputError

if TYPE_CHECKING:
    from marimo_studio._agent_transport import StudioServerConnection


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


async def activate_view(
    studio: StudioWorkspace,
    connection: StudioServerConnection,
    name: str,
) -> ViewActivationResult:
    """Select a configured view in one connected Studio browser."""
    from marimo_studio._agent_client import request_view_activation

    return await request_view_activation(
        connection,
        studio.notebook,
        ViewActivationRequest(
            view=name,
            browser_client=connection.browser_client or None,
        ),
    )


__all__ = ["ViewActivationRequest", "ViewActivationResult", "activate_view"]
