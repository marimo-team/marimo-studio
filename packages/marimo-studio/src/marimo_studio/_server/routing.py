"""Recognize Studio-owned page routes without touching server state."""

from __future__ import annotations

from dataclasses import dataclass

from marimo_studio._urls import STUDIO_PATH, SUPPORT_PATH, authored_file_key
from marimo_studio._workspace.models import (
    RESERVED_VIEW_ASSET_NAMES,
    RESERVED_VIEW_NAMES,
    VIEW_PATTERN,
    StudioWorkspace,
)


@dataclass(frozen=True)
class AuthoredViewRoute:
    file_key: str
    relative: str


def authored_view_route(relative: str) -> AuthoredViewRoute | None:
    """Resolve a notebook-scoped route used by browser-relative view files."""
    prefix = f"{SUPPORT_PATH}/notebooks/"
    if not relative.startswith(prefix):
        return None
    token, separator, route = relative.removeprefix(prefix).partition("/views/")
    if not separator:
        return None
    file_key = authored_file_key(token)
    if file_key is None:
        return None
    return AuthoredViewRoute(file_key=file_key, relative=f"/{route}")


def native_editor_target(relative: str) -> str | None:
    """Map the explicit native-editor mount back to Marimo's root routes."""
    prefix = f"{SUPPORT_PATH}/editor"
    if relative.rstrip("/") == prefix:
        return "/"
    if relative.startswith(f"{prefix}/"):
        return f"/{relative.removeprefix(f'{prefix}/')}"
    return None


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


def document_view(relative: str, studio: StudioWorkspace, mode: str) -> str | None:
    """Resolve a presentation document path to its view name."""
    if mode == "run" and relative in {"", "/"}:
        return studio.default_view
    parts = relative.strip("/").split("/")
    if len(parts) == 1:
        return parts[0] if parts[0] in studio.views else None
    if len(parts) == 2 and parts[1] == "index.html":
        return parts[0] if parts[0] in studio.views else None
    return None


def view_asset(relative: str, studio: StudioWorkspace) -> tuple[str, str] | None:
    """Resolve a path below a named view to an authored static asset."""
    parts = relative.strip("/").split("/")
    if len(parts) < 2 or parts[0] not in studio.views:
        return None
    return parts[0], "/".join(parts[1:])


def view_route_alias(relative: str, studio: StudioWorkspace) -> str | None:
    """Resolve browser-relative support and Marimo resource URLs."""
    parts = relative.strip("/").split("/")
    if len(parts) < 2 or parts[0] not in studio.views:
        return None
    nested = parts[1].casefold()
    if nested in RESERVED_VIEW_ASSET_NAMES:
        return "/" + "/".join((nested, *parts[2:]))
    return None


def studio_view(relative: str, studio: StudioWorkspace, mode: str) -> str | None:
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
