"""Recognize Studio-owned page routes without touching server state."""

from __future__ import annotations

from marimo_studio._urls import STUDIO_PATH, SUPPORT_PATH
from marimo_studio._workspace.models import (
    RESERVED_VIEW_ASSET_NAMES,
    RESERVED_VIEW_NAMES,
    VIEW_PATTERN,
    StudioConfig,
)


def could_handle(relative: str, mode: str) -> bool:
    """Return whether a path can belong to Studio in the active mode."""
    if relative == SUPPORT_PATH or relative.startswith(f"{SUPPORT_PATH}/"):
        return True
    if relative in {"", "/"} and mode in {"edit", "run"}:
        return True
    parts = relative.strip("/").split("/")
    if mode == "edit" and parts[0] == STUDIO_PATH.strip("/"):
        return len(parts) in {1, 2}
    return (
        len(parts) >= 1
        and VIEW_PATTERN.fullmatch(parts[0]) is not None
        and parts[0] not in RESERVED_VIEW_NAMES
    )


def document_view(relative: str, studio: StudioConfig, mode: str) -> str | None:
    """Resolve a presentation document path to its view name."""
    if mode == "run" and relative in {"", "/"}:
        return studio.default_view
    parts = relative.strip("/").split("/")
    if len(parts) == 1:
        return parts[0] if parts[0] in studio.views else None
    if len(parts) == 2 and parts[1] == "index.html":
        return parts[0] if parts[0] in studio.views else None
    return None


def view_asset(relative: str, studio: StudioConfig) -> tuple[str, str] | None:
    """Resolve a path below a named view to an authored static asset."""
    parts = relative.strip("/").split("/")
    if len(parts) < 2 or parts[0] not in studio.views:
        return None
    return parts[0], "/".join(parts[1:])


def view_route_alias(relative: str, studio: StudioConfig) -> str | None:
    """Resolve browser-relative support and Marimo resource URLs."""
    parts = relative.strip("/").split("/")
    if len(parts) < 2 or parts[0] not in studio.views:
        return None
    nested = parts[1].casefold()
    if nested in RESERVED_VIEW_ASSET_NAMES:
        return "/" + "/".join((nested, *parts[2:]))
    return None


def studio_view(relative: str, studio: StudioConfig, mode: str) -> str | None:
    """Resolve an edit workspace path to its selected view name."""
    if mode != "edit":
        return None
    parts = relative.strip("/").split("/")
    if parts == [STUDIO_PATH.strip("/")]:
        return studio.default_view
    if len(parts) == 2 and parts[0] == STUDIO_PATH.strip("/"):
        return parts[1] if parts[1] in studio.views else None
    return None


def is_studio_landing(relative: str, mode: str) -> bool:
    """Return whether the request should enter the edit workspace."""
    return mode == "edit" and relative in {"", "/"}
